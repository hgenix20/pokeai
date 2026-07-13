"""Diagnose buy_at_mart: drive the Viridian Mart purchase step by step with a
screenshot after every input group. Uses the CURRENT live state (should be in
or near the Mart after the failed restock attempts). stream.py STOPPED.
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
from pokeai.skills.overworld import Overworld
from pokeai.skills.services import MARTS, Services

OUT = r"C:\Users\Sagac\AppData\Local\Temp\claude\C--Program-Files-Git\166a5709-56c5-4d9e-b14e-311acd851a68\scratchpad"
VIRIDIAN = (3, 1)


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    b = BizHawkBridge(timeout=120)
    b.wait_for_bizhawk()
    reader = FireRedStateReader(b)
    nav = Navigator(b)
    ow = Overworld(b, nav, reader)
    svc = Services(b, nav, ow, reader)
    info = MARTS[VIRIDIAN]

    say(f"map {nav.current_map()} pos {nav.vision.player_xy()} "
        f"money {reader.read_money()} balls {reader.ball_count()}")
    b.screenshot(OUT + r"\buy_0_start.png")

    if nav.current_map() != info["map"]:
        say("entering the Mart…")
        if not svc._enter(info):
            say(f"FAIL enter: {nav.current_map()}")
            return 1
    ow.wait_control(10)
    say(f"in Mart at {nav.vision.player_xy()}; npcs {sorted(nav.vision.object_tiles())}")
    b.screenshot(OUT + r"\buy_1_inside.png")

    stand = info.get("stand", (info["clerk"][0], info["clerk"][1] + 2))
    ok = nav.go_to(stand)
    say(f"go_to stand {stand} -> {ok}; pos {nav.vision.player_xy()}")
    b.press_button_held("UP", 12); time.sleep(0.3)
    b.screenshot(OUT + r"\buy_2_at_counter.png")

    b.tap("A", 6); time.sleep(1.2)
    b.screenshot(OUT + r"\buy_3_after_A_greet.png")
    b.tap("A", 6); time.sleep(1.4)
    b.screenshot(OUT + r"\buy_4_after_A_buy.png")
    b.tap("A", 6); time.sleep(0.9)
    b.screenshot(OUT + r"\buy_5_after_A_item.png")
    for _ in range(4):
        b.tap("UP", 5); time.sleep(0.25)
    b.screenshot(OUT + r"\buy_6_after_qty.png")
    b.tap("A", 6); time.sleep(0.9)
    b.screenshot(OUT + r"\buy_7_after_qty_confirm.png")
    b.tap("A", 6); time.sleep(1.4)
    b.screenshot(OUT + r"\buy_8_after_yes.png")
    for _ in range(4):
        b.tap("B", 5); time.sleep(0.4)
    b.screenshot(OUT + r"\buy_9_after_b.png")

    say(f"money {reader.read_money()} balls {reader.ball_count()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
