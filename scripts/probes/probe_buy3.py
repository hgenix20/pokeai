"""Verify Services.buy_at_mart end to end (settle-paced, corrected counter).
Unwinds any leftover shop menus with B first (the live state is mid-probe),
then buys 5 Poke Balls and verifies by money + bag delta. stream.py STOPPED.
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
from pokeai.skills.services import Services

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

    say(f"map {nav.current_map()} pos {nav.vision.player_xy()} "
        f"money {reader.read_money()} balls {reader.ball_count()}")

    say("unwinding any open menus with B…")
    for _ in range(6):
        b.tap("B", 5)
        time.sleep(0.5)
    for _ in range(10):
        p0 = b.player_xy()
        b.press_direction_settle("DOWN")
        if b.player_xy() != p0:
            break
        b.tap("B", 5)
        time.sleep(0.4)
    say(f"free at {nav.vision.player_xy()} map {nav.current_map()}")

    res = svc.buy_at_mart(qty=5, slot=0, city_map=VIRIDIAN)
    b.screenshot(OUT + r"\buy3_result.png")
    say(f"buy_at_mart -> {res}")
    say(f"money {reader.read_money()} balls {reader.ball_count()}")
    ok = res.get("ok") and res.get("balls_added", 0) > 0
    say("PASS" if ok else "FAIL")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
