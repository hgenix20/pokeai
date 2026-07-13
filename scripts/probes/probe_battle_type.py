"""G7: pin down gBattleTypeFlags (wild vs trainer) empirically.

TRAINER sample: slot 1 (starter in hand) - walking toward the lab door fires
GROK's scripted battle. WILD sample: slot 9 party (Route 1 grass hunt).
Dump u32s around the pokefirered candidate 0x02022B4C during each and diff;
the trainer bit (BATTLE_TYPE_TRAINER = 1<<3) should flip. stream.py STOPPED.
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
from pokeai.skills.catch import Catch

SLOTS = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai\states\slots"
BASE, END = 0x02022B00, 0x02022B80


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def dump(b) -> dict:
    return {a: b.read_u32(a) for a in range(BASE, END, 4)}


def main() -> int:
    b = BizHawkBridge(timeout=180)
    b.wait_for_bizhawk()
    nav = Navigator(b)
    battle = Battle(b)
    catch = Catch(b, battle)

    # --- trainer sample: GROK's scripted fight from slot 1 ---
    say("loading slot 1 (starter in hand, rival battle pending)…")
    if not b.load_state(SLOTS + r"\slot_1.state"):
        say("FAIL slot 1")
        return 1
    time.sleep(1.2)
    say(f"map {nav.current_map()} pos {nav.vision.player_xy()}")
    # GROK's challenge fires on the walk to the lab DOOR (bottom-center):
    # navigate toward the exit row, then step down; ride his dialogue with A.
    nav.go_to((6, 9), attempts=8)
    for _ in range(30):
        if battle.active():
            break
        p0 = b.player_xy()
        b.press_direction_settle("DOWN")
        if b.player_xy() == p0:      # blocked or script holding: ride dialogue
            b.tap("A", 6); time.sleep(0.4)
    if not catch.wait_for_menu(tries=30):
        say("FAIL: no trainer battle menu")
        return 1
    trainer = dump(b)
    say(f"TRAINER battle menu up (foe {battle.enemy_stats()})")

    # --- wild sample: slot 8 (Route 1 south grass, the catch checkpoint) ---
    say("loading slot 8 (Route 1 grass)…")
    if not b.load_state(SLOTS + r"\slot_8.state"):
        say("FAIL slot 8")
        return 1
    time.sleep(1.2)
    for _ in range(6):
        b.press_direction_settle("UP")
    pattern = ["LEFT", "LEFT", "UP", "RIGHT", "DOWN", "LEFT", "UP", "RIGHT"]
    got = False
    for step in range(80):
        if battle.active() and catch.confirm_real_battle(max_tries=4):
            got = True
            break
        b.press_direction_settle(pattern[step % len(pattern)])
        time.sleep(0.05)
    if not got:
        say("FAIL: no wild battle")
        return 1
    wild = dump(b)
    say(f"WILD battle menu up (foe {battle.enemy_stats()})")

    say("addr        trainer      wild        diff")
    for a in sorted(trainer):
        t, w = trainer[a], wild[a]
        mark = "  <== " if t != w else ""
        if t != w or a == 0x02022B4C:
            say(f"{a:#010x}  {t:#010x}  {w:#010x}{mark}")
    c = 0x02022B4C
    say(f"candidate gBattleTypeFlags {c:#x}: trainer={trainer[c]:#x} wild={wild[c]:#x} "
        f"trainer_bit(0x8): {bool(trainer[c] & 8)} vs {bool(wild[c] & 8)}")
    if (trainer[c] & 8) and not (wild[c] & 8):
        say("PASS - 0x02022B4C is gBattleTypeFlags (bit 3 = trainer)")
        return 0
    say("candidate did not behave; inspect the diff above")
    return 2


if __name__ == "__main__":
    sys.exit(main())
