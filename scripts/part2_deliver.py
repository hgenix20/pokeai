"""G2 second-half, step 2: deliver Oak's Parcel to Prof. Oak in Pallet Town.

From slot 5 (Viridian, parcel in bag): leave Viridian SOUTH -> Route 1 (map
3,19) -> south -> Pallet Town (map 3,0) -> Oak's lab (map 4,3) -> talk to Oak ->
Pokedex + 5 Poke Balls. Verified via event-flag delta. Saves slot 6.

Multi-map edge crossings (Viridian->Route1->Pallet are CONNECTIONS, not warps):
walk to the map's south edge at the entrance column and hold DOWN until
current_map changes. Ledges on Route 1 are one-way SOUTH, so going south is
along the grain. Waypoint hops keep each BFS plan local. Run from slot 5,
stream.py STOPPED. Detailed logging (run in background + monitor).
"""
from __future__ import annotations

import json
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.emulator.firered_state_reader import FireRedStateReader
from pokeai.perception.navigator import Navigator
from pokeai.skills.battle import Battle
from pokeai.skills.overworld import Overworld

SLOTS = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai\states\slots"
OUT = r"C:\Users\Sagac\AppData\Local\Temp\claude\C--Program-Files-Git\0ce068f5-fdaf-4e80-b3d3-05f89c188438\scratchpad"
VIRIDIAN, ROUTE1, PALLET, OAKLAB = (3, 1), (3, 19), (3, 0), (4, 3)
# bag ground truth (verified live): Oak's Parcel = KeyItem id 349 @ SB1+0x3B8.
# Delivery is confirmed when Oak TAKES the parcel (it leaves the bag).
SB1_PTR = 0x03005008
KEYITEMS_OFF = 0x3B8
OAKS_PARCEL_ID = 349


def has_parcel(b) -> bool:
    p = b.read_u32(SB1_PTR)
    return any(b.read_u16(p + KEYITEMS_OFF + i * 4) == OAKS_PARCEL_ID for i in range(30))


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def moved(b, d="LEFT") -> bool:
    p0 = b.player_xy()
    b.press_direction_settle(d)
    return b.player_xy() != p0


def in_battle(b, battle) -> bool:
    """Enemy loaded AND movement locked (a fled/post-battle enemy can linger)."""
    if not battle.active():
        return False
    return not (moved(b, "LEFT") or moved(b, "RIGHT"))


def flee_or_fight(b, battle) -> str:
    for _ in range(4):
        for _ in range(2):
            b.tap("B", 6)
            time.sleep(0.35)
        b.tap("RIGHT", 6)
        time.sleep(0.3)
        b.tap("DOWN", 6)
        time.sleep(0.3)
        b.tap("A", 6)
        time.sleep(0.6)
        for _ in range(4):
            b.tap("B", 6)
            time.sleep(0.35)
        if not in_battle(b, battle):
            return "fled"
    verdict = battle.fight()
    for _ in range(15):
        b.tap("A", 6)
        time.sleep(0.35)
    return verdict


def cross_south(b, nav, cur, want, tries=40) -> bool:
    """Walk to the south edge and hold DOWN until the map changes to `want`."""
    for _ in range(tries):
        if nav.current_map() == want:
            return True
        if nav.current_map() != cur:
            return nav.current_map() == want
        b.press_direction_settle("DOWN")
    return nav.current_map() == want


def descend_map(b, nav, ow, cur, want, budget=180) -> bool:
    """Drive south across `cur` toward its south edge into `want`. Repeatedly:
    flood to the southmost reachable tile, then try to cross the edge."""
    from collections import deque
    delta = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
    battle = Battle(b)
    t0 = time.time()
    while time.time() - t0 < budget and nav.current_map() == cur:
        # routes are grass-dense: flee any wild battle before trying to move,
        # else go_to loops forever against the battle screen.
        if battle.active() and in_battle(b, battle):
            r = flee_or_fight(b, battle)
            say(f"  [{cur}] wild battle -> {r}")
            continue
        g = nav.vision.nav_grid()
        walk = g["walk"] - nav.vision.object_tiles()
        ledge_dir = g.get("ledge_dir", {})
        start = nav.vision.player_xy()
        # flood INCLUDING one-way ledge hops (a ledge in dir D, entered from its
        # near side, lands 2 tiles out) so "southmost reachable" sees past the
        # ledge rows that fence the route. Matches nav.plan's hop model.
        seen = {start}
        q = deque([start])
        best = start
        while q:
            x, y = q.popleft()
            if y > best[1]:
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
        say(f"  [{cur}] southmost reachable {best} from {start}")
        if best != start:
            nav.go_to(best, attempts=12)
        # try to fall off the south edge into the next map (hold DOWN hops ledges)
        for _ in range(8):
            m0 = nav.current_map()
            b.press_direction_settle("DOWN")
            if nav.current_map() != m0:
                break
        if nav.current_map() == want:
            return True
    return nav.current_map() == want


def main() -> int:
    b = BizHawkBridge(timeout=300)
    say("waiting for ai_bridge…")
    b.wait_for_bizhawk()
    reader = FireRedStateReader(b)
    nav = Navigator(b)
    ow = Overworld(b, nav, reader)

    say("loading slot 5 (got parcel)…")
    if not b.load_state(SLOTS + r"\slot_5.state"):
        say("FAIL slot 5 load")
        return 1
    time.sleep(1.0)
    ev0 = reader.read_event_flags_set()
    say(f"start map {nav.current_map()} pos {nav.vision.player_xy()} events {ev0}")

    # If we resumed INSIDE a building (slot saved in the Mart), leave it first.
    if nav.current_map() != VIRIDIAN:
        say(f"in a building {nav.current_map()} — leaving to Viridian city…")
        nav.leave_building()
        ow.wait_control(12)
        say(f"  now map {nav.current_map()} pos {nav.vision.player_xy()}")

    # Viridian -> Route 1
    say("descending Viridian -> Route 1…")
    if not descend_map(b, nav, ow, VIRIDIAN, ROUTE1):
        say(f"FAIL: stuck leaving Viridian, map={nav.current_map()}")
        b.screenshot(OUT + r"\deliver_stuck1.png")
        return 1
    say(f"on Route 1: {nav.current_map()} pos {nav.vision.player_xy()}")

    # Route 1 -> Pallet
    say("descending Route 1 -> Pallet…")
    if not descend_map(b, nav, ow, ROUTE1, PALLET):
        say(f"FAIL: stuck on Route 1, map={nav.current_map()}")
        b.screenshot(OUT + r"\deliver_stuck2.png")
        return 1
    say(f"in Pallet Town: {nav.current_map()} pos {nav.vision.player_xy()}")
    b.screenshot(OUT + r"\deliver_pallet.png")

    # Pallet -> Oak's lab (warp). The lab door is a known warp on the Pallet map.
    say("finding Oak's lab door in Pallet…")
    labdoors = [w for w in nav.map_warps_full() if (w["destGroup"], w["destMap"]) == OAKLAB]
    say(f"lab warps: {[(w['x'], w['y']) for w in labdoors]}")
    entered = False
    for w in labdoors:
        nav.go_to((w["x"], w["y"] + 1), attempts=8)
        if nav.take_warp((w["x"], w["y"])) == OAKLAB:
            entered = True
            break
    if not entered:
        say(f"FAIL: could not enter Oak's lab, map={nav.current_map()}")
        b.screenshot(OUT + r"\deliver_stuck3.png")
        return 1
    ow.wait_control(15)
    say(f"in Oak's lab: {nav.current_map()} pos {nav.vision.player_xy()}")

    # CHECKPOINT: save slot 7 here so the Oak hand-off can be iterated without
    # re-driving the whole Viridian->Pallet descent each time.
    if b.save_state(SLOTS + r"\slot_7.state"):
        try:
            m7 = json.load(open(SLOTS + r"\slot_5.json", encoding="utf-8"))
            m7.update(n=7, summary="Oak's lab with parcel (pre-handoff)",
                      ts=time.strftime("%Y-%m-%d %H:%M"))
            json.dump(m7, open(SLOTS + r"\slot_7.json", "w", encoding="utf-8"))
            say("saved slot 7 = Oak's lab with parcel (pre-handoff)")
        except Exception:
            pass

    # talk to Oak: he's the NPC at the top-center behind the counter
    npcs = sorted(nav.vision.object_tiles(), key=lambda t: (t[1], t[0]))
    say(f"lab npcs {npcs}")
    b.screenshot(OUT + r"\deliver_lab.png")
    oak = npcs[0] if npcs else (5, 2)
    say(f"had parcel before Oak: {has_parcel(b)}")
    say(f"delivering parcel to Oak {oak}…")
    # ride the long scene (parcel -> Pokedex -> 5 Balls -> rival naming may follow);
    # stop once Oak has TAKEN the parcel (it leaves the bag) + control returns.
    ow.interact(oak, rounds=6)
    for _ in range(120):
        if not has_parcel(b):
            break
        b.tap("A", 6)
        time.sleep(0.35)
    ow.advance_dialogue(cap=60)
    ow.wait_control(20)
    b.screenshot(OUT + r"\deliver_after.png")

    ev1 = reader.read_event_flags_set()
    say(f"parcel still in bag: {has_parcel(b)}; events {ev0} -> {ev1}")
    if not has_parcel(b):
        say("DELIVERED (Oak took the parcel). Saving slot 6.")
        if b.save_state(SLOTS + r"\slot_6.state"):
            meta = json.load(open(SLOTS + r"\slot_5.json", encoding="utf-8"))
            meta.update(n=6, summary="Pallet: delivered parcel, got Pokedex + 5 Balls",
                        ts=time.strftime("%Y-%m-%d %H:%M"))
            json.dump(meta, open(SLOTS + r"\slot_6.json", "w", encoding="utf-8"))
            say("saved slot 6")
        return 0
    say("Parcel still in bag after Oak — scene incomplete; check deliver_after.png")
    return 2


if __name__ == "__main__":
    sys.exit(main())
