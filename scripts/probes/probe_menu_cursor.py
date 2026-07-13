"""Find the START-menu cursor address by EWRAM diff.

Run with the START menu OPEN and the cursor on a KNOWN entry. The script
dumps EWRAM, presses UP/DOWN to move the cursor to other known entries,
re-dumps, and intersects "byte that equaled k1 then k2 then k3" candidates.
Menu order with the dex: 0 POKEDEX 1 POKEMON 2 BAG 3 CLAUDE 4 SAVE
5 OPTION 6 EXIT (wraps both ways).
"""
from __future__ import annotations

import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

from pokeai.emulator.bizhawk_bridge import BizHawkBridge

EWRAM = 0x02000000
SIZE = 0x40000
CHUNK = 0x8000


def dump(b) -> bytes:
    out = bytearray()
    for off in range(0, SIZE, CHUNK):
        out += bytes(b.read_range(EWRAM + off, EWRAM + off + CHUNK))
    return bytes(out)


def main() -> int:
    b = BizHawkBridge(timeout=30)
    b.wait_for_bizhawk()

    # sequence of cursor positions: start EXIT(6) -> UP OPTION(5) -> UP SAVE(4)
    say = lambda m: print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)
    say("dump 1 (cursor should be on EXIT=6)…")
    d1 = dump(b)
    b.press_button_held("UP", 5)
    time.sleep(0.6)
    say("dump 2 (cursor OPTION=5)…")
    d2 = dump(b)
    b.press_button_held("UP", 5)
    time.sleep(0.6)
    say("dump 3 (cursor SAVE=4)…")
    d3 = dump(b)

    cands = [i for i in range(SIZE)
             if d1[i] == 6 and d2[i] == 5 and d3[i] == 4]
    say(f"candidates: {len(cands)}")
    for i in cands[:20]:
        say(f"  0x{EWRAM + i:08X}")

    if not cands:
        return 1
    # verify: move DOWN twice (SAVE->OPTION->EXIT) and re-check first cands
    b.press_button_held("DOWN", 5)
    time.sleep(0.6)
    b.press_button_held("DOWN", 5)
    time.sleep(0.6)
    say("verify (cursor back on EXIT=6):")
    for i in cands[:20]:
        v = b.read_range(EWRAM + i, EWRAM + i + 1)[0]
        say(f"  0x{EWRAM + i:08X} = {v} {'OK' if v == 6 else 'no'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
