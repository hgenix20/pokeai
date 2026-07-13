"""G2 probe 2: from slot 3 (Route 1 south edge), walk north into grass until a
WILD battle triggers, A-mash it to a verdict, and report the XP/level delta.
RAM ground truth throughout. Bounded: 80 walk steps, 400 battle turns.

Run me with stream.py STOPPED (I bind 51055; ai_bridge.lua reconnects ~8s).
"""
from __future__ import annotations

import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.emulator.firered_state_reader import FireRedStateReader
from pokeai.perception.navigator import Navigator
from pokeai.skills.battle import Battle

ROOT = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai"
SLOTS = ROOT + r"\states\slots"


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    b = BizHawkBridge(timeout=180)
    say("waiting for ai_bridge to (re)connect…")
    b.wait_for_bizhawk()
    reader = FireRedStateReader(b)
    nav = Navigator(b)
    battle = Battle(b)

    say("loading slot 3 (Route 1 south edge)…")
    if not b.load_state(SLOTS + r"\slot_3.state"):
        say("FAIL: slot 3 load")
        return 1
    time.sleep(1.0)
    say(f"map {nav.current_map()} pos {b.player_xy()}")
    lvl0, hp0, mx0 = battle.my_stats()
    say(f"CLAW before: lv{lvl0} {hp0}/{mx0}")

    # LESSON (2026-07-03, verified live): encounters fire only on steps INSIDE
    # tall grass, and Route 1 has a one-way ledge across the path (~y=39) that
    # blocks a naive north walk. So: go a few tiles north, then step WEST into
    # the grass patch and pace within it. Encounter hit after 10 steps live.
    for _ in range(7):
        b.press_direction_settle("UP")
    pattern = ["LEFT", "LEFT", "LEFT", "UP", "DOWN", "LEFT",
               "RIGHT", "UP", "DOWN", "RIGHT"]
    in_battle = False
    for step in range(60):
        if battle.active():
            in_battle = True
            say(f"encounter after {step} grass steps at {b.player_xy()}")
            break
        b.press_direction_settle(pattern[step % len(pattern)])
        time.sleep(0.05)
    if not in_battle and not battle.active():
        say("FAIL: no wild battle in 60 grass steps")
        return 1

    elvl, ehp, emx = battle.enemy_stats()
    say(f"WILD BATTLE — foe lv{elvl} {ehp}/{emx}")
    verdict = battle.fight(narrate=lambda ln: say("  " + ln))
    say(f"verdict: {verdict}")
    if verdict != "win":
        say("FAIL: did not win (flee/potion logic is the G2 build)")
        return 1

    # ride post-battle text back to the overworld, then read the delta
    for _ in range(20):
        b.tap("A", 6)
        time.sleep(0.4)
    lvl1, hp1, mx1 = battle.my_stats()
    say(f"CLAW after: lv{lvl1} {hp1}/{mx1} (was lv{lvl0} {hp0}/{mx0})")
    say(f"WILD BATTLE WON — level delta {lvl1 - lvl0}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
