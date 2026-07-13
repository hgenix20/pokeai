"""Capture one screenshot of the live BizHawk screen via the bridge.

Requires the UPDATED bizhawk/ai_bridge.lua (with the 'S' command) to be loaded.
Saves to states/bizhawk/shot.png by default so the AI can read the actual screen.
"""
from __future__ import annotations

import os
import sys

from pokeai.emulator.bizhawk_bridge import BizHawkBridge

DEFAULT = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai\states\bizhawk\shot.png"


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    b = BizHawkBridge(timeout=30)
    print("waiting for ai_bridge.lua…", flush=True)
    b.wait_for_bizhawk()
    print("ping:", b.ping())
    b.screenshot(path)
    ok = os.path.exists(path) and os.path.getsize(path) > 0
    print(f"screenshot: {path}  exists={ok}  bytes={os.path.getsize(path) if ok else 0}")
    b.close()
    if not ok:
        print("RED — no file written. Is the UPDATED ai_bridge.lua reloaded? "
              "(old script has no 'S' command)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
