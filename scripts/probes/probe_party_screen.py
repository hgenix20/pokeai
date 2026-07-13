"""Micro-probe the stuck in-battle party screen: one press at a time with a
screenshot after each, so the real cursor behavior is visible. stream.py OFF.
"""
from __future__ import annotations

import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from pokeai.emulator.bizhawk_bridge import BizHawkBridge

OUT = r"C:\Users\Sagac\AppData\Local\Temp\claude\C--Program-Files-Git\166a5709-56c5-4d9e-b14e-311acd851a68\scratchpad"
SEQ = [("B", 0.8), ("B", 0.8), ("UP", 0.6), ("UP", 0.6), ("UP", 0.6),
       ("UP", 0.6), ("A", 1.2), ("A", 1.2)]


def main() -> int:
    b = BizHawkBridge(timeout=120)
    b.wait_for_bizhawk()
    b.screenshot(OUT + r"\pp_00_start.png")
    for i, (btn, pause) in enumerate(SEQ, 1):
        b.tap(btn, 6)
        time.sleep(pause)
        b.screenshot(OUT + rf"\pp_{i:02d}_{btn}.png")
        print(f"pressed {btn}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
