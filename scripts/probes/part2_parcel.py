"""G2 second-half: get Oak's Parcel at the Viridian Poke Mart (map 5,3), then
report (delivery to Oak is the next step). WAYPOINT navigation through the open
plaza avoids the cross-city go_to hang (a single BFS over a huge map can spin
the blacklist loop). Verifies the parcel via the event-flag count delta.

Detailed logging to stdout (run in background + monitor). From slot 4.
"""
from __future__ import annotations

import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.emulator.firered_state_reader import FireRedStateReader
from pokeai.perception.navigator import Navigator
from pokeai.skills.overworld import Overworld

SLOTS = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai\states\slots"
OUT = r"C:\Users\Sagac\AppData\Local\Temp\claude\C--Program-Files-Git\0ce068f5-fdaf-4e80-b3d3-05f89c188438\scratchpad"
# Viridian plaza waypoints from the south entrance to the Mart door (open space,
# short hops so the pather never plans across the whole 48x40 map at once).
MART_ROUTE = [(24, 32), (36, 32), (36, 20)]
MART_DOOR = (36, 19)
MART_MAP = (5, 3)
# Bag layout (FRLG BPRE, verified live 2026-07-03): SaveBlock1 pockets start at
# +0x310 (Items), Key Items at +0x3B8 (each entry [u16 id][u16 qty^securityKey16]).
# Oak's Parcel = item id 349 (0x15D). The parcel-receipt sets no flag in our
# counted event range, so the BAG is the ground-truth check, not event flags.
SB1_PTR, SB2_PTR = 0x03005008, 0x0300500C
KEYITEMS_OFF = 0x3B8
OAKS_PARCEL_ID = 349


def has_parcel(b) -> bool:
    p = b.read_u32(SB1_PTR)
    for i in range(30):  # scan the key-items pocket
        if b.read_u16(p + KEYITEMS_OFF + i * 4) == OAKS_PARCEL_ID:
            return True
    return False


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def hop(nav, ow, wp) -> bool:
    say(f"  -> waypoint {wp} from {nav.vision.player_xy()}")
    ok = nav.go_to(wp, attempts=8)
    say(f"     {'OK' if ok else 'STOP'} at {nav.vision.player_xy()}")
    return ok


def main() -> int:
    b = BizHawkBridge(timeout=300)
    say("waiting for ai_bridge…")
    b.wait_for_bizhawk()
    reader = FireRedStateReader(b)
    nav = Navigator(b)
    ow = Overworld(b, nav, reader)

    say("loading slot 4…")
    if not b.load_state(SLOTS + r"\slot_4.state"):
        say("FAIL slot load")
        return 1
    time.sleep(1.0)
    ev0 = reader.read_event_flags_set()
    say(f"start map {nav.current_map()} pos {nav.vision.player_xy()} events {ev0}")

    say("waypoint route to the Mart door…")
    for wp in MART_ROUTE:
        hop(nav, ow, wp)
    # enter the Mart: step up into the door
    say("entering the Mart (UP into door)…")
    city = nav.current_map()
    for _ in range(3):
        b.press_button_held("UP", 32)
        time.sleep(1.0)
        if nav.current_map() != city:
            break
    if nav.current_map() != MART_MAP:
        say(f"FAIL: not in Mart, map={nav.current_map()} pos={nav.vision.player_xy()}")
        b.screenshot(OUT + r"\parcel_fail.png")
        return 1
    ow.wait_control(12)

    px, py = nav.vision.player_xy()
    say(f"in Mart pos {(px, py)}")
    b.screenshot(OUT + r"\mart_before.png")

    # The parcel scene AUTO-FIRES on entry (the clerk calls you over); just ride
    # the dialogue to completion rather than navigating to an NPC through the
    # blocking text box. A-mash through the whole scene.
    say("riding the auto-triggered parcel scene…")
    for _ in range(50):
        if has_parcel(b):
            break
        b.tap("A", 6)
        time.sleep(0.35)
    # IMPORTANT: keep A-mashing to CLOSE the lingering "received OAK's PARCEL"
    # box, then confirm control — else the slot is saved with a dialogue up and
    # the player can't move (the delivery then can't leave the Mart).
    for _ in range(12):
        b.tap("A", 6)
        time.sleep(0.3)
    ow.wait_control(15)
    b.screenshot(OUT + r"\mart_after.png")

    if has_parcel(b):
        say("OAK'S PARCEL IN BAG (KeyItem 349). Saving slot 5.")
        if b.save_state(SLOTS + r"\slot_5.state"):
            import json
            meta = json.load(open(SLOTS + r"\slot_4.json", encoding="utf-8"))
            meta.update(n=5, summary="Viridian: got Oak's Parcel (bag KeyItem 349)",
                        ts=time.strftime("%Y-%m-%d %H:%M"))
            json.dump(meta, open(SLOTS + r"\slot_5.json", "w", encoding="utf-8"))
            say("saved slot 5 = got Oak's Parcel")
        return 0
    say(f"NO parcel in bag (events {ev0}->{reader.read_event_flags_set()}); check shots.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
