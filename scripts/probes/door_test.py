"""Empirically find the working 1F exit: try DOWN on the current tile, then go to
(3,8) and press DOWN onto the (3,9) door, reporting which one warps to Pallet."""
from __future__ import annotations

import time

from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.perception.navigator import Navigator


def main() -> int:
    b = BizHawkBridge(timeout=60)
    print("waiting for ai_bridge…", flush=True)
    b.wait_for_bizhawk()
    print("connected:", b.ping(), flush=True)
    nav = Navigator(b)
    start = nav.current_map()
    print(f"start map={start} pos={nav.vision.player_xy()}")

    print("[1] DOWN from current tile…")
    b.press_button_held("DOWN", 32)
    time.sleep(0.6)
    print(f"    -> map={nav.current_map()} pos={nav.vision.player_xy()}")
    if nav.current_map() != start:
        print("    WARPED via current-tile DOWN"); b.close(); return 0

    print("[2] go to (3,8) then DOWN onto the (3,9) door…")
    ok = nav.go_to((3, 8))
    time.sleep(0.3)
    print(f"    go_to(3,8)={ok}  pos={nav.vision.player_xy()}")
    b.press_button_held("DOWN", 32)
    time.sleep(0.6)
    print(f"    -> map={nav.current_map()} pos={nav.vision.player_xy()}")
    if nav.current_map() != start:
        print("    WARPED via (3,8)->DOWN"); b.close(); return 0

    print("    still inside — pos=", nav.vision.player_xy())
    b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
