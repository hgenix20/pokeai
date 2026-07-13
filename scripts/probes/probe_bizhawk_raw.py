"""Raw memory probe over the BizHawk bridge — diagnose whether EWRAM/IWRAM hold
live game state. Prints the SaveBlock pointers, gMain, and raw bytes from EWRAM/
IWRAM/gObjectEvents. Non-zero SaveBlock pointers => the game is booted into a
save; all zeros => title/intro screen (not in the overworld yet)."""
from __future__ import annotations

from pokeai.emulator.bizhawk_bridge import BizHawkBridge


def main() -> int:
    b = BizHawkBridge(timeout=30)
    print("waiting for ai_bridge.lua…", flush=True)
    b.wait_for_bizhawk()
    print("ping:", b.ping())
    print("SB1 ptr @03005008 = %08x" % b.read_u32(0x03005008))
    print("SB2 ptr @0300500C = %08x" % b.read_u32(0x0300500C))
    print("gMain   @030030F0 = %08x" % b.read_u32(0x030030F0))
    print("EWRAM   @02000000 :", bytes(b.read_range(0x02000000, 0x02000010)).hex())
    print("IWRAM   @03000000 :", bytes(b.read_range(0x03000000, 0x03000010)).hex())
    print("gObjEvt @02036E38 :", bytes(b.read_range(0x02036E38, 0x02036E60)).hex())
    b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
