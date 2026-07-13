"""Field Brain — NeedsArbiter wired over live FireRed RAM (CORE_GAMEPLAY §10
step 3). The first FireRed host for the drive system:

  perceive (FieldContext: RAM -> named facts)
    -> decide (NeedsArbiter over AGENT_ROOTS.md drives, strategy overrides)
      -> dispatch (Decision.goal -> executor: catch / heal / restock / ...)
        -> report (winning drive + reason to the UI callback)

A Strategy is a PRESET over this brain (CORE_GAMEPLAY §8): drive-priority
overrides + config facts (party_target, wild_available, hunt map) + a
completion test. catch_fill6 is the first preset (build_fill6_brain).

Executors own multi-map errands. Route 1 <-> Viridian travel uses the proven
planner pattern from scripts/route1_to_viridian.py: BFS-flood to the most
reachable tile toward an edge, walk, push across the map connection; wild
battles that interrupt travel are fled (fight as fallback).

Pure logic stays testable: FieldContext and FieldBrain take injected objects
and never import the emulator.
"""
from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import replace

from pokeai.agents.brain.needs import NeedsArbiter
from pokeai.knowledge.roots import Roots, load_roots

# Live-verified map ids.
ROUTE1 = (3, 19)
VIRIDIAN = (3, 1)
# Towns with a live-confirmed mart/center landmark (see skills/services.py).
MART_TOWNS = {VIRIDIAN}


def arbiter_with_overrides(overrides: dict | None = None,
                           roots: Roots | None = None) -> NeedsArbiter:
    """An arbiter whose drive priorities are re-weighted by a strategy preset.
    Priority <= 0 disables a drive outright."""
    roots = roots or load_roots()
    drives = roots.drives
    if overrides:
        drives = [replace(d, priority=overrides.get(d.name, d.priority))
                  for d in drives]
    drives = sorted((d for d in drives if d.priority > 0),
                    key=lambda d: -d.priority)
    return NeedsArbiter(Roots(drives=drives, gates=roots.gates,
                              towns=roots.towns, items=roots.items,
                              gyms=roots.gyms))


class FieldContext:
    """Named facts for drive triggers, computed fresh from RAM each cycle."""

    def __init__(self, reader, nav, config: dict | None = None):
        self.reader = reader
        self.nav = nav
        self.config = dict(config or {})

    def build(self) -> dict:
        details = self.reader.read_party_details()
        count = len(details)
        thp = sum(m["hp"] for m in details)
        tmax = sum(m["max_hp"] for m in details)
        hurt = sum(1 for m in details
                   if m["max_hp"] > 0 and m["hp"] / m["max_hp"] < 0.5)
        cur = tuple(divmod(self.reader.read_current_map(), 256)) \
            if self.nav is None else self.nav.current_map()
        badges = self.reader.read_badges()
        gym = None
        try:
            gym = load_roots().next_gym(badges)
        except Exception:
            pass
        ctx = {
            "party_count": count,
            "party_hp_fraction": thp / max(tmax, 1),
            "fainted_count": sum(1 for m in details
                                 if m["max_hp"] > 0 and m["hp"] == 0),
            "half_party_low": count > 0 and hurt >= math.ceil(count / 2),
            "party_top_level": max((m["level"] for m in details), default=0),
            "money": self.reader.read_money(),
            "ball_count": self.reader.ball_count(),
            "healing_items": self.reader.count_heal_items(),
            "badges": badges,
            "current_map": cur,
            "mart_known": cur in MART_TOWNS or bool(self.config.get("mart_known")),
            "at_gym_town": False,            # no gym town reachable pre-Pewter
            "next_gym_unbeaten": gym is not None,
            "next_gym_recommended_level": gym.recommended_level if gym else 99,
            "exploration_exhausted": False,  # no FireRed stall counter yet
            "always": True,
        }
        # strategy-preset facts (party_target, wild_available, ...) come last so
        # a preset can also pin a computed fact for testing.
        ctx.update(self.config)
        return ctx


class FieldBrain:
    """decide -> dispatch loop. Executors map Decision.goal -> callable(ctx)
    returning a short status string (logged + fed to the next cycle)."""

    def __init__(self, arbiter: NeedsArbiter, context: FieldContext,
                 executors: dict, complete_when=None, narrate=None,
                 on_decision=None):
        self.arbiter = arbiter
        self.context = context
        self.executors = executors
        self.complete_when = complete_when or (lambda ctx: False)
        self.narrate = narrate
        self.on_decision = on_decision

    def run(self, max_cycles: int = 30) -> dict:
        history = []
        for cycle in range(max_cycles):
            ctx = self.context.build()
            if self.complete_when(ctx):
                return {"status": "complete", "cycles": cycle, "history": history}
            d = self.arbiter.decide(ctx)
            if self.on_decision:
                self.on_decision(d, ctx)
            if self.narrate:
                self.narrate(f"[{d.drive}] {d.rationale}")
            ex = self.executors.get(d.goal)
            if ex is None:
                history.append((d.drive, d.goal, "no_executor"))
                if len(history) >= 3 and all(h[2] == "no_executor"
                                             for h in history[-3:]):
                    return {"status": "stuck", "cycles": cycle,
                            "history": history}
                continue
            result = ex(ctx)
            if self.narrate:
                self.narrate(f"[{d.drive}] -> {result}")
            history.append((d.drive, d.goal, result))
        return {"status": "cycle_cap", "cycles": max_cycles, "history": history}


# --------------------------------------------------------------------------
# Live-side helpers (emulator-bound; not imported by the pure tests)
# --------------------------------------------------------------------------

def _moved(b, d) -> bool:
    p0 = b.player_xy()
    b.press_direction_settle(d)
    return b.player_xy() != p0


def in_real_battle(b, battle, catch=None) -> bool:
    """Real-battle test. With a Catch instance, uses the STRONG three-signal
    check (enemy loaded + movement locked + action menu responds) — the weak
    movement-lock-only check false-positives on corridors/dialogues when a
    stale gEnemyParty lingers (e.g. any state saved right after a flee)."""
    if catch is not None:
        return catch.confirm_real_battle()
    return battle.active() and not (_moved(b, "LEFT") or _moved(b, "RIGHT"))


def flee_or_fight(b, battle, catch=None) -> str:
    """Escape a wild battle (RUN = bottom-right of the 2x2 action menu, reached
    by normalizing LEFT+UP then RIGHT+DOWN); fight it out if fleeing fails.
    Proven pattern from scripts/route1_to_viridian.py."""
    for _ in range(4):
        for _ in range(2):
            b.tap("B", 6); time.sleep(0.35)
        b.tap("LEFT", 5); time.sleep(0.2)   # normalize toward FIGHT
        b.tap("UP", 5); time.sleep(0.2)
        b.tap("RIGHT", 6); time.sleep(0.3)  # -> BAG
        b.tap("DOWN", 6); time.sleep(0.3)   # -> RUN
        b.tap("A", 6); time.sleep(0.6)
        for _ in range(4):
            b.tap("B", 6); time.sleep(0.35)
        if not in_real_battle(b, battle, catch):
            return "fled"
    verdict = battle.fight()
    for _ in range(15):
        b.tap("A", 6); time.sleep(0.35)
    return verdict


def _reachable_extreme(nav, direction: str):
    """BFS flood from the player over walkable tiles; return the reachable tile
    furthest toward a map edge (NORTH = smallest y, SOUTH = largest y)."""
    grid = nav.vision.nav_grid()
    start = nav.vision.player_xy()
    walk = grid["walk"] - nav.vision.object_tiles()
    seen = {start}
    q = deque([start])
    best = start

    def better(t, cur):
        if direction == "NORTH":
            return t[1] < cur[1] or (t[1] == cur[1]
                                     and abs(t[0] - start[0]) < abs(cur[0] - start[0]))
        return t[1] > cur[1] or (t[1] == cur[1]
                                 and abs(t[0] - start[0]) < abs(cur[0] - start[0]))

    while q:
        x, y = q.popleft()
        if better((x, y), best):
            best = (x, y)
        for nb in ((x, y - 1), (x, y + 1), (x - 1, y), (x + 1, y)):
            if nb in walk and nb not in seen:
                seen.add(nb)
                q.append(nb)
    return None if best == start else best


def travel(b, nav, battle, reader, target_map: tuple[int, int],
           narrate=None, timeout: float = 420.0, catch=None) -> bool:
    """Walk to an ADJACENT map across an edge connection. Route 1 <-> Viridian:
    north to Viridian, south to Route 1. Wild battles are fled. Ledge-aware by
    construction (nav_grid treats ledges as walls; southbound routes hop via
    the pather's gap-finding as proven in G2)."""
    say = narrate or (lambda m: None)
    cur = nav.current_map()
    if cur == target_map:
        return True
    direction = "NORTH" if target_map == VIRIDIAN else "SOUTH"
    push = "UP" if direction == "NORTH" else "DOWN"
    deadline = time.time() + timeout
    it = 0
    stuck_at = None
    stuck_n = 0
    while time.time() < deadline:
        it += 1
        if nav.current_map() == target_map:
            return True
        # wedge breaker: if the player position froze across iterations, some
        # screen is eating our inputs (forced party menu, odd prompt) — run
        # the battle-interruption resolver, which exits fast when free.
        pos_now = nav.vision.player_xy()
        stuck_n = stuck_n + 1 if pos_now == stuck_at else 0
        stuck_at = pos_now
        if catch is not None and stuck_n >= 2:
            say(f"travel[{it}]: position frozen at {pos_now} - resolving interruptions")
            catch._ride_out_lead_faint()
            stuck_n = 0
            continue
        # interiors are map groups >= 4 (outdoor Kanto is group 3): step
        # outside first — the walk loop and the battle probes assume outdoors,
        # and a stale gEnemyParty misfires the movement-lock check in tight
        # rooms (seen live 2026-07-05: post-heal inside the Center).
        if nav.current_map()[0] != 3:
            say("leaving the building before traveling on")
            if nav.leave_building() is None:
                # a lingering dialogue holds movement (nurse's closing box,
                # live 2026-07-05): close it with A until movement returns
                for _ in range(12):
                    p0 = b.player_xy()
                    b.press_direction_settle("DOWN")
                    if b.player_xy() != p0:
                        break
                    b.tap("A", 6)
                    time.sleep(0.4)
            continue
        if reader.read().all_party_fainted:
            say("blackout during travel")
            return False
        if battle.active() and in_real_battle(b, battle, catch):
            say(f"travel interrupted by a wild battle - {flee_or_fight(b, battle, catch)}")
            continue
        grid = nav.vision.nav_grid()
        px, py = nav.vision.player_xy()
        edge_row = 1 if direction == "NORTH" else grid["h"] - 2
        at_edge = py <= edge_row if direction == "NORTH" else py >= edge_row
        if at_edge:
            say(f"travel[{it}]: at the {direction} edge {px, py} - pushing across")
            for _ in range(4):
                b.press_direction_settle(push)
            continue
        target = _reachable_extreme(nav, direction)
        if not target:
            say(f"travel[{it}]: no reachable progress from {px, py} - nudging")
            _moved(b, "LEFT") or _moved(b, "RIGHT")
            continue
        path = nav.plan(target)
        if not path:
            say(f"travel[{it}]: no path {px, py} -> {target} - nudging")
            _moved(b, "RIGHT")
            continue
        say(f"travel[{it}]: {px, py} -> {target} ({len(path)} steps)")
        nav.walk_path(path)
    say(f"travel to {target_map} timed out")
    return False


def build_fill6_brain(bridge, nav, battle, catch, services, reader,
                      catcher, narrate=None, on_decision=None,
                      target_party: int = 6) -> FieldBrain:
    """The catch_fill6 strategy as a Field Brain preset: fill the party to 6 on
    Route 1, healing at / restocking from Viridian when the drives fire."""
    config = {
        "party_target": target_party,
        "wild_available": True,     # Route 1 grass is the hunting ground
        "mart_known": True,         # Viridian mart is a known landmark
    }
    context = FieldContext(reader, nav, config)
    # prepare/grow/progress are disabled for this preset: shopping for potions
    # and story progress belong to other strategies; every idle moment hunts.
    arbiter = arbiter_with_overrides({"prepare": 0, "grow": 0, "progress": 0,
                                      "explore": 0})
    say = narrate or (lambda m: None)

    def ex_catch(ctx) -> str:
        if not travel(bridge, nav, battle, reader, ROUTE1, narrate=say,
                      catch=catch):
            return "travel_failed"
        res = catcher.run(max_encounters=3, weaken_to=0.30, narrate=say)
        return res["status"]

    def _back_outside() -> None:
        if nav.current_map()[0] != 3:
            nav.leave_building()

    def ex_heal(ctx) -> str:
        if not travel(bridge, nav, battle, reader, VIRIDIAN, narrate=say,
                      catch=catch):
            return "travel_failed"
        ok = services.heal_at_center(VIRIDIAN)
        _back_outside()
        return "healed" if ok else "heal_failed"

    def ex_restock(ctx) -> str:
        if not travel(bridge, nav, battle, reader, VIRIDIAN, narrate=say,
                      catch=catch):
            return "travel_failed"
        want = min(8, max(2, ctx["money"] // 200 - 1))
        res = services.buy_at_mart(qty=want, slot=0, city_map=VIRIDIAN)
        _back_outside()
        return "restocked" if res.get("ok") else f"buy_failed:{res.get('reason')}"

    return FieldBrain(
        arbiter, context,
        # 'explore' is the arbiter's fallback when nothing fires — for this
        # preset that means "party full but mid-HP" (survive needs <35%), so
        # top up at the Center; that walks complete_when over its HP bar.
        executors={"catch": ex_catch, "heal": ex_heal, "restock": ex_restock,
                   "explore": ex_heal},
        complete_when=lambda ctx: (ctx["party_count"] >= target_party
                                   and ctx["party_hp_fraction"] >= 0.85),
        narrate=say, on_decision=on_decision,
    )
