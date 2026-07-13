"""One press + screenshot: the screenshot-first micro-tool for driving
menus by eye. Usage:  probe_press.py [BUTTON] [hold_frames]
No button = screenshot only. Saves to probe_press\\last.png."""
from __future__ import annotations

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

from pokeai.emulator.bizhawk_bridge import BizHawkBridge

OUT = r"C:\pokeai-states\probe_press"


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    b = BizHawkBridge(timeout=30)
    b.wait_for_bizhawk()
    if len(sys.argv) > 1:
        button = sys.argv[1].upper()
        frames = int(sys.argv[2]) if len(sys.argv) > 2 else 8
        b.press_button_held(button, frames)
        time.sleep(0.7)
        print(f"pressed {button} ({frames}f)")
    b.screenshot(OUT + r"\last.png")
    print("shot saved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
