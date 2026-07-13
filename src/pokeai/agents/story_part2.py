"""Part 2 of the storyline - the Oak's Parcel errand (the Viridian round trip).

Walkthrough: Route 1 south end -> north to Viridian, heal at the Center,
receive Oak's Parcel at the Mart -> back south across Route 1 to Pallet ->
hand the parcel to Oak (Pokedex + 5 Poke Balls) -> Town Map from Daisy in the
rival's house -> north to Viridian again -> Teachy TV from the old man on the
north path -> out the north-west path onto Route 2 (the forest approach).

This is the run_part1-style promotion of scripts/part2_full_test.py's G3
acceptance flow (every stage live-verified 2026-07-05), with the multi-map
legs delegated to skills/journey.py - the module those scripts' travel
patterns were promoted into (cross_edge IS part2_full_test's cross_map,
refined through G11). The hard-won sequences are preserved verbatim:

  * Mart scene (stage B): the clerk scene is self-starting, so plain A-taps
    both open and advance it; the loop polls the BAG (KeyItem 349) because
    the parcel lands MID-scene, then 12 extra taps + wait_control ride out
    the post-parcel text before leaving.
  * Oak hand-off (stage D): walk to the lab TOP-CENTER (6,3) FIRST so
    off-camera Oak loads, then approach UP - the scene auto-fires
    (scripts/deliver_oak.py's proven mechanic). Ride the WHOLE scene: the
    parcel leaves the bag mid-scene but the Pokedex flag and the 5 Balls
    only land at the end, so "bag empty" alone is not "scene over".
  * Daisy / the old man (stages E/G): interact -> advance -> wait, verified
    against the bag after EVERY NPC. Item ids 361 (Town Map) and 366
    (Teachy TV) were discovered live 2026-07-05 by exactly that key-item
    delta and are named constants in firered_state_reader now.
  * Dud doormats: a rival-house door candidate whose take_warp returns None
    (or leaves us still in Pallet) is skipped, never forced - the 7/2
    Pallet lesson.

Unlike run_part1 (FIXLIST FL-7: not resumable), EVERY step here is gated on
a RAM fact and SKIPPED when its outcome already holds, so the driver can
re-enter this function after a crash / usage-limit stop at any point in the
errand. Facts: bag counts (parcel 349 / Town Map 361 / Teachy TV 366) via
reader.count_item, FLAG_SYS_POKEDEX_GET (0x829) via reader.read_flag, and
map ids via nav.current_map. Slot saves are deliberately NOT taken here:
the driver owns checkpointing.
"""
from __future__ import annotations

import time

from pokeai.emulator.firered_state_reader import (
    ITEM_OAKS_PARCEL,
    ITEM_TEACHY_TV,
    ITEM_TOWN_MAP,
)
from pokeai.skills.journey import cross_edge, flood_dir, leave_building_safe

# Live-verified map ids (scripts/part2_full_test.py; ROUTE2 from the G7
# forest run, scripts/forest_grind.py).
VIRIDIAN, ROUTE1, PALLET, ROUTE2 = (3, 1), (3, 19), (3, 0), (3, 20)
OAKLAB = (4, 3)            # Oak's lab interior
PLAYER_HOUSE_1F = (4, 0)   # excluded when hunting the rival's house
MART_MAP = (5, 3)          # Viridian Mart interior
# Viridian waypoints to the Mart door, walked IN ORDER so each BFS plan stays
# local (long single plans die on NPC drift - the G2 lesson kept through G3).
MART_ROUTE = [(24, 32), (36, 32), (36, 20)]
LAB_TOP_CENTER = (6, 3)    # stand here so off-camera Oak loads (deliver_oak.py)
FLAG_SYS_POKEDEX_GET = 0x829

# Task ids surfaced to hooks (quest board), in story order.
STEP_IDS = ("p2_to_viridian", "p2_heal", "p2_parcel", "p2_deliver",
            "p2_townmap", "p2_teachytv", "p2_route2")

# The part-2 overworld rail, south to north. Legs between neighbours are edge
# CONNECTIONS (not warps): Viridian->Route2 northbound is the G7-proven leg
# (scripts/forest_run.py, 2026-07-05); Route2->Viridian southbound is the same
# engine run in reverse (symmetric, engine-trusted) so a resume stranded on
# Route 2 with a hurt party can still reach the Viridian Center.
_CHAIN = (PALLET, ROUTE1, VIRIDIAN, ROUTE2)


# --------------------------------------------------------------------------
# RAM facts - the resume gates. Each is the OUTCOME of exactly one step.
# --------------------------------------------------------------------------

def have_parcel(reader) -> bool:
    """Oak's Parcel (KeyItem 349) is in the bag: the Mart pickup happened."""
    return bool(reader.count_item(ITEM_OAKS_PARCEL))


def parcel_delivered(reader) -> bool:
    """Oak's hand-off is DONE. The parcel leaving the bag alone is NOT proof
    (it leaves mid-scene, live 2026-07-05): the Pokedex system flag 0x829 is
    the end-of-scene fact, set together with the 5 Balls."""
    return bool(reader.read_flag(FLAG_SYS_POKEDEX_GET))


def have_town_map(reader) -> bool:
    """Town Map (KeyItem 361, discovered live 2026-07-05) is in the bag."""
    return bool(reader.count_item(ITEM_TOWN_MAP))


def have_teachy_tv(reader) -> bool:
    """Teachy TV (KeyItem 366, discovered live 2026-07-05) is in the bag."""
    return bool(reader.count_item(ITEM_TEACHY_TV))


def _party_full(reader) -> bool:
    s = reader.read()
    return s.party_count > 0 and s.party_total_hp == s.party_total_max_hp


def pending_steps(reader, nav) -> list[str]:
    """Task ids whose outcome fact does NOT yet hold - the resume plan, in
    story order. run_part2 re-checks every gate against fresh RAM right
    before its step (facts move during the run); this helper exists so the
    driver/UI can preview the plan, and so the gates are unit-testable."""
    past_pickup = have_parcel(reader) or parcel_delivered(reader)
    pend = []
    if not past_pickup:
        pend.append("p2_to_viridian")
    if not _party_full(reader):
        pend.append("p2_heal")
    if not past_pickup:
        pend.append("p2_parcel")
    if not parcel_delivered(reader):
        pend.append("p2_deliver")
    if not have_town_map(reader):
        pend.append("p2_townmap")
    if not have_teachy_tv(reader):
        pend.append("p2_teachytv")
    if nav.current_map() != ROUTE2:
        pend.append("p2_route2")
    return pend


# --------------------------------------------------------------------------
# Travel
# --------------------------------------------------------------------------

def _travel(b, reader, nav, ow, policy, target, narrate=None) -> bool:
    """Walk the Pallet <-> Route 1 <-> Viridian <-> Route 2 rail to `target`,
    one edge connection at a time via journey.cross_edge (the promoted
    cross_map: ledge-hop flooding, WildPolicy battle handling, the wedge
    breaker, the dead-end edge yield). Starts by leaving any building a
    resume left us inside (checkpoints were historically taken in the Mart
    and in the lab). Route 1 NORTHBOUND keeps the 420s budget the G3 run
    needed against its dense grass; every other leg keeps the original 240s
    (part2_full_test.py stage C/F values)."""
    for _ in range(6):                       # 3 legs max + building exit + slack
        if nav.current_map()[0] != 3:        # interiors are map groups >= 4
            leave_building_safe(b, nav)
            ow.wait_control(12)
        cur = nav.current_map()
        if cur == target:
            return True
        if cur not in _CHAIN or target not in _CHAIN:
            return False                     # off the part-2 rail: driver's call
        i, j = _CHAIN.index(cur), _CHAIN.index(target)
        step = 1 if j > i else -1
        direction = "NORTH" if step > 0 else "SOUTH"
        nxt = _CHAIN[i + step]
        budget = 420.0 if (cur == ROUTE1 and direction == "NORTH") else 240.0
        if not cross_edge(b, nav, ow, reader, policy, nxt, direction,
                          budget=budget, narrate=narrate):
            return False
    return nav.current_map() == target


# --------------------------------------------------------------------------
# Stage actions - part2_full_test.py ports, verbatim sequences
# --------------------------------------------------------------------------

def _get_parcel(b, reader, nav, ow, narrate=None) -> bool:
    """Viridian Mart pickup (stage B verbatim). Waypoint-hop to the door,
    push UP into it (held 32 frames, up to 3 tries - the doormat is one tile
    deep), then A-tap against the BAG until KeyItem 349 lands; the extra 12
    taps + wait_control ride out the clerk's post-parcel line so control is
    back before we leave."""
    say = narrate or (lambda m: None)
    for wp in MART_ROUTE:
        nav.go_to(wp, attempts=8)
    city = nav.current_map()
    for _ in range(3):
        b.press_button_held("UP", 32)
        time.sleep(1.0)
        if nav.current_map() != city:
            break
    if nav.current_map() != MART_MAP:
        say(f"not in the Mart: {nav.current_map()}")
        return False
    ow.wait_control(12)
    for _ in range(50):
        if reader.count_item(ITEM_OAKS_PARCEL):
            break
        b.tap("A", 6)
        time.sleep(0.35)
    for _ in range(12):
        b.tap("A", 6)
        time.sleep(0.3)
    ow.wait_control(15)
    if not have_parcel(reader):
        return False
    say("parcel in bag (KeyItem 349)")
    nav.leave_building()
    ow.wait_control(12)
    return True


def _enter_lab(nav, ow) -> bool:
    """Enter Oak's lab from Pallet via its recorded warp (stage C tail).
    No-op when a resume already put us inside (the old slot-7 checkpoint)."""
    if nav.current_map() == OAKLAB:
        return True
    labdoors = [w for w in nav.map_warps_full()
                if (w["destGroup"], w["destMap"]) == OAKLAB]
    for w in labdoors:
        nav.go_to((w["x"], w["y"] + 1), attempts=8)
        if nav.take_warp((w["x"], w["y"])) == OAKLAB:
            ow.wait_control(15)
            return True
    return nav.current_map() == OAKLAB


def _deliver_to_oak(b, reader, nav, ow, narrate=None) -> bool:
    """Hand Oak the parcel and ride the WHOLE scene (stage D verbatim).

    Oak stands at the lab TOP-CENTER, off-camera from the entrance: walk to
    (6,3) first so he loads, then approach UP - the parcel scene auto-fires
    (deliver_oak.py's proven mechanic). If the approach never opens a
    dialogue, fall back to interacting with the top-most NPCs directly.
    Success = parcel OUT of the bag + balls >= 5 + flag 0x829 SET; any one
    alone is a half-finished scene."""
    say = narrate or (lambda m: None)

    def ride_scene(cap=260) -> bool:
        # The parcel leaves the bag MID-scene: only bag-empty AND dialogue
        # closed AND control back means the scene really ended (the Pokedex
        # + 5 Balls come after the parcel line).
        for _ in range(cap):
            if not reader.count_item(ITEM_OAKS_PARCEL):
                if not ow.dialogue_open() and ow.has_control():
                    return True
            b.tap("A", 6)
            time.sleep(0.3)
        return not reader.count_item(ITEM_OAKS_PARCEL)

    nav.go_to(LAB_TOP_CENTER, attempts=10)
    time.sleep(0.4)
    npcs = sorted(nav.vision.object_tiles(), key=lambda t: (t[1], t[0]))
    say(f"lab npcs from top-center: {npcs}")
    for _ in range(5):
        if not reader.count_item(ITEM_OAKS_PARCEL):
            break
        moved = b.press_direction_settle("UP")
        if ow.dialogue_open():
            say("dialogue opened on approach - riding the delivery scene")
            ride_scene()
            break
        if not moved:
            break
    if reader.count_item(ITEM_OAKS_PARCEL):
        for cand in npcs[:5]:
            say(f"trying NPC {cand}")
            ow.interact(cand, rounds=3)
            ride_scene(cap=120)
            if not reader.count_item(ITEM_OAKS_PARCEL):
                break
    ow.wait_control(20)
    balls = reader.ball_count()
    dex = parcel_delivered(reader)
    say(f"parcel gone: {not have_parcel(reader)}  balls {balls}  dexflag {dex}")
    return (not have_parcel(reader)) and balls >= 5 and dex


def _get_town_map(reader, nav, ow, narrate=None) -> bool:
    """Town Map from Daisy (stage E verbatim). The rival's house is found by
    elimination: any Pallet door that is NOT the lab and NOT the player's
    house. Dud doormats (take_warp None / still in Pallet) are skipped, never
    forced. Every NPC inside is tried; the bag (item 361) is the ground truth
    after each conversation, and we leave the building before reporting."""
    say = narrate or (lambda m: None)
    rival_doors = [w for w in nav.map_warps_full()
                   if (w["destGroup"], w["destMap"]) not in (OAKLAB, PLAYER_HOUSE_1F)]
    say(f"rival-house candidate doors: "
        f"{[((w['x'], w['y']), (w['destGroup'], w['destMap'])) for w in rival_doors]}")
    for w in rival_doors:
        nav.go_to((w["x"], w["y"] + 1), attempts=8)
        dest = nav.take_warp((w["x"], w["y"]))
        if dest is None or nav.current_map() == PALLET:
            continue
        ow.wait_control(12)
        say(f"inside {nav.current_map()}; npcs {sorted(nav.vision.object_tiles())}")
        got = False
        for npc in sorted(nav.vision.object_tiles()):
            ow.interact(npc, rounds=4)
            ow.advance_dialogue(cap=40)
            ow.wait_control(10)
            if have_town_map(reader):
                say(f"TOWN MAP received (door ({w['x']},{w['y']}), npc {npc})")
                got = True
                break
        nav.leave_building()
        ow.wait_control(12)
        if got:
            return True
    return have_town_map(reader)


def _get_teachy_tv(reader, nav, ow, narrate=None) -> bool:
    """Teachy TV from the old man on Viridian's north path (stage G
    verbatim). His tile was never recorded: candidates come from the
    live-verified box (12 <= x <= 26, at-or-north-of the player, floor 12),
    nearest-the-path first (sort by (y, |x - 18|)). He may run the whole
    catching demo: advance -> ride_cutscene(90) -> advance rides it out.
    Between attempts, flood NORTH (ledge-aware) and rescan further up."""
    say = narrate or (lambda m: None)
    for _attempt in range(3):
        py = nav.vision.player_xy()[1]
        cands = [t for t in nav.vision.object_tiles()
                 if 12 <= t[0] <= 26 and t[1] <= max(12, py)]
        cands.sort(key=lambda t: (t[1], abs(t[0] - 18)))
        say(f"north-path npc candidates: {cands}")
        for npc in cands:
            ow.interact(npc, rounds=4)
            # he may offer the catching demo: ride the whole scene with A
            ow.advance_dialogue(cap=80)
            ow.ride_cutscene(timeout=90)
            ow.advance_dialogue(cap=40)
            ow.wait_control(15)
            if have_teachy_tv(reader):
                say(f"TEACHY TV received (npc {npc})")
                return True
        # walk further north up the path and rescan
        tgt = flood_dir(nav, "NORTH")
        if tgt:
            nav.go_to((tgt[0], max(tgt[1], 4)), attempts=8)
    return have_teachy_tv(reader)


# --------------------------------------------------------------------------
# The part runner
# --------------------------------------------------------------------------

class _NoHooks:
    def phase(self, task_id, action): ...
    def done_task(self, task_id): ...


def run_part2(b, reader, nav, ow, svc, policy, hooks=None) -> bool:
    """Drive Part 2 end to end, resuming from wherever the facts say we are.

    `b`=bridge, `reader`=FireRedStateReader, `nav`=Navigator, `ow`=Overworld,
    `svc`=Services, `policy`=journey.WildPolicy (owns battle/catch for the
    crossings). `hooks` (the dashboard) gets phase() narration and
    done_task() for every step id in STEP_IDS - including steps skipped
    because their outcome fact already held, so the quest board rolls
    forward on a resume exactly like run_part1 rolls off the intro quests.
    Returns True only when every outcome fact holds (standing on Route 2
    with Pokedex, 5+ Balls, Town Map and Teachy TV banked)."""
    h = hooks or _NoHooks()

    def narrator(task_id):
        return lambda msg: h.phase(task_id, msg)

    # --- Step 1: Route 1 south end -> north to Viridian ---
    # Moot once the parcel is in the bag or delivered: the story has already
    # been north (and the later steps drive all remaining travel themselves).
    if have_parcel(reader) or parcel_delivered(reader):
        h.done_task("p2_to_viridian")
    else:
        h.phase("p2_to_viridian", "Heading north to Viridian City")
        if not _travel(b, reader, nav, ow, policy, VIRIDIAN,
                       narrate=narrator("p2_to_viridian")):
            h.phase("p2_to_viridian", "Couldn't reach Viridian - needs a look")
            return False
        h.done_task("p2_to_viridian")

    # --- Step 2: heal at the Viridian Center ---
    # Outcome-gated on full HP (heal_at_center itself no-ops when full);
    # runs before the Route 1 crossings so the errand never starts hurt.
    if _party_full(reader):
        h.done_task("p2_heal")
    else:
        h.phase("p2_heal", "Healing up at the Viridian Pokemon Center")
        if not _travel(b, reader, nav, ow, policy, VIRIDIAN,
                       narrate=narrator("p2_heal")):
            h.phase("p2_heal", "Couldn't reach Viridian to heal - needs a look")
            return False
        if not svc.heal_at_center(VIRIDIAN) or not _party_full(reader):
            h.phase("p2_heal", "Party not full after the heal - needs a look")
            return False
        if nav.current_map() != VIRIDIAN:     # still inside the Center
            nav.leave_building()
            ow.wait_control(12)
        h.done_task("p2_heal")

    # --- Step 3: Oak's Parcel at the Mart ---
    if have_parcel(reader) or parcel_delivered(reader):
        h.done_task("p2_parcel")
    else:
        h.phase("p2_parcel", "Picking up Oak's Parcel at the Viridian Mart")
        if not _travel(b, reader, nav, ow, policy, VIRIDIAN,
                       narrate=narrator("p2_parcel")) \
                or not _get_parcel(b, reader, nav, ow,
                                   narrate=narrator("p2_parcel")):
            h.phase("p2_parcel", "No parcel after the Mart scene - needs a look")
            return False
        h.phase("p2_parcel", "Oak's Parcel in the bag!")
        h.done_task("p2_parcel")

    # --- Step 4: back south to Pallet, deliver to Oak ---
    if parcel_delivered(reader):
        h.done_task("p2_deliver")
    else:
        h.phase("p2_deliver", "Taking the parcel back to Prof. Oak")
        if nav.current_map() != OAKLAB:       # a lab resume skips the trek
            if not _travel(b, reader, nav, ow, policy, PALLET,
                           narrate=narrator("p2_deliver")):
                h.phase("p2_deliver", "Couldn't reach Pallet - needs a look")
                return False
            if not _enter_lab(nav, ow):
                h.phase("p2_deliver", "Couldn't enter Oak's lab - needs a look")
                return False
        if not _deliver_to_oak(b, reader, nav, ow,
                               narrate=narrator("p2_deliver")):
            h.phase("p2_deliver", "Oak's hand-off didn't finish - needs a look")
            return False
        h.phase("p2_deliver", "Pokedex + 5 Poke Balls received!")
        h.done_task("p2_deliver")

    # --- Step 5: Town Map from Daisy ---
    if have_town_map(reader):
        h.done_task("p2_townmap")
    else:
        h.phase("p2_townmap", "Visiting Daisy next door for the Town Map")
        # _travel also walks us OUT of the lab when step 4 just ran.
        if not _travel(b, reader, nav, ow, policy, PALLET,
                       narrate=narrator("p2_townmap")) \
                or not _get_town_map(reader, nav, ow,
                                     narrate=narrator("p2_townmap")):
            h.phase("p2_townmap", "No Town Map from any Pallet NPC - needs a look")
            return False
        h.phase("p2_townmap", "Town Map received!")
        h.done_task("p2_townmap")

    # --- Step 6: north again - Teachy TV from the old man ---
    if have_teachy_tv(reader):
        h.done_task("p2_teachytv")
    else:
        h.phase("p2_teachytv", "North to Viridian - the old man on the path")
        if not _travel(b, reader, nav, ow, policy, VIRIDIAN,
                       narrate=narrator("p2_teachytv")) \
                or not _get_teachy_tv(reader, nav, ow,
                                      narrate=narrator("p2_teachytv")):
            h.phase("p2_teachytv", "No Teachy TV from the north path - needs a look")
            return False
        h.phase("p2_teachytv", "Teachy TV received!")
        h.done_task("p2_teachytv")

    # --- Step 7: the Route 2 west approach ---
    # With the old man's demo done the north path is open; the north-west
    # path out of Viridian is an edge connection onto Route 2 (G7-proven).
    if nav.current_map() == ROUTE2:
        h.done_task("p2_route2")
        return True
    h.phase("p2_route2", "Taking the north-west path toward Route 2")
    if not _travel(b, reader, nav, ow, policy, ROUTE2,
                   narrate=narrator("p2_route2")):
        h.phase("p2_route2", "Couldn't cross into Route 2 - needs a look")
        return False
    h.phase("p2_route2", "Route 2 - the forest approach. Part 2 complete!")
    h.done_task("p2_route2")
    return True
