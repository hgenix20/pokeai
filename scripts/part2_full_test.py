"""G3 ACCEPTANCE — Part 2 END TO END from slot 4, every stage RAM-gated.

Chain (slot 4 = Viridian south entrance, pre-parcel):
  A  heal at the Viridian Center            -> party HP full (RAM)
  B  Mart: receive Oak's Parcel             -> KeyItem 349 in bag; save slot 5
  C  descend Viridian -> Route 1 -> Pallet  -> map ids
  D  deliver to Oak                         -> parcel gone + balls == 5 +
                                               FLAG_SYS_POKEDEX_GET (0x829) SET;
                                               save slot 7 pre-handoff checkpoint
  E  Daisy (rival's house)                  -> Town Map key item appears (id
                                               discovered + logged)
  F  travel north back to Viridian          -> map id
  G  old man on the north path              -> Teachy TV key item appears
  H  save slot 6 = "Part 2 COMPLETE"        -> slots regenerated

Discovery is inline where tiles were never recorded (rival-house door, Daisy,
the old man): warps/NPCs are enumerated and the findings printed for the
record. stream.py STOPPED. Run in background and monitor (30-45 min).
"""
from __future__ import annotations

import json
import sys
import time
from collections import deque

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.emulator.firered_state_reader import (
    FireRedStateReader,
    ITEM_OAKS_PARCEL,
)
from pokeai.perception.navigator import Navigator
from pokeai.skills.battle import Battle
from pokeai.skills.overworld import Overworld
from pokeai.skills.services import Services

SLOTS = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai\states\slots"
OUT = r"C:\Users\Sagac\AppData\Local\Temp\claude\C--Program-Files-Git\166a5709-56c5-4d9e-b14e-311acd851a68\scratchpad"
VIRIDIAN, ROUTE1, PALLET, OAKLAB = (3, 1), (3, 19), (3, 0), (4, 3)
PLAYER_HOUSE_1F = (4, 0)
MART_ROUTE = [(24, 32), (36, 32), (36, 20)]
MART_MAP = (5, 3)
FLAG_SYS_POKEDEX_GET = 0x829


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def fail(b, msg, shot):
    say(f"FAIL: {msg}")
    try:
        b.screenshot(OUT + rf"\{shot}.png")
    except Exception:
        pass
    return 1


from pokeai.agents.field_brain import flee_or_fight, in_real_battle  # noqa: E402
from pokeai.skills.catch import Catch  # noqa: E402


def flood_extreme(nav, direction: str):
    """Furthest reachable tile toward a map edge, INCLUDING one-way ledge hops
    (southbound routes are fenced by ledges)."""
    delta = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
    g = nav.vision.nav_grid()
    walk = g["walk"] - nav.vision.object_tiles()
    ledge_dir = g.get("ledge_dir", {})
    start = nav.vision.player_xy()
    seen = {start}
    q = deque([start])
    best = start

    def better(t, cur):
        return t[1] < cur[1] if direction == "NORTH" else t[1] > cur[1]

    while q:
        x, y = q.popleft()
        if better((x, y), best):
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


def cross_map(b, nav, battle, reader, catch, cur, want, direction, budget=240) -> bool:
    """Walk across `cur` and over the edge connection into `want`."""
    push = "UP" if direction == "NORTH" else "DOWN"
    t0 = time.time()
    while time.time() - t0 < budget:
        m = nav.current_map()
        if m == want:
            return True
        if m[0] != 3:
            # still inside a building (a lingering box can hold movement and
            # fail leave_building): B-ride until movement returns, then exit
            say(f"  inside {m} - leaving before the crossing")
            if nav.leave_building() is None:
                for _ in range(10):
                    p0 = b.player_xy()
                    b.press_direction_settle("DOWN")
                    if b.player_xy() != p0:
                        break
                    b.tap("B", 5)
                    time.sleep(0.4)
            continue
        if m != cur:
            return m == want
        if reader.read().all_party_fainted:
            say("  BLACKOUT mid-journey")
            return False
        if battle.active() and in_real_battle(b, battle, catch):
            say(f"  [{cur}] wild battle -> {flee_or_fight(b, battle, catch)}")
            continue
        best = flood_extreme(nav, direction)
        if best:
            nav.go_to(best, attempts=12)
        for _ in range(8):
            m0 = nav.current_map()
            b.press_direction_settle(push)
            if nav.current_map() != m0:
                break
    return nav.current_map() == want


def key_items(r) -> dict:
    return dict(r.read_bag_pocket("key_items"))


def save_slot(b, n, base_json, summary):
    if b.save_state(SLOTS + rf"\slot_{n}.state"):
        meta = json.load(open(SLOTS + rf"\slot_{base_json}.json", encoding="utf-8"))
        meta.update(n=n, summary=summary, ts=time.strftime("%Y-%m-%d %H:%M"))
        json.dump(meta, open(SLOTS + rf"\slot_{n}.json", "w", encoding="utf-8"))
        say(f"saved slot {n} = {summary}")


def main() -> int:
    from_stage_d = "--from7" in sys.argv   # iterate D-G from the slot-7 checkpoint
    b = BizHawkBridge(timeout=300)
    say("waiting for ai_bridge…")
    b.wait_for_bizhawk()
    reader = FireRedStateReader(b)
    nav = Navigator(b)
    ow = Overworld(b, nav, reader)
    battle = Battle(b)
    catch = Catch(b, battle)
    svc = Services(b, nav, ow, reader)

    if from_stage_d:
        say("=== resume: load slot 7 (lab, parcel in hand) and run D-G ===")
        if not b.load_state(SLOTS + r"\slot_7.state"):
            return fail(b, "slot 7 load", "p2_load7")
        time.sleep(1.2)
        return stages_d_to_h(b, reader, nav, ow, battle, catch, svc)

    say("=== stage 0: load slot 4 (Viridian south, pre-parcel) ===")
    if not b.load_state(SLOTS + r"\slot_4.state"):
        return fail(b, "slot 4 load", "p2_load")
    time.sleep(1.2)
    if nav.current_map() != VIRIDIAN:
        return fail(b, f"not in Viridian: {nav.current_map()}", "p2_start")
    s = reader.read()
    say(f"map {nav.current_map()} pos {nav.vision.player_xy()} money {s.money} "
        f"HP {s.party_total_hp}/{s.party_total_max_hp} "
        f"dexflag {reader.read_flag(FLAG_SYS_POKEDEX_GET)}")

    say("=== stage A: heal at the Viridian Center ===")
    if not svc.heal_at_center(VIRIDIAN):
        return fail(b, "heal_at_center", "p2_heal")
    s = reader.read()
    if s.party_total_hp != s.party_total_max_hp:
        return fail(b, "party not full after heal", "p2_heal2")
    say(f"healed: {s.party_total_hp}/{s.party_total_max_hp}")
    if nav.current_map() != VIRIDIAN:
        nav.leave_building()
        ow.wait_control(12)

    say("=== stage B: Oak's Parcel at the Mart ===")
    for wp in MART_ROUTE:
        nav.go_to(wp, attempts=8)
    city = nav.current_map()
    for _ in range(3):
        b.press_button_held("UP", 32); time.sleep(1.0)
        if nav.current_map() != city:
            break
    if nav.current_map() != MART_MAP:
        return fail(b, f"not in Mart: {nav.current_map()}", "p2_mart")
    ow.wait_control(12)
    for _ in range(50):
        if reader.count_item(ITEM_OAKS_PARCEL):
            break
        b.tap("A", 6); time.sleep(0.35)
    for _ in range(12):
        b.tap("A", 6); time.sleep(0.3)
    ow.wait_control(15)
    if not reader.count_item(ITEM_OAKS_PARCEL):
        return fail(b, "no parcel after Mart scene", "p2_parcel")
    say("parcel in bag (KeyItem 349)")
    save_slot(b, 5, 4, "Viridian: healed + Oak's Parcel")
    nav.leave_building()
    ow.wait_control(12)

    say("=== stage C: descend Viridian -> Route 1 -> Pallet ===")
    if not cross_map(b, nav, battle, reader, catch, VIRIDIAN, ROUTE1, "SOUTH"):
        return fail(b, f"stuck leaving Viridian: {nav.current_map()}", "p2_desc1")
    say(f"on Route 1 at {nav.vision.player_xy()}")
    if not cross_map(b, nav, battle, reader, catch, ROUTE1, PALLET, "SOUTH"):
        return fail(b, f"stuck on Route 1: {nav.current_map()}", "p2_desc2")
    say(f"in Pallet at {nav.vision.player_xy()}")

    labdoors = [w for w in nav.map_warps_full()
                if (w["destGroup"], w["destMap"]) == OAKLAB]
    entered = False
    for w in labdoors:
        nav.go_to((w["x"], w["y"] + 1), attempts=8)
        if nav.take_warp((w["x"], w["y"])) == OAKLAB:
            entered = True
            break
    if not entered:
        return fail(b, f"could not enter the lab: {nav.current_map()}", "p2_lab")
    ow.wait_control(15)
    save_slot(b, 7, 5, "Oak's lab with parcel (pre-handoff)")
    return stages_d_to_h(b, reader, nav, ow, battle, catch, svc)


def stages_d_to_h(b, reader, nav, ow, battle, catch, svc) -> int:
    say("=== stage D: deliver the parcel to Oak ===")

    # Oak stands at the lab TOP-CENTER, off-camera from the entrance: walk to
    # (6,3) first so he loads, then approach UP - the parcel scene auto-fires
    # (deliver_oak.py's proven mechanic). Ride the WHOLE scene: the parcel
    # leaves mid-scene but the Pokedex + 5 Balls come after.
    def ride_scene(cap=260) -> bool:
        for _ in range(cap):
            if not reader.count_item(ITEM_OAKS_PARCEL):
                if not ow.dialogue_open() and ow.has_control():
                    return True
            b.tap("A", 6); time.sleep(0.3)
        return not reader.count_item(ITEM_OAKS_PARCEL)

    nav.go_to((6, 3), attempts=10)
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
    dex = reader.read_flag(FLAG_SYS_POKEDEX_GET)
    say(f"parcel gone: {not reader.count_item(ITEM_OAKS_PARCEL)}  "
        f"balls {balls}  dexflag {dex}")
    if reader.count_item(ITEM_OAKS_PARCEL):
        return fail(b, "Oak did not take the parcel", "p2_oak")
    if balls < 5:
        return fail(b, f"expected 5 balls, have {balls}", "p2_balls")
    if not dex:
        return fail(b, "FLAG_SYS_POKEDEX_GET (0x829) not set", "p2_dex")

    say("=== stage E: Town Map from Daisy (rival's house) ===")
    nav.leave_building()
    ow.wait_control(12)
    ki0 = key_items(reader)
    rival_doors = [w for w in nav.map_warps_full()
                   if (w["destGroup"], w["destMap"]) not in (OAKLAB, PLAYER_HOUSE_1F)]
    say(f"rival-house candidate doors: "
        f"{[((w['x'], w['y']), (w['destGroup'], w['destMap'])) for w in rival_doors]}")
    got_map = False
    town_map_id = None
    for w in rival_doors:
        nav.go_to((w["x"], w["y"] + 1), attempts=8)
        dest = nav.take_warp((w["x"], w["y"]))
        if dest is None or nav.current_map() == PALLET:
            continue
        ow.wait_control(12)
        say(f"inside {nav.current_map()}; npcs {sorted(nav.vision.object_tiles())}")
        for npc in sorted(nav.vision.object_tiles()):
            ow.interact(npc, rounds=4)
            ow.advance_dialogue(cap=40)
            ow.wait_control(10)
            ki1 = key_items(reader)
            new = {k: v for k, v in ki1.items() if k not in ki0}
            if new:
                town_map_id = next(iter(new))
                say(f"TOWN MAP received: key item id {town_map_id} "
                    f"(door ({w['x']},{w['y']}) -> {nav.current_map()}, npc {npc})")
                got_map = True
                break
        nav.leave_building()
        ow.wait_control(12)
        if got_map:
            break
    if not got_map:
        return fail(b, "no Town Map from any Pallet NPC", "p2_daisy")

    say("=== stage F: north to Viridian ===")
    if not cross_map(b, nav, battle, reader, catch, PALLET, ROUTE1, "NORTH"):
        return fail(b, f"stuck leaving Pallet: {nav.current_map()}", "p2_north1")
    if not cross_map(b, nav, battle, reader, catch, ROUTE1, VIRIDIAN, "NORTH", budget=420):
        return fail(b, f"stuck on Route 1 northbound: {nav.current_map()}", "p2_north2")
    say(f"back in Viridian at {nav.vision.player_xy()}")

    say("=== stage G: Teachy TV from the old man (north path) ===")
    ki0 = key_items(reader)
    got_tv = False
    tv_id = None
    for attempt in range(3):
        px, py = nav.vision.player_xy()
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
            ki1 = key_items(reader)
            new = {k: v for k, v in ki1.items() if k not in ki0}
            if new:
                tv_id = next(iter(new))
                say(f"TEACHY TV received: key item id {tv_id} (npc {npc})")
                got_tv = True
                break
        if got_tv:
            break
        # walk further north up the path and rescan
        tgt = flood_extreme(nav, "NORTH")
        if tgt:
            nav.go_to((tgt[0], max(tgt[1], 4)), attempts=8)
    if not got_tv:
        return fail(b, "no Teachy TV from the north-path NPCs", "p2_tv")

    say("=== stage H: save Part 2 COMPLETE ===")
    save_slot(b, 6, 5, "Part 2 COMPLETE: Pokedex + 5 Balls + Town Map + Teachy TV")
    b.screenshot(OUT + r"\p2_done.png")
    say(f"PASS — dexflag set, balls {reader.ball_count()}, "
        f"town map id {town_map_id}, teachy tv id {tv_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
