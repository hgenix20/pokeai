"""G5 ACCEPTANCE TEST: actually CATCH a wild Pokemon from slot 8, proving the
whole vertical slice (menu-state detection -> BAG -> Balls pocket -> throw ->
confirm). Success == party_count goes 1 -> 2 (RAM-honest, not a screenshot claim).

Flow, built on the live-confirmed signals:
  * real battle  : active AND movement-locked (dodges the stale-gEnemyParty FP)
  * menu is up   : action cursor 0x02023FF8 responds to RIGHT/LEFT (0=FIGHT,1=BAG,
                   2=POKEMON,3=RUN); stable at rest, so no false positive on the intro
  * throw        : RIGHT->BAG, A; RIGHT switches ITEMS->POKe BALLS pocket; A selects
                   the top ball and throws it
  * post-throw   : mash B (not A) -- B advances every text box AND declines the
                   "give a nickname?" YES/NO prompt (B == NO), so the whole
                   wobble/Gotcha/nickname sequence resolves cleanly
  * caught?      : poll party_count (0x02024029); +1 == caught

stream.py STOPPED. Iterates from slot 8. Screenshots each step for verification.
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

ACTION_CURSOR = 0x02023FF8   # gActionSelectionCursor (0=FIGHT 1=BAG 2=POKEMON 3=RUN)
PARTY_COUNT = 0x02024029     # gPlayerPartyCount (u8)


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def moved(b, d):
    p0 = b.player_xy()
    b.press_direction_settle(d)
    return b.player_xy() != p0


def in_real_battle(b, battle):
    if not battle.active():
        return False
    return not (moved(b, "LEFT") or moved(b, "RIGHT"))


def menu_up(b):
    """True iff the action cursor responds to RIGHT/LEFT (menu genuinely up).
    Restores the cursor to FIGHT. Rejects intro-animation noise via stable-at-rest."""
    r0 = b.read_byte(ACTION_CURSOR); time.sleep(0.35)
    r1 = b.read_byte(ACTION_CURSOR)
    if r0 != r1:
        return False                      # value drifting on its own -> not the menu
    b.tap("RIGHT", 5); time.sleep(0.35)
    moved_r = b.read_byte(ACTION_CURSOR)
    b.tap("LEFT", 5); time.sleep(0.35)    # restore to FIGHT
    back = b.read_byte(ACTION_CURSOR)
    return moved_r != r0 and back == r0


def main() -> int:
    b = BizHawkBridge(timeout=120)
    b.wait_for_bizhawk()
    nav = Navigator(b)
    battle = Battle(b)
    if not b.load_state(SLOTS + r"\slot_8.state"):
        say("FAIL slot 8")
        return 1
    time.sleep(1.2)
    say(f"start {nav.current_map()} pos {nav.vision.player_xy()} "
        f"party_count={b.read_byte(PARTY_COUNT)}")

    # 1) pace grass -> real wild battle
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
        say("no REAL wild battle in 60 steps")
        return 1
    lvl, hp, mx = battle.enemy_stats()
    party_before = b.read_byte(PARTY_COUNT)
    say(f"REAL WILD BATTLE: enemy lv{lvl} {hp}/{mx}; party_before={party_before}")

    # 2) advance intro -> action menu. Use B (not A) to advance: B advances the
    #    intro text boxes just like A, but is HARMLESS if the menu is already up
    #    (no-op at the action menu; backs out of any accidental submenu). So if
    #    menu_up() races to a false-negative on the poll the menu appears, the B
    #    tap can't strand us in FIGHT the way an A would.
    menu_ok = False
    for i in range(30):
        if menu_up(b):
            menu_ok = True
            say(f"menu up at poll {i} (cursor@FIGHT={b.read_byte(ACTION_CURSOR)})")
            break
        b.tap("B", 8); time.sleep(0.5)
    if not menu_ok:
        say("menu never came up")
        b.screenshot(OUT + r"\ct_nomenu.png")
        return 1

    # 3) FIGHT -> BAG (cursor 0 -> 1), open bag
    b.tap("RIGHT", 6); time.sleep(0.3)
    say(f"cursor after RIGHT = {b.read_byte(ACTION_CURSOR)} (want 1=BAG)")
    b.tap("A", 6); time.sleep(1.3)
    b.screenshot(OUT + r"\ct_1_bag_items.png")

    # 4) ITEMS -> POKe BALLS pocket. Battle bag pocket order is
    #    ITEMS -> KEY ITEMS -> POKe BALLS -> ..., so RIGHT twice from the default.
    b.tap("RIGHT", 6); time.sleep(0.5)   # ITEMS -> KEY ITEMS
    b.tap("RIGHT", 6); time.sleep(0.7)   # KEY ITEMS -> POKe BALLS
    b.screenshot(OUT + r"\ct_2_bag_balls.png")
    say("switched to POKe BALLS pocket (expect Poke Ball x5, cursor on first ball)")

    # 5) select top ball -> throw (A), plus one A for any use/confirm submenu
    b.tap("A", 6); time.sleep(0.8)
    b.screenshot(OUT + r"\ct_3_after_select.png")
    b.tap("A", 6); time.sleep(0.8)   # confirm USE/throw if a submenu appeared
    say("threw ball; watching party_count for a catch")

    # 6) mash B (advances text + declines nickname) while polling party_count
    caught = False
    for i in range(40):  # ~40 * 0.5s = 20s
        pc = b.read_byte(PARTY_COUNT)
        if pc > party_before:
            caught = True
            say(f"CAUGHT! party_count {party_before} -> {pc} at poll {i}")
            break
        b.tap("B", 5); time.sleep(0.5)
    b.screenshot(OUT + r"\ct_4_result.png")

    if not caught:
        say(f"NOT caught (party still {b.read_byte(PARTY_COUNT)}); "
            f"battle.active={battle.active()} -- ball may have broken free")
        return 2

    # settle post-catch, confirm back to a stable state
    for _ in range(6):
        b.tap("B", 5); time.sleep(0.3)
    say(f"done: party_count={b.read_byte(PARTY_COUNT)} battle.active={battle.active()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
