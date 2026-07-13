"""Diagnose the slot-0 load failure: screenshot what's on screen, try the
savestate load while checking the bridge's actual reply, and re-read state."""
from __future__ import annotations

import time

from pokeai.emulator.bizhawk_bridge import BizHawkBridge

ROOT = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai"
SLOT0 = ROOT + r"\states\slots\slot_0.state"
OUT = ROOT + r"\states\bizhawk"


def main() -> int:
    b = BizHawkBridge(timeout=30)
    print("waiting for ai_bridge…", flush=True)
    b.wait_for_bizhawk()
    print("connected:", b.ping(), flush=True)

    b.screenshot(OUT + r"\diag_before.png")
    print("screen before -> diag_before.png", flush=True)
    print("xy before:", b.player_xy(), flush=True)

    ok = b.load_state(SLOT0)
    print(f"load_state returned: {ok!r}", flush=True)
    time.sleep(2.0)

    print("xy after:", b.player_xy(), flush=True)
    b.screenshot(OUT + r"\diag_after.png")
    print("screen after -> diag_after.png", flush=True)
    b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
