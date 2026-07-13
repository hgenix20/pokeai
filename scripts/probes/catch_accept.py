"""G5 ACCEPTANCE TEST via the reusable Catch skill: from slot 8, enter a real
wild battle and throw balls until caught or out. PASS == party_count 1 -> 2
(RAM-honest). Exercises src/pokeai/skills/catch.py end to end. stream.py STOPPED.
"""
from __future__ import annotations

import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.emulator.firered_state_reader import GPLAYER_PARTY_COUNT
from pokeai.perception.navigator import Navigator
from pokeai.skills.battle import Battle
from pokeai.skills.catch import Catch

SLOTS = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai\states\slots"
OUT = r"C:\Users\Sagac\AppData\Local\Temp\claude\C--Program-Files-Git\0ce068f5-fdaf-4e80-b3d3-05f89c188438\scratchpad"


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def moved(b, d):
    p0 = b.player_xy()
    b.press_direction_settle(d)
    return b.player_xy() != p0


def in_real_battle(b, battle):
    return battle.active() and not (moved(b, "LEFT") or moved(b, "RIGHT"))


def main() -> int:
    b = BizHawkBridge(timeout=120)
    b.wait_for_bizhawk()
    nav = Navigator(b)
    battle = Battle(b)
    catch = Catch(b, battle)
    if not b.load_state(SLOTS + r"\slot_8.state"):
        say("FAIL slot 8")
        return 1
    time.sleep(1.2)
    party0 = b.read_byte(GPLAYER_PARTY_COUNT)
    say(f"start party_count={party0}")

    for _ in range(6):
        b.press_direction_settle("UP")
    pattern = ["LEFT", "LEFT", "UP", "RIGHT", "DOWN", "LEFT", "UP", "RIGHT"]
    got = False
    for step in range(60):
        if battle.active() and in_real_battle(b, battle):
            got = True
            break
        b.press_direction_settle(pattern[step % len(pattern)])
        time.sleep(0.05)
    if not got:
        say("no REAL wild battle")
        return 1
    say(f"REAL WILD BATTLE: enemy lv{battle.enemy_stats()[0]}")

    result = catch.attempt(max_balls=5, narrate=say)
    b.screenshot(OUT + r"\ca_result.png")
    party1 = b.read_byte(GPLAYER_PARTY_COUNT)
    say(f"RESULT={result}  party {party0} -> {party1}  "
        f"{'PASS' if party1 > party0 else 'no-catch'}")
    return 0 if party1 > party0 else 2


if __name__ == "__main__":
    sys.exit(main())
