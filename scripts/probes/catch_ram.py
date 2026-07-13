"""G5 catch unblock, v2. Find a ROBUST "action menu is up / waiting for player"
signal in FireRed battle RAM, WITHOUT relying on fixed timing or screenshots.

Key insight: when the 2x2 action menu (FIGHT/BAG/POKEMON/RUN) is up and waiting,
tapping RIGHT/LEFT moves the FIGHT<->BAG cursor, which TOGGLES a battle-state RAM
byte. During the send-out ANIMATION, presses are eaten and nothing toggles. So
  "menu is up"  ==  "a monitored byte responds to a RIGHT/LEFT tap".
That test also reveals the cursor address (usable to drive the menu deterministically).

Uses the WORKING real-battle detector (active AND movement-locked) to dodge the
lingering-gEnemyParty false positive that plain battle.active() trips on (slot 8
loads with a stale enemy from earlier battles). stream.py STOPPED. Iterates slot 8.
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

# battle-state regions to monitor (FireRed BPRE US). Wide enough to catch the
# action cursor + the "waiting for player action" controller state.
REGIONS = [
    ("iwram_battlefuncs", 0x03004300, 0x03004360),   # gBattleMainFunc / controller fns
    ("ewram_battlecomm", 0x02023B00, 0x02023C40),     # gBattleCommunication / cursors
    ("ewram_actioncursor", 0x02023FE0, 0x02024060),   # action/move selection cursors
]


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def snap(b):
    out = {}
    for name, a, e in REGIONS:
        try:
            out[name] = (a, bytes(b.read_range(a, e)))
        except Exception as ex:
            out[name] = (a, b"")
            say(f"  read {name} failed: {ex}")
    return out


def changed_bytes(s1, s2):
    """list of (name, addr, v1, v2) that differ between two snapshots."""
    out = []
    for name, (a, d1) in s1.items():
        d2 = s2[name][1]
        for i in range(min(len(d1), len(d2))):
            if d1[i] != d2[i]:
                out.append((name, a + i, d1[i], d2[i]))
    return out


def moved(b, d):
    p0 = b.player_xy()
    b.press_direction_settle(d)
    return b.player_xy() != p0


def in_real_battle(b, battle):
    if not battle.active():
        return False
    return not (moved(b, "LEFT") or moved(b, "RIGHT"))


def cursor_responds(b):
    """Return the set of (name,addr) bytes that behave like the action-menu cursor:
    STABLE at rest, CHANGE on RIGHT, and RESTORE on LEFT. This rejects time-varying
    bytes (animation/RNG counters) that a naive before/after diff would flag during
    the battle intro. Non-empty => the action menu is genuinely up. Net cursor pos
    restored (RIGHT then LEFT)."""
    r0 = snap(b); time.sleep(0.4)
    r1 = snap(b)                                   # rest interval, no input
    noisy = {(n, a) for (n, a, _, _) in changed_bytes(r0, r1)}  # timers/RNG -> exclude
    base = snap(b)
    b.tap("RIGHT", 5); time.sleep(0.4)
    right = snap(b)
    b.tap("LEFT", 5); time.sleep(0.4)              # restore cursor to FIGHT
    back = snap(b)
    moved_on_right = {(n, a) for (n, a, _, _) in changed_bytes(base, right)}
    restored_on_left = {(n, a) for (n, a, _, _) in changed_bytes(right, back)}
    # cursor byte: not noisy, moved on RIGHT, and moved back on LEFT
    return (moved_on_right & restored_on_left) - noisy


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
        f"battle.active={battle.active()} (stale enemy ok; using movement-lock)")

    # pace grass; stop only on a REAL battle (active AND movement-locked)
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
        b.screenshot(OUT + r"\cr_nobattle.png")
        return 1
    lvl, hp, mx = battle.enemy_stats()
    say(f"REAL WILD BATTLE at {b.player_xy()}: enemy lv{lvl} {hp}/{mx} (full={hp==mx})")

    # POLL for the menu. Each cycle: (1) test cursor response FIRST so we detect
    # the menu the instant it's up (before any A opens the FIGHT submenu); (2) if
    # not up yet, tap A to advance an intro text box ("Wild X appeared!" ->
    # "Go! MON!" -> send-out animation -> menu). A during animation is eaten (safe).
    menu_tick = None
    for i in range(30):  # up to ~30 * ~1.2s
        resp = cursor_responds(b)
        if resp:
            menu_tick = i
            say(f"MENU UP at poll {i}: cursor-responsive bytes -> "
                + ", ".join(f"{a:#08x}" for (_, a) in sorted(resp)))
            break
        b.tap("A", 8); time.sleep(0.5)  # advance intro text / no-op during animation
    if menu_tick is None:
        say("cursor never responded in ~22s (menu not detected)")
        b.screenshot(OUT + r"\cr_nomenu.png")
        return 1

    b.screenshot(OUT + r"\cr_menu.png")
    say("shot cr_menu (action menu, cursor on FIGHT)")

    # now open the BAG (RIGHT -> BAG, A) and screenshot the pocket/item layout
    b.tap("RIGHT", 6); time.sleep(0.5)
    b.tap("A", 6); time.sleep(1.4)
    b.screenshot(OUT + r"\cr_bag.png")
    say("shot cr_bag (in-battle bag pocket + items)")

    # capture the full FIGHT-cursor snapshot so we can hard-code the menu signal
    b.tap("B", 6); time.sleep(0.8)
    fight = snap(b)
    say("--- action-menu snapshot (cursor=FIGHT) key bytes ---")
    for name, (a, d) in fight.items():
        say(f"  {name} @ {a:#08x}: " + d[:32].hex())
    say("done; menu signal = cursor-responsive byte(s) above")
    return 0


if __name__ == "__main__":
    sys.exit(main())
