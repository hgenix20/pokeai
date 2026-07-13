"""G5 ACCEPTANCE v2 — WEAKEN-FIRST catch via the reusable Catch skill.

From slot 8 (Route 1, 5 balls, CLAW lv6): enter a real wild battle, weaken the
foe to <=30% HP with move slot 1 (Tackle), then throw. PASS == party_count +1
(RAM-honest) with the new member's species decoded and logged. A weaken KO
('fainted_target') re-hunts on the next encounter, up to 4 encounters.

stream.py STOPPED (single bridge owner).
"""
from __future__ import annotations

import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.emulator.firered_state_reader import FireRedStateReader, GPLAYER_PARTY_COUNT
from pokeai.perception.navigator import Navigator
from pokeai.skills.battle import Battle
from pokeai.skills.catch import Catch

SLOTS = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai\states\slots"
OUT = r"C:\Users\Sagac\AppData\Local\Temp\claude\C--Program-Files-Git\166a5709-56c5-4d9e-b14e-311acd851a68\scratchpad"


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def moved(b, d):
    p0 = b.player_xy()
    b.press_direction_settle(d)
    return b.player_xy() != p0


def in_real_battle(b, battle):
    return battle.active() and not (moved(b, "LEFT") or moved(b, "RIGHT"))


def hunt(b, battle, max_steps=60) -> bool:
    pattern = ["LEFT", "LEFT", "UP", "RIGHT", "DOWN", "LEFT", "UP", "RIGHT"]
    for step in range(max_steps):
        if battle.active() and in_real_battle(b, battle):
            return True
        b.press_direction_settle(pattern[step % len(pattern)])
        time.sleep(0.05)
    return False


def main() -> int:
    b = BizHawkBridge(timeout=120)
    b.wait_for_bizhawk()
    Navigator(b)  # warms vision caches; not otherwise needed here
    battle = Battle(b)
    catch = Catch(b, battle)
    reader = FireRedStateReader(b)
    if not b.load_state(SLOTS + r"\slot_8.state"):
        say("FAIL slot 8")
        return 1
    time.sleep(1.2)
    party0 = b.read_byte(GPLAYER_PARTY_COUNT)
    say(f"start party_count={party0} balls={reader.ball_count()}")

    for _ in range(6):
        b.press_direction_settle("UP")

    for enc in range(4):
        if not hunt(b, battle):
            say("no REAL wild battle")
            return 1
        lvl, ehp, emax = battle.enemy_stats()
        say(f"encounter {enc + 1}: REAL WILD BATTLE, foe lv{lvl} {ehp}/{emax} HP")

        result = catch.attempt(max_balls=5, narrate=say, weaken_to=0.30)
        say(f"attempt result: {result} (balls thrown: {catch.balls_thrown})")
        if result == "fainted_target":
            continue
        break

    b.screenshot(OUT + r"\ca2_result.png")
    party1 = b.read_byte(GPLAYER_PARTY_COUNT)
    if party1 > party0:
        sp = reader.read_species(party1 - 1)
        det = reader.read_party_details()[party1 - 1]
        say(f"new member: species {sp} lv{det['level']} {det['hp']}/{det['max_hp']} HP")
    say(f"party {party0} -> {party1}  balls left {reader.ball_count()}  "
        f"{'PASS' if party1 > party0 else 'no-catch'}")
    return 0 if party1 > party0 else 2


if __name__ == "__main__":
    sys.exit(main())
