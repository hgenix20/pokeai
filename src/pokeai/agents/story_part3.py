"""Part 3 of the storyline — Viridian to the BOULDER BADGE.

Walkthrough: north out of Viridian across Route 2, through the forest gate
buildings into Viridian Forest, out the north gate to Pewter City; heal at
the Pewter Center; into the Pewter Gym; the aisle trainer's sight line fires
on the walk north; then Brock (Geodude lv12 + Onix lv14) via fight_smart.
PASS = FLAG_BADGE01 (0x820) read back SET from RAM — never narration.

This is the agent-side port of the two live-proven acceptance scripts
(scripts/forest_run.py, G7 2026-07-05, and scripts/brock_run.py, G8
2026-07-05/06), built on the promoted journey arsenal (skills/journey.py).
The hard-won sequences are preserved verbatim — they encode live lessons:

  * WARP-TABLE traversal, northmost warp first ((y, x) minimum): greedy
    edge-flooding DEAD-ENDS in the forest maze (live 2026-07-05: the
    top-right pocket at (28,5) is walled off from the real NW exit); the
    warp table gives the exit deterministically.
  * DUD-doormat sweeps (journey.warp_exit): multi-tile doormats have dead
    tiles (the 7/2 Pallet-door lesson, re-hit live at the forest north
    gate: (6,10)/(8,10) dead, (7,10) real) — try the mat row CENTER-first
    with an outward held push.
  * Gate buildings are map group 15, the forest is (1,0) (forest_grind
    2026-07-05); OTHER interiors mis-entered en route get a plain
    leave_building exit, not warp navigation (a Center's northmost warp is
    its 2F stairs — warping "north" there ping-pongs forever).
  * Blackout IS the recovery path, not a failure: ride the whiteout out on
    A (ride_out_end(button="A", cap=80)) and resume — FireRed respawns the
    party healed at the last Center.
  * Position-freeze wedge breaker: three identical player_xy reads mean
    some screen is eating inputs (forced party menu, move-learning modal's
    cousins) — catch._ride_out_lead_faint() resolves and exits fast when
    actually free.
  * Brock gets fight_smart(turn_cap=60): Onix outlasts the default 30-turn
    cap (brock_run, live 2026-07-05).

FACT-GATED throughout: RAM facts skip whatever already happened, so the
part can resume from anywhere. The badge flag completes the WHOLE part;
map-id facts (already in Pewter / inside the gym / past Viridian) skip the
travel and heal legs. Battles on the road go through the caller's
journey.WildPolicy (trainers fight_smart, wilds flee, catch-when-armed).

Deliberately OMITTED from the script ports: slot saves + screenshots (the
operator workflow's checkpointing, not the agent's) and brock_run's mart
restock detour (services.MARTS now knows Pewter; restocking belongs to the
prepare drive, not the story leg).

hooks.phase/done_task follow the firered_part1.py dashboard pattern; task
ids are p3_route2 / p3_forest / p3_pewter / p3_heal / p3_gym / p3_trainer /
brock.
"""
from __future__ import annotations

import time
from collections import deque

from pokeai.emulator.firered_state_reader import BADGE_FLAG_FIRST
from pokeai.skills.journey import leave_building_safe, warp_exit

# Live-verified map ids (forest_run / forest_grind / brock_run 2026-07-05).
VIRIDIAN = (3, 1)
PEWTER = (3, 2)
ROUTE2 = (3, 20)          # both halves of Route 2 share one map id
FOREST = (1, 0)
GATE_GROUP = 15           # Route 2 gate buildings (forest_grind 2026-07-05)
GYM = (6, 2)              # Pewter Gym interior (brock_run 2026-07-05)
PEWTER_GROUP = 6          # Pewter interiors (gym/mart/center/museum)

FLAG_BADGE01 = BADGE_FLAG_FIRST      # 0x820 — the Boulder Badge RAM flag

_TRAVEL_TASKS = ("p3_route2", "p3_forest", "p3_pewter")
_ALL_TASKS = (*_TRAVEL_TASKS, "p3_heal", "p3_gym", "p3_trainer", "brock")


class _NoHooks:
    def phase(self, task_id, action): ...
    def done_task(self, task_id): ...


def _northmost(warps: list[dict]) -> dict:
    """The forest/gate exit pick: minimum (y, x). The warp TABLE, not the
    collision grid, names the north exit (forest_run 2026-07-05 — greedy
    flooding dead-ends in the maze; do not 'simplify' back to flooding)."""
    return min(warps, key=lambda t: (t["y"], t["x"]))


def _flood_north(nav):
    """Furthest REACHABLE tile toward the north edge, ledge-hop aware.

    Exact port of forest_run.flood_north (2026-07-05) — kept over
    journey.flood_dir because of the lateral tiebreak (same y prefers the
    tile nearest the player's column): it keeps the walker centered on
    Route 2's braided lanes instead of drifting into fenced side pockets."""
    delta = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
    g = nav.vision.nav_grid()
    walk = g["walk"] - nav.vision.object_tiles()
    ledge_dir = g.get("ledge_dir", {})
    start = nav.vision.player_xy()
    seen = {start}
    q = deque([start])
    best = start
    while q:
        x, y = q.popleft()
        if y < best[1] or (y == best[1] and abs(x - start[0]) < abs(best[0] - start[0])):
            best = (x, y)
        for name, (dx, dy) in delta.items():
            nxt = (x + dx, y + dy)
            if ledge_dir.get(nxt) == name:
                land = (x + 2 * dx, y + 2 * dy)
                if land in walk and land not in seen:
                    seen.add(land)
                    q.append(land)
            elif nxt in walk and nxt not in seen:
                seen.add(nxt)
                q.append(nxt)
    return None if best == start else best


def _travel_to_pewter(b, reader, nav, ow, battle, catch, policy,
                      h, finish, say, budget: float) -> bool:
    """Viridian -> Route 2 -> gates -> Viridian Forest -> Pewter City.

    forest_run's main loop, verbatim in structure: map-transition logging,
    Pewter break, blackout ride-out, battles (via the caller's WildPolicy —
    the same trainer-fight/wild-flee split forest_run inlined), the
    position-freeze wedge breaker, then movement (warp table in gates and
    forest, north flood-walk outdoors). Marks the travel tasks as their map
    facts appear."""
    last_map = None
    deadline = time.time() + budget
    stuck_at, stuck_n = None, 0
    while time.time() < deadline:
        m = nav.current_map()
        if m != last_map:
            say(f"MAP {m} (pos {nav.vision.player_xy()})")
            last_map = m
            if m == ROUTE2 or m == FOREST or m[0] == GATE_GROUP:
                finish("p3_route2")       # map fact: Viridian is behind us
            if m == FOREST:
                h.phase("p3_forest",
                        "Viridian Forest — following the warp table north")
        if m == PEWTER:
            for tid in _TRAVEL_TASKS:
                finish(tid)
            h.phase("p3_pewter", "Pewter City reached!")
            return True

        if reader.read().all_party_fainted:
            say("BLACKOUT - riding the whiteout back to the Center")
            battle.ride_out_end(button="A", cap=80)
            continue

        res = policy.handle()
        if res:
            say(f"battle en route -> {res}")
            continue

        # position-freeze wedge breaker (forest_run 2026-07-05)
        pos_now = nav.vision.player_xy()
        stuck_n = stuck_n + 1 if pos_now == stuck_at else 0
        stuck_at = pos_now
        if stuck_n >= 3:
            say(f"position frozen at {pos_now} - resolving")
            catch._ride_out_lead_faint()
            stuck_n = 0
            continue

        if m == FOREST or m[0] == GATE_GROUP:
            # gates AND the forest are warp-connected: exit by warp table,
            # northmost first, dud-doormat sweep included
            if not warp_exit(b, nav, ow, _northmost, narrate=say):
                say("  warp exit failed; retrying")
            continue
        if m[0] != 3:
            # a stray building mis-entered en route: plain exit, not warps
            # (forest_grind's refinement of forest_run's blanket rule)
            leave_building_safe(b, nav)
            continue

        px, py = nav.vision.player_xy()
        if py <= 1:
            for _ in range(4):
                b.press_direction_settle("UP")
            continue
        target = _flood_north(nav)
        if not target:
            p0 = b.player_xy()
            b.press_direction_settle("LEFT")
            if b.player_xy() == p0:
                b.press_direction_settle("RIGHT")
            continue
        path = nav.plan(target)
        if not path:
            b.press_direction_settle("RIGHT")
            continue
        nav.walk_path(path)
    say("travel to Pewter timed out")
    return False


def _back_outside(b, nav, ow, cap: int = 6) -> None:
    """Step back into the city after an interior (post-heal, or a Pewter
    interior resume). Bounded: leave_building_safe already carries the
    lingering-dialogue B-ride (an A would re-open the nurse's menu —
    B-vs-A lesson, live 2026-07-05)."""
    for _ in range(cap):
        if nav.current_map()[0] == 3:
            return
        leave_building_safe(b, nav)
        ow.wait_control(10)


def _enter_gym(b, nav, ow, say) -> bool:
    """From Pewter, enter the gym via its warp-table door ((destGroup,
    destMap) == GYM). take_warp first; a held UP into the mat is the dud-
    doormat fallback (brock_run 2026-07-05)."""
    gymdoors = [w for w in nav.map_warps_full()
                if (w["destGroup"], w["destMap"]) == GYM]
    if not gymdoors:
        say("no gym door in the warp table")
        return False
    w = gymdoors[0]
    nav.go_to((w["x"], w["y"] + 1), attempts=8)
    if nav.take_warp((w["x"], w["y"])) != GYM:
        b.press_button_held("UP", 32)
        time.sleep(1.0)
    if nav.current_map() != GYM:
        return False
    ow.wait_control(10)
    say(f"in the gym at {nav.vision.player_xy()}; "
        f"npcs {sorted(nav.vision.object_tiles())}")
    return True


def _gym_leg(b, reader, nav, ow, battle, catch, finish, say,
             budget: float) -> bool:
    """Inside the gym: walk the aisle north (the trainer's sight line
    fires), then challenge the top NPC — Brock. brock_run's loop verbatim:
    badge-flag gate first every turn, blackout = ride out + walk back (the
    Center respawn heals implicitly), fight_smart(turn_cap=60) for every
    gym battle, bounce-outside recovery, adjacency interact on the leader.
    True only when FLAG_BADGE01 reads SET."""
    def reenter():
        gymdoors = [w2 for w2 in nav.map_warps_full()
                    if (w2["destGroup"], w2["destMap"]) == GYM]
        if gymdoors:
            w2 = gymdoors[0]
            nav.go_to((w2["x"], w2["y"] + 1), attempts=10)
            if nav.take_warp((w2["x"], w2["y"])) != GYM:
                b.press_button_held("UP", 32)
                time.sleep(1.0)

    deadline = time.time() + budget
    while time.time() < deadline:
        if reader.read_flag(FLAG_BADGE01):
            return True
        if reader.read().all_party_fainted:
            say("BLACKOUT in the gym - riding out + walking back")
            battle.ride_out_end(button="A", cap=80)
            reenter()
            continue
        if battle.active() and catch.confirm_real_battle():
            res = battle.fight_smart(narrate=say, turn_cap=60)
            say(f"gym battle -> {res}")
            if res == "win" and not reader.read_flag(FLAG_BADGE01):
                finish("p3_trainer")      # a win without the badge = the aisle
            continue
        if nav.current_map() != GYM:
            # got bounced outside somehow: re-enter
            reenter()
            continue
        # move north toward Brock; interact when adjacent to the top NPC
        npcs = sorted(nav.vision.object_tiles(), key=lambda t: t[1])
        if npcs:
            brock = npcs[0]
            px, py = nav.vision.player_xy()
            if abs(px - brock[0]) + abs(py - brock[1]) <= 2:
                say(f"challenging the leader at {brock}…")
                ow.interact(brock, rounds=4)
                time.sleep(1.0)
                continue
            nav.go_to((brock[0], brock[1] + 2), attempts=8)
        else:
            p0 = b.player_xy()
            b.press_direction_settle("UP")
            if b.player_xy() == p0:
                b.tap("A", 6)
                time.sleep(0.4)
    say("gym deadline hit without the badge")
    return reader.read_flag(FLAG_BADGE01)


def run_part3(b, reader, nav, ow, svc, battle, catch, policy, hooks=None, *,
              narrate=None, travel_budget: float = 2400.0,
              gym_budget: float = 1500.0) -> bool:
    """Drive Part 3 (Viridian -> forest -> Pewter -> Brock) to the Boulder
    Badge. `policy` is a journey.WildPolicy over (battle, catch); `hooks`
    (the dashboard) gets phase/done_task per firered_part1.py. Returns True
    only when FLAG_BADGE01 verifies in RAM.

    Fact gates, checked in order:
      badge flag set          -> the whole part already happened
      inside the gym (6,2)    -> skip travel + heal, straight to the gauntlet
      Pewter / its interiors  -> skip travel
      Route 2/gates/forest    -> travel resumes mid-journey (route2 done)
    A failed Pewter heal is narrated but NOT fatal: a gym blackout respawns
    the party healed at that same Center (the recovery path is the heal)."""
    h = hooks or _NoHooks()
    say = narrate or (lambda msg: None)
    done: set[str] = set()

    def finish(task_id: str) -> None:
        if task_id not in done:
            done.add(task_id)
            h.done_task(task_id)

    if reader.read_flag(FLAG_BADGE01):
        say("badge01 already set - Part 3 is already complete")
        for tid in _ALL_TASKS:
            finish(tid)
        return True

    m = nav.current_map()
    if m == GYM:
        say("resuming INSIDE the gym - travel and heal are behind us")
        for tid in (*_TRAVEL_TASKS, "p3_heal"):
            finish(tid)
    else:
        if m == PEWTER or m[0] == PEWTER_GROUP:
            say(f"already at Pewter ({m}) - skipping the forest journey")
            for tid in _TRAVEL_TASKS:
                finish(tid)
            _back_outside(b, nav, ow)
        else:
            if m == ROUTE2 or m == FOREST or m[0] == GATE_GROUP:
                finish("p3_route2")       # map fact: Viridian is behind us
            h.phase("p3_route2",
                    "North out of Viridian — Route 2, the gate, the forest")
            if not _travel_to_pewter(b, reader, nav, ow, battle, catch,
                                     policy, h, finish, say, travel_budget):
                h.phase("p3_pewter", "Never reached Pewter — needs a look")
                return False

        h.phase("p3_heal", "Healing at the Pewter Center")
        if svc.heal_at_center(PEWTER):
            h.phase("p3_heal", "Party healed at the Pewter Center")
            finish("p3_heal")
        else:
            h.phase("p3_heal", "Pewter heal unconfirmed — pressing on "
                               "(a blackout respawn heals anyway)")
        _back_outside(b, nav, ow)

        h.phase("p3_gym", "Entering the Pewter Gym")
        if nav.current_map() != GYM and not _enter_gym(b, nav, ow, say):
            h.phase("p3_gym",
                    f"Could not enter the gym ({nav.current_map()}) — needs a look")
            return False
    finish("p3_gym")

    h.phase("brock", "The gym gauntlet — the aisle trainer, then Brock")
    if not _gym_leg(b, reader, nav, ow, battle, catch, finish, say, gym_budget):
        h.phase("brock", "Badge flag never set — needs a look")
        return False
    finish("p3_trainer")                  # badge fact: the aisle is behind us
    h.phase("brock", "BOULDER BADGE — FLAG_BADGE01 verified in RAM!")
    finish("brock")
    return True
