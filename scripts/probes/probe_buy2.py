"""Buy diagnostic round 2: the clerk is behind the LEFT counter (~(2,3),
faces east). Stand at (3,3) facing LEFT and drive the buy menu with
screenshots. Uses the CURRENT live state (inside the Mart). stream.py STOPPED.
"""
from __future__ import annotations

import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.emulator.firered_state_reader import FireRedStateReader
from pokeai.perception.navigator import Navigator

OUT = r"C:\Users\Sagac\AppData\Local\Temp\claude\C--Program-Files-Git\166a5709-56c5-4d9e-b14e-311acd851a68\scratchpad"


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    b = BizHawkBridge(timeout=120)
    b.wait_for_bizhawk()
    reader = FireRedStateReader(b)
    nav = Navigator(b)

    say(f"map {nav.current_map()} pos {nav.vision.player_xy()} "
        f"money {reader.read_money()} balls {reader.ball_count()}")
    if nav.current_map() != (5, 3):
        say("not inside the Mart - abort")
        return 1

    ok = nav.go_to((4, 3))
    say(f"go_to (4,3) -> {ok}; pos {nav.vision.player_xy()}")
    b.press_button_held("LEFT", 12); time.sleep(0.3)
    b.screenshot(OUT + r"\b2_0_at_counter.png")

    b.tap("A", 6); time.sleep(1.2)
    b.screenshot(OUT + r"\b2_1_greet.png")
    b.tap("A", 6); time.sleep(1.4)
    b.screenshot(OUT + r"\b2_2_buy.png")
    b.tap("A", 6); time.sleep(0.9)
    b.screenshot(OUT + r"\b2_3_item.png")
    for _ in range(4):
        b.tap("UP", 5); time.sleep(0.25)
    b.screenshot(OUT + r"\b2_4_qty.png")
    b.tap("A", 6); time.sleep(0.9)
    b.screenshot(OUT + r"\b2_5_qtyok.png")
    b.tap("A", 6); time.sleep(1.4)
    b.screenshot(OUT + r"\b2_6_yes.png")
    for _ in range(5):
        b.tap("B", 5); time.sleep(0.4)
    b.screenshot(OUT + r"\b2_7_out.png")

    say(f"money {reader.read_money()} balls {reader.ball_count()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
