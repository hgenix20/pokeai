"""Verify the BizHawk bridge: wait for ai_bridge.lua to connect, then read the
ROM header (proves RAM/ROM reads work) regardless of game progress. Runs on
Windows (the project venv); launch an EmuHawk with --lua=bizhawk/ai_bridge.lua
pointing at the FireRed ROM, and this will connect to it.
"""
from __future__ import annotations

import sys

from pokeai.emulator.bizhawk_bridge import BizHawkBridge


def main() -> int:
    b = BizHawkBridge(timeout=90)
    print("listening on 127.0.0.1:51055 — waiting for BizHawk ai_bridge.lua…", flush=True)
    try:
        b.wait_for_bizhawk()
    except Exception as e:
        print(f"FAIL: BizHawk never connected ({type(e).__name__}: {e})")
        return 2
    print("connected. ping:", b.ping(), flush=True)
    title = bytes(b.read_range(0x080000A0, 0x080000AC)).decode("ascii", "replace")
    code = bytes(b.read_range(0x080000AC, 0x080000B0)).decode("ascii", "replace")
    print(f"ROM header: title={title!r} code={code!r}")
    print("multi-read [romhdr u32, ewram u32]:",
          [hex(v) for v in b.read_many([(0x080000A0, 4), (0x02000000, 4)])])
    b.close()
    ok = "POKEMON" in title.upper()
    print(f"\nBIZHAWK BRIDGE: {'GREEN — reads work' if ok else 'RED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
