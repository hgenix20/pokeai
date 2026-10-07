"""G2 acceptance (first-half): from Viridian south (slot 4), heal at the
Pokemon Center (RAM-verify party full) and pick up Oak's Parcel at the Mart
(RAM-verify an item entered the bag). Saves slot 5 = "Viridian, healed +
parcel" on success. Run with stream.py STOPPED.
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
from pokeai.skills.overworld import Overworld
from pokeai.skills.services import MARTS, Services

SLOTS = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai\states\slots"
SB1_PTR, SB2_PTR = 0x03005008, 0x0300500C
# items pocket: discovered empirically 2026-07-03 to start near SB1+0x310
# ([u16 itemId][u16 qty^key16]); count decoded qty>0 slots as a bag-size proxy.
ITEMS_OFF, ITEMS_SLOTS = 0x310, 30


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def bag_item_count(b) -> int:
    key16 = b.read_u32(b.read_u32(SB2_PTR) + 0xF20) & 0xFFFF
    p = b.read_u32(SB1_PTR)
    raw = bytes(b.read_range(p + ITEMS_OFF, p + ITEMS_OFF + ITEMS_SLOTS * 4))
    n = 0
    for i in range(0, len(raw), 4):
        item = int.from_bytes(raw[i:i + 2], "little")
        qty = int.from_bytes(raw[i + 2:i + 4], "little") ^ key16
        if item != 0 and 0 < qty < 999:
            n += 1
    return n


def main() -> int:
    b = BizHawkBridge(timeout=180)
    b.wait_for_bizhawk()
    reader = FireRedStateReader(b)
    nav = Navigator(b)
    ow = Overworld(b, nav, reader)
    svc = Services(b, nav, ow, reader)

    if not b.load_state(SLOTS + r"\slot_4.state"):
        say("FAIL slot load")
        return 1
    time.sleep(1.0)
    city = nav.current_map()
    s0 = reader.read()
    say(f"start {city} HP {s0.party_total_hp}/{s0.party_total_max_hp} bag {bag_item_count(b)}")

    # --- HEAL ---
    say("routing to Pokemon Center to heal…")
    healed = svc.heal_at_center(city)
    s1 = reader.read()
    say(f"heal -> {healed}; HP {s1.party_total_hp}/{s1.party_total_max_hp} "
        f"map {nav.current_map()}")
    if not (healed and s1.party_total_hp == s1.party_total_max_hp):
        say("FAIL: party not full after heal")
        return 1

    # leave the Center back to the city
    say("leaving the Center…")
    nav.leave_building()
    ow.wait_control(15)
    say(f"back outside: map {nav.current_map()} pos {nav.vision.player_xy()}")

    # --- OAK'S PARCEL (Mart) ---
    bag_before = bag_item_count(b)
    info = MARTS[city]
    say(f"routing to Mart door {info['door']} for Oak's Parcel…")
    nav.go_to((info["door"][0], info["door"][1] + 1))
    if nav.take_warp(info["door"]) != info["map"]:
        b.press_button_held("UP", 32)
        time.sleep(1.0)
    if nav.current_map() != info["map"]:
        say(f"FAIL: not in Mart (map {nav.current_map()})")
        return 1
    ow.wait_control(15)
    say(f"in Mart; talking to clerk {info['clerk']}…")
    ow.interact(info["clerk"], rounds=4)
    ow.advance_dialogue(cap=60)
    ow.wait_control(15)
    bag_after = bag_item_count(b)
    say(f"bag {bag_before} -> {bag_after}")
    if bag_after <= bag_before:
        say("NOTE: bag count unchanged — parcel scene may need cutscene ride;"
            " reporting partial (heal verified).")
        return 2

    say("PARCEL RECEIVED — saving slot 5")
    if b.save_state(SLOTS + r"\slot_5.state"):
        meta = json.load(open(SLOTS + r"\slot_4.json", encoding="utf-8"))
        meta.update(n=5, summary="Viridian: healed + Oak's Parcel",
                    ts=time.strftime("%Y-%m-%d %H:%M"))
        json.dump(meta, open(SLOTS + r"\slot_5.json", "w", encoding="utf-8"))
        say("saved slot 5")
    return 0


if __name__ == "__main__":
    sys.exit(main())
