"""Confirm a name on the FireRed keyboard: press START (moves cursor to OK) then
A (confirms) back-to-back with only a tiny gap — the OK highlight lapses if you
wait, so NO screenshot in between (that delay was why it kept reverting). Presses
START a couple times (lag can drop one), then A once, then screenshots the result.

Safe-ish: if START never registers, the cursor is still on a letter and the A
would add one char — check the screenshot after and delete with B if so.
"""
from __future__ import annotations

import time

from pokeai.emulator.bizhawk_bridge import BizHawkBridge

OUT = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai\states\bizhawk\confirm.png"


def main() -> int:
    b = BizHawkBridge(timeout=30)
    print("waiting for ai_bridge.lua…", flush=True)
    b.wait_for_bizhawk()
    print("ping:", b.ping())
    # a couple of STARTs to walk onto OK (lag may drop one), short gaps
    for _ in range(2):
        b.tap("START", 6)
        time.sleep(0.12)
    # then confirm with A immediately, before the OK highlight lapses
    b.tap("A", 6)
    time.sleep(0.4)
    b.screenshot(OUT)
    print("screenshot:", OUT)
    b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
