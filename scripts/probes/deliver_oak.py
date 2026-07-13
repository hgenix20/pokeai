"""Finish the Oak's Parcel hand-off from slot 7 (in Oak's lab, parcel in bag).

In FRLG Prof. Oak stands at the TOP-CENTER of his lab (off the bottom-centered
camera when you enter). Delivery fires when you approach/talk to him. This walks
to the top-center, then tries the top NPCs (Oak first) + a straight UP approach,
riding the long parcel -> Pokedex -> 5 Balls scene until the parcel LEAVES the
bag. Iterates cheaply from slot 7 (no re-driving the descent). stream.py STOPPED.
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

SLOTS = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai\states\slots"
OUT = r"C:\Users\Sagac\AppData\Local\Temp\claude\C--Program-Files-Git\0ce068f5-fdaf-4e80-b3d3-05f89c188438\scratchpad"
SB1P = 0x03005008


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def has_parcel(b) -> bool:
    p = b.read_u32(SB1P)
    return any(b.read_u16(p + 0x3B8 + i * 4) == 349 for i in range(30))


def ride_scene(b, ow, cap=260) -> bool:
    """A-mash the WHOLE delivery scene to completion. The parcel leaves the bag
    partway through (Oak takes it), but the Pokedex + 5 Poke Balls are given
    AFTER, so keep going until control returns (no dialogue) with the parcel
    gone. Returns True once fully done."""
    gone_since = None
    for i in range(cap):
        if not has_parcel(b):
            if gone_since is None:
                gone_since = i
            # after the parcel is taken, ride the rest, then confirm control
            if not ow.dialogue_open():
                if ow.has_control():
                    return True
        b.tap("A", 6)
        time.sleep(0.3)
    return not has_parcel(b)


def main() -> int:
    b = BizHawkBridge(timeout=120)
    say("waiting for ai_bridge…")
    b.wait_for_bizhawk()
    reader = FireRedStateReader(b)
    nav = Navigator(b)
    ow = Overworld(b, nav, reader)

    if not b.load_state(SLOTS + r"\slot_7.state"):
        say("FAIL: slot 7 load")
        return 1
    time.sleep(1.2)
    say(f"in lab {nav.current_map()} pos {nav.vision.player_xy()} parcel {has_parcel(b)}")

    # walk to the top-center so Oak (and the counter) load, then look
    nav.go_to((6, 3), attempts=10)
    time.sleep(0.4)
    npcs = sorted(nav.vision.object_tiles(), key=lambda t: (t[1], t[0]))
    say(f"after moving up: pos {nav.vision.player_xy()} npcs {npcs}")
    b.screenshot(OUT + r"\oak_handoff_before.png")

    # 1) straight-up approach: walk up toward Oak; the parcel script often fires
    #    on approach. Ride any dialogue.
    for _ in range(5):
        if not has_parcel(b):
            break
        moved = b.press_direction_settle("UP")
        if ow.dialogue_open():
            say("dialogue opened on approach — riding scene")
            ride_scene(b, ow)
            break
        if not moved:
            break

    # 2) if still holding it, interact with each top NPC (Oak is top-center)
    if has_parcel(b):
        for cand in sorted(nav.vision.object_tiles(), key=lambda t: (t[1], t[0]))[:5]:
            if not has_parcel(b):
                break
            say(f"trying Oak candidate {cand}")
            try:
                ow.interact(cand, rounds=3)
            except Exception as e:
                say(f"  interact issue {type(e).__name__}")
            ride_scene(b, ow, cap=120)

    ow.wait_control(25)
    b.screenshot(OUT + r"\oak_handoff_after.png")
    # verify the Pokedex+balls scene actually completed: count Poke Balls (item 4)
    key16 = b.read_u16(b.read_u32(0x0300500C) + 0xF20 + 0)  # low 16 of security key
    key16 = b.read_u32(b.read_u32(0x0300500C) + 0xF20) & 0xFFFF
    p = b.read_u32(SB1P)
    balls = 0
    for off in range(0x310, 0x600, 4):
        if b.read_u16(p + off) == 4:
            balls = b.read_u16(p + off + 2) ^ key16
            break
    say(f"parcel in bag: {has_parcel(b)}  Poke Balls: {balls}")
    delivered = (not has_parcel(b)) and balls >= 5
    say(f"DELIVERED={delivered}")
    if delivered:
        if b.save_state(SLOTS + r"\slot_6.state"):
            m = json.load(open(SLOTS + r"\slot_7.json", encoding="utf-8"))
            m.update(n=6, summary="Pallet: delivered parcel to Oak (Pokedex + 5 Balls)",
                     ts=time.strftime("%Y-%m-%d %H:%M"))
            json.dump(m, open(SLOTS + r"\slot_6.json", "w", encoding="utf-8"))
            say("saved slot 6 = parcel delivered")
        return 0
    say("not delivered — check oak_handoff_after.png")
    return 2


if __name__ == "__main__":
    sys.exit(main())
