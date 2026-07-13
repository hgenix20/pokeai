"""Journey engine — the proven overworld travel patterns promoted from the
G7/G8 scripts (forest_run/forest_grind/part2_full_test) into one module.

Pieces:
  * flood_dir / cross_edge : ledge-aware travel toward a map edge connection,
    in any of the four directions (G7 was north/south only).
  * warp_exit              : leave a warp-connected map (gate/cave/forest) via
    a chosen warp; DUD-doormat aware (center-first mat sweep + outward push,
    the 7/2 Pallet lesson re-learned at the forest gate).
  * leave_building_safe    : building exit with the lingering-dialogue B-ride.
  * WildPolicy             : per-encounter decision — flee by default, CATCH
    when armed (the B2 catch_next_encounter directive seam) or when the
    caller's policy asks; trainers always fight (fight_smart).
  * Journey.step()         : one loop turn — battles, blackout, wedges, then
    movement toward the current leg's objective.

Everything verifies on RAM ground truth; narration is a side channel.
"""
from __future__ import annotations

import time
from collections import deque

from pokeai.agents.field_brain import flee_or_fight, in_real_battle

DIRS = {
    "NORTH": (0, -1, "UP"),
    "SOUTH": (0, 1, "DOWN"),
    "EAST": (1, 0, "RIGHT"),
    "WEST": (-1, 0, "LEFT"),
}
_STEP = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}


def flood_dir(nav, direction: str):
    """Furthest reachable tile toward a map edge (ledge-hop aware)."""
    dx, dy, _ = DIRS[direction]
    g = nav.vision.nav_grid()
    walk = g["walk"] - nav.vision.object_tiles()
    ledge_dir = g.get("ledge_dir", {})
    start = nav.vision.player_xy()
    seen = {start}
    q = deque([start])
    best = start

    def score(t):
        return t[0] * dx + t[1] * dy

    while q:
        x, y = q.popleft()
        if score((x, y)) > score(best):
            best = (x, y)
        for name, (sx, sy) in _STEP.items():
            nxt = (x + sx, y + sy)
            if ledge_dir.get(nxt) == name:
                land = (x + 2 * sx, y + 2 * sy)
                if land in walk and land not in seen:
                    seen.add(land)
                    q.append(land)
            elif nxt in walk and nxt not in seen:
                seen.add(nxt)
                q.append(nxt)
    return None if best == start else best


def at_edge(nav, direction: str) -> bool:
    g = nav.vision.nav_grid()
    px, py = nav.vision.player_xy()
    return {"NORTH": py <= 1, "SOUTH": py >= g["h"] - 2,
            "EAST": px >= g["w"] - 2, "WEST": px <= 1}[direction]


def leave_building_safe(b, nav) -> None:
    if nav.leave_building() is None:
        for _ in range(10):
            p0 = b.player_xy()
            b.press_direction_settle("DOWN")
            if b.player_xy() != p0:
                return
            b.tap("B", 5)
            time.sleep(0.4)


def warp_exit(b, nav, ow, pick, narrate=None) -> bool:
    """Exit the current map via the warp chosen by `pick(warps)`. Tries every
    warp on the picked mat row CENTER-first with an outward push (dud tiles)."""
    say = narrate or (lambda m: None)
    cur = nav.current_map()
    warps = nav.map_warps_full()
    if not warps:
        return False
    w0 = pick(warps)
    row = [w for w in warps if abs(w["y"] - w0["y"]) <= 1]
    cx = sum(w["x"] for w in row) / len(row)
    row.sort(key=lambda w: abs(w["x"] - cx))
    g = nav.vision.nav_grid()
    outward = "DOWN" if w0["y"] >= g["h"] // 2 else "UP"
    inward_dy = -1 if outward == "DOWN" else 1
    for w in row:
        say(f"  {cur}: warp ({w['x']},{w['y']}) -> ({w['destGroup']},{w['destMap']})")
        nb = (w["x"], w["y"] + inward_dy)
        if nav.vision.walkable(*nb) and nav.go_to(nb, attempts=10):
            b.press_button_held(outward, 32)
            time.sleep(1.0)
            if nav.current_map() != cur:
                ow.wait_control(10)
                return True
        if nav.take_warp((w["x"], w["y"])) is not None or nav.current_map() != cur:
            ow.wait_control(10)
            return True
    return nav.current_map() != cur


class WildPolicy:
    """Flee wilds by default; CATCH when should_catch() says so (the armed
    catch_next directive, or a roster policy). Trainers always fight.

    Nuzlocke wiring: when a live `ruleset` is passed, the catch decision comes
    from `ruleset.should_catch(area, party_species, enemy_species)` (the
    first-encounter + dupes + species clauses) and a caught mon is recorded via
    `ruleset.on_caught(area, species)` + nicknamed via `ruleset.nickname_for`.
    Without a ruleset the behavior is unchanged (the no-arg `should_catch`
    callable, e.g. the armed catch_next flag). `area_fn` returns the current
    (map_group, map_num) so first-encounter is scoped per area."""

    def __init__(self, b, battle, catch, should_catch=None, narrate=None,
                 on_caught=None, ruleset=None, area_fn=None):
        self.b = b
        self.battle = battle
        self.catch = catch
        self.should_catch = should_catch or (lambda: False)
        self.say = narrate or (lambda m: None)
        self.on_caught = on_caught
        self.ruleset = ruleset
        self.area_fn = area_fn

    def enemy_species(self) -> int:
        """Species id of the active wild (0 on any read surprise). Feeds the
        Nuzlocke dupes/species clauses."""
        try:
            return self.battle.enemy_species()
        except Exception:
            return 0

    def _area(self):
        try:
            return self.area_fn() if self.area_fn else (-1, -1)
        except Exception:
            return (-1, -1)

    def _should_catch_now(self, enc_species: int) -> bool:
        if self.ruleset is not None and self.ruleset.is_active():
            return self.ruleset.should_catch(
                self._area(), self.catch.party_species(), enc_species)
        return bool(self.should_catch())

    def handle(self, assume_locked: bool = False) -> str | None:
        """Resolve any REAL battle; returns the outcome or None if no battle.
        `assume_locked=True` when the caller already observed the player
        frozen (a walk press was eaten): skips confirm_real_battle's
        LEFT/RIGHT movement probe, which otherwise displaces the player
        1-2 tiles whenever the battle has actually ended (nav audit
        2026-07-06 - it jiggled the walker between every retry)."""
        if not (self.battle.active()
                and self.catch.confirm_real_battle(assume_locked=assume_locked)):
            return None
        if self.battle.is_trainer_battle():
            res = self.battle.fight_smart(narrate=self.say)
            self.say(f"trainer battle -> {res}")
            return f"trainer:{res}"
        enc_species = self.enemy_species()
        if self._should_catch_now(enc_species):
            nick = (self.ruleset.nickname_for(enc_species)
                    if self.ruleset is not None else None)
            party0 = self.catch.party_count()
            res = self.catch.attempt(max_balls=5, narrate=self.say,
                                     weaken_to=0.30, nickname=nick)
            caught = self.catch.party_count() > party0
            self.say(f"armed catch -> {res} (party +{int(caught)})")
            if caught:
                if self.ruleset is not None:
                    self.ruleset.on_caught(self._area(), enc_species)
                if self.on_caught:
                    self.on_caught()
            return f"catch:{res}"
        res = flee_or_fight(self.b, self.battle, self.catch)
        self.say(f"wild battle -> {res}")
        return f"wild:{res}"


def cross_edge(b, nav, ow, reader, policy: WildPolicy, want, direction: str,
               budget: float = 420.0, narrate=None) -> bool:
    """Walk across the current map and over the `direction` edge connection.
    `want` = the expected destination map id, or None to accept any change."""
    say = narrate or (lambda m: None)
    cur = nav.current_map()
    _, _, push = DIRS[direction]
    deadline = time.time() + budget
    stuck_at, stuck_n = None, 0
    edge_rounds = 0
    extensions = 0
    while time.time() < deadline:
        m = nav.current_map()
        if m != cur:
            return want is None or m == want
        if reader.read().all_party_fainted:
            say("blackout during the crossing")
            policy.battle.ride_out_end(button="A", cap=80)
            return False
        if policy.handle():
            # a resolved battle is PROGRESS, not stalling: a gauntlet route's
            # trainer fights must not eat the walking budget (a crossing died
            # one tile from the edge this way, live 2026-07-05). HARD-CAPPED
            # at 3 extensions: unbounded refills let corner grass keep a
            # dead-end leg alive forever (also live 2026-07-05).
            if deadline - time.time() < 120 and extensions < 3:
                deadline += 120
                extensions += 1
            continue
        if m[0] != 3:
            leave_building_safe(b, nav)
            continue
        pos = nav.vision.player_xy()
        stuck_n = stuck_n + 1 if pos == stuck_at else 0
        stuck_at = pos
        if stuck_n >= 3:
            say(f"position frozen at {pos} - resolving")
            policy.catch._ride_out_lead_faint()
            stuck_n = 0
            continue
        if at_edge(nav, direction):
            edge_rounds += 1
            if edge_rounds >= 5:
                # a map edge with no connection (Route 3's east end bends
                # north instead, live 2026-07-05): yield so the caller can
                # try another direction instead of pushing forever
                say(f"edge toward {direction} is a dead end")
                return False
            for _ in range(4):
                b.press_direction_settle(push)
            continue
        edge_rounds = 0
        target = flood_dir(nav, direction)
        if not target:
            # we ARE the local extreme toward `direction`: push into the
            # boundary — a connection fires, a wall no-ops (Route 3's north
            # corridor tops out at y=3, below the at_edge threshold, live
            # 2026-07-05). Lateral nudge only if the pushes did nothing.
            p0 = b.player_xy()
            for _ in range(4):
                b.press_direction_settle(push)
            if nav.current_map() != cur:
                continue
            if b.player_xy() == p0:
                b.press_direction_settle("LEFT")
                if b.player_xy() == p0:
                    b.press_direction_settle("RIGHT")
            continue
        path = nav.plan(target)
        if not path:
            b.press_direction_settle(push)
            continue
        say(f"cross[{direction}]: {pos} -> {target} ({len(path)} steps)")
        nav.walk_path(path)
    say(f"crossing toward {want} timed out")
    return False
