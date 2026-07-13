"""G5 catching, step 2: from slot 8 (Route 1 with balls) trigger a REAL wild
battle (active enemy AND movement locked, to dodge the lingering-gEnemyParty
false positive), ride the intro to the action menu, open the BAG, and screenshot
each step so we can map the FireRed in-battle bag layout + build the throw.
Iterates cheaply from slot 8. stream.py STOPPED.
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

SLOTS = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai\states\slots"
OUT = r"C:\Users\Sagac\AppData\Local\Temp\claude\C--Program-Files-Git\0ce068f5-fdaf-4e80-b3d3-05f89c188438\scratchpad"


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def moved(b, d):
    p0 = b.player_xy()
    b.press_direction_settle(d)
    return b.player_xy() != p0


def in_real_battle(b, battle):
    """active enemy AND we cannot move (a lingering post-battle enemy reads
    active but we're free to walk)."""
    if not battle.active():
        return False
    return not (moved(b, "LEFT") or moved(b, "RIGHT"))


def main() -> int:
    b = BizHawkBridge(timeout=120)
    b.wait_for_bizhawk()
    nav = Navigator(b)
    battle = Battle(b)
    if not b.load_state(SLOTS + r"\slot_8.state"):
        say("FAIL slot 8")
        return 1
    time.sleep(1.2)
    say(f"start {nav.current_map()} pos {nav.vision.player_xy()}")

    # move UP into the mid-route grass, then pace until a REAL battle
    for _ in range(6):
        b.press_direction_settle("UP")
    pattern = ["LEFT", "LEFT", "UP", "RIGHT", "DOWN", "LEFT", "UP", "RIGHT"]
    got = False
    for step in range(50):
        if battle.active() and in_real_battle(b, battle):
            got = True
            break
        b.press_direction_settle(pattern[step % len(pattern)])
        time.sleep(0.05)
    if not got:
        say("no REAL wild battle in 50 steps")
        b.screenshot(OUT + r"\catch_nogr.png")
        return 1
    lvl, hp, mx = battle.enemy_stats()
    say(f"REAL WILD BATTLE at {b.player_xy()}: enemy lv{lvl} {hp}/{mx}")

    # Intro flow (mapped live): "Wild X appeared!" WAITS for A; press A ->
    # "Go! CLAW!" + a long send-out ANIMATION; the action menu then appears on
    # its OWN. Presses during the animation are eaten (safe), so: advance the
    # first box with A, then WAIT ~7s for the menu, then navigate it.
    b.tap("A", 6); time.sleep(0.5)   # advance "Wild X appeared!"
    b.tap("A", 6); time.sleep(0.5)   # advance "Go! CLAW!" text (start send-out)
    time.sleep(7.0)                   # let the send-out animation finish -> menu
    b.screenshot(OUT + r"\cb_1_menu.png")
    say("shot cb_1_menu (should be the action menu now)")
    # cursor defaults to FIGHT (top-left); RIGHT -> BAG (top-right), A opens it
    b.tap("RIGHT", 6); time.sleep(0.5)
    b.screenshot(OUT + r"\cb_2_baghover.png")
    b.tap("A", 6); time.sleep(1.5)
    b.screenshot(OUT + r"\cb_3_bagopen.png")
    say("shot cb_3_bagopen (bag pocket + item list)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
