"""G2 probe: receive the Route 1 free Potion and DISCOVER the bag layout from
the SaveBlock1 delta (offsets are candidates from pokefirered; this verifies
them empirically). Prints every changed u16 in SB1[0x000:0x700] with a
security-key interpretation so the items pocket + quantity XOR are proven.

Run with stream.py STOPPED. Starts from slot 3 (Route 1 south edge).
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
from pokeai.skills.battle import Battle
from pokeai.skills.overworld import Overworld

SLOTS = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai\states\slots"
SB1_PTR, SB2_PTR = 0x03005008, 0x0300500C
DUMP_LEN = 0x700


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def sb1_dump(b) -> bytes:
    out = bytearray()
    for off in range(0, DUMP_LEN, 0x100):
        p = b.read_u32(SB1_PTR)          # deref fresh: SaveBlocks relocate
        out += bytes(b.read_range(p + off, p + off + 0x100))
    return bytes(out)


def main() -> int:
    b = BizHawkBridge(timeout=180)
    say("waiting for ai_bridge…")
    b.wait_for_bizhawk()
    reader = FireRedStateReader(b)
    nav = Navigator(b)
    ow = Overworld(b, nav, reader)
    battle = Battle(b)

    say("loading slot 3…")
    if not b.load_state(SLOTS + r"\slot_3.state"):
        say("FAIL: slot load")
        return 1
    time.sleep(1.0)
    say(f"map {nav.current_map()} pos {b.player_xy()} money {reader.read_money()}")

    key16 = b.read_u32(b.read_u32(SB2_PTR) + 0xF20) & 0xFFFF
    say(f"security key16 = {key16:#06x}")

    before = sb1_dump(b)

    # nearest NPCs, closest first; talk until the bag changes
    objs = sorted(nav.vision.object_tiles(), key=lambda t: abs(t[0] - b.player_xy()[0])
                  + abs(t[1] - b.player_xy()[1]))
    say(f"npc tiles: {objs[:4]}")
    changed = []
    for target in objs[:3]:
        say(f"interacting with npc at {target}…")
        try:
            ow.interact(target)
        except Exception as e:
            say(f"  interact error: {type(e).__name__}: {e}")
        ow.wait_control(15)
        if battle.active():
            say("  wild battle interrupted — fighting it out")
            battle.fight()
            for _ in range(15):
                b.tap("A", 6)
                time.sleep(0.4)
        after = sb1_dump(b)
        changed = [(i, int.from_bytes(before[i:i + 2], "little"),
                    int.from_bytes(after[i:i + 2], "little"))
                   for i in range(0, DUMP_LEN, 2)
                   if before[i:i + 2] != after[i:i + 2]]
        if changed:
            break
        say("  no SB1 delta from that npc; trying next")

    if not changed:
        say("FAIL: no bag delta found")
        return 1
    say(f"{len(changed)} changed u16(s):")
    for off, was, now in changed[:40]:
        say(f"  SB1+{off:#05x}: {was:#06x} -> {now:#06x}"
            f"   (as qty^key: {was ^ key16} -> {now ^ key16})")
    say("interpretation: an items-pocket slot is [u16 itemId][u16 qty^key16];"
        " expect itemId 13 (POTION) with qty 0->1 or 1->2")
    say(f"money now {reader.read_money()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
