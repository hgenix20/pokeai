"""The game is sitting at a live battle action menu right now: test menu_up()
and confirm_real_battle() against it and print every intermediate read.
NO slot load - uses the live state. stream.py STOPPED.
"""
from __future__ import annotations

import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.perception.navigator import Navigator
from pokeai.skills.battle import Battle
from pokeai.skills.catch import ACTION_CURSOR, Catch


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    b = BizHawkBridge(timeout=120)
    b.wait_for_bizhawk()
    nav = Navigator(b)
    battle = Battle(b)
    catch = Catch(b, battle)

    say(f"pos {nav.vision.player_xy()} battle.active={battle.active()} "
        f"enemy={battle.enemy_stats()} me={battle.my_stats()}")

    r0 = b.read_byte(ACTION_CURSOR)
    time.sleep(0.3)
    r1 = b.read_byte(ACTION_CURSOR)
    say(f"cursor read: {r0} then {r1} (stable={r0 == r1})")
    b.tap("RIGHT", 5); time.sleep(0.3)
    r2 = b.read_byte(ACTION_CURSOR)
    say(f"after RIGHT tap: {r2} (changed={r2 != r1})")
    b.tap("LEFT", 5); time.sleep(0.3)
    r3 = b.read_byte(ACTION_CURSOR)
    say(f"after LEFT tap: {r3} (restored={r3 == r1})")

    say(f"menu_up() -> {catch.menu_up()}")
    say(f"confirm_real_battle() -> {catch.confirm_real_battle()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
