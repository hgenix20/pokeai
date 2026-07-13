"""Drive BizHawk by a sequence of actions, screenshotting after each so the AI
can watch the result frame-by-frame. Connects once.

Each arg is one action:
  A | B | START | SELECT | UP | DOWN | LEFT | RIGHT   (a button pulse; :N = frames)
  wait:N                                              (let ~N frames pass, no input)
  shot                                                (screenshot only)

Screens -> states/bizhawk/step_NN_<label>.png
"""
from __future__ import annotations

import os
import sys
import time

from pokeai.emulator.bizhawk_bridge import BizHawkBridge

OUT = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai\states\bizhawk"


def main() -> int:
    actions = sys.argv[1:]
    b = BizHawkBridge(timeout=30)
    print("waiting for ai_bridge.lua…", flush=True)
    b.wait_for_bizhawk()
    print("ping:", b.ping(), flush=True)

    def shot(i: int, label: str) -> None:
        safe = "".join(c if c.isalnum() else "_" for c in label)  # legal Win filename
        p = os.path.join(OUT, f"step_{i:02d}_{safe}.png")
        b.screenshot(p)
        print(f"  [{i:02d}] {label:8s} -> {p}", flush=True)

    shot(0, "before")
    for i, a in enumerate(actions, 1):
        if a.startswith("wait:"):
            b.tick(int(a.split(":")[1]))
            label = a
        elif a.startswith("hold:"):
            parts = a.split(":")
            btn = parts[1].upper()
            frames = int(parts[2]) if len(parts) > 2 else 30
            b.set_held([btn])
            b.tick(frames)
            b.release()
            label = "hold_" + btn
        elif a == "shot":
            label = "shot"
        else:
            btn, _, fr = a.partition(":")
            b.press_button_pulse(btn.upper(), int(fr) if fr else 16)
            label = btn.upper()
        time.sleep(0.3)
        shot(i, label)

    b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
