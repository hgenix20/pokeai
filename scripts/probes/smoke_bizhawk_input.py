"""Verify BizHawk INPUT live: prove the bridge can actually move the player.

Reads are already covered by smoke_bizhawk.py; this is step (2) of the BizHawk
re-point — confirm joypad.set over the bridge changes game state. Stand the
player somewhere walkable in the overworld first (NOT in a menu/dialogue), then:

  1. In the running EmuHawk, load bizhawk/ai_bridge.lua via Tools > Lua Console.
  2. Run:  C:/pokeai-venv/Scripts/python.exe scripts/smoke_bizhawk_input.py

It reads the live player position, taps each direction with press_direction_settle,
and reports whether the position changed — GREEN if any direction moved the player.
"""
from __future__ import annotations

import sys

from pokeai.emulator.bizhawk_bridge import BizHawkBridge


def main() -> int:
    b = BizHawkBridge(timeout=90)
    print("listening on 127.0.0.1:51055 — load bizhawk/ai_bridge.lua…", flush=True)
    try:
        b.wait_for_bizhawk()
    except Exception as e:
        print(f"FAIL: BizHawk never connected ({type(e).__name__}: {e})")
        return 2
    print("connected. ping:", b.ping(), flush=True)

    start = b.player_xy()
    print(f"start player_xy (raw object coords) = {start}", flush=True)
    moved_any = False
    for d in ("Up", "Down", "Left", "Right"):
        before = b.player_xy()
        moved = b.press_direction_settle(d)
        after = b.player_xy()
        ok = moved and after != before
        moved_any = moved_any or ok
        print(f"  {d:<5} moved={ok}  {before} -> {after}", flush=True)

    b.close()
    print(f"\nBIZHAWK INPUT: {'GREEN — joypad moves the player' if moved_any else 'RED — no movement (in a menu/wall? try a different tile)'}")
    return 0 if moved_any else 1


if __name__ == "__main__":
    sys.exit(main())
