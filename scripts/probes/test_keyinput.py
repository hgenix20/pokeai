"""Definitive input test: hold buttons and read the GBA key register REG_KEYINPUT
(0x04000130, active-LOW: 0=pressed). Independent of game logic and screen state.

idle           = 0x03FF (all 10 bits set = nothing pressed)
bit0 A  bit1 B  bit2 Select  bit3 Start  bit4 Right  bit5 Left  bit6 Up  bit7 Down
If holding a button does NOT clear its bit, our joypad.set isn't reaching the core
(e.g. CrowdControl's connector overwriting input every frame).
"""
from __future__ import annotations

import time

from pokeai.emulator.bizhawk_bridge import BizHawkBridge

KEYINPUT = 0x04000130


def main() -> int:
    b = BizHawkBridge(timeout=30)
    print("waiting for ai_bridge.lua…", flush=True)
    b.wait_for_bizhawk()
    print("ping:", b.ping())
    print("idle KEYINPUT = 0x%04x (expect 0x03ff)" % b.read_u16(KEYINPUT))
    for btn, bit in [("START", 3), ("A", 0), ("RIGHT", 4)]:
        b.set_held([btn])
        time.sleep(0.12)
        vals = [b.read_u16(KEYINPUT) for _ in range(4)]
        b.release()
        time.sleep(0.05)
        pressed = any(((v >> bit) & 1) == 0 for v in vals)
        print(f"hold {btn:5s}: " + " ".join("0x%04x" % v for v in vals)
              + f"  -> bit{bit} cleared(pressed)={pressed}")
    print("idle KEYINPUT = 0x%04x" % b.read_u16(KEYINPUT))
    b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
