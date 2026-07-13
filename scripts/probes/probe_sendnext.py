"""Resume the LIVE stuck trainer battle (CLAW fainted, send-next screen up)
with the fixed fight_smart: send_next_mon should drive a healthy mon out and
the battle should proceed to a verdict. No slot load. stream.py STOPPED.
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
from pokeai.skills.battle import Battle

OUT = r"C:\Users\Sagac\AppData\Local\Temp\claude\C--Program-Files-Git\166a5709-56c5-4d9e-b14e-311acd851a68\scratchpad"


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    b = BizHawkBridge(timeout=120)
    b.wait_for_bizhawk()
    reader = FireRedStateReader(b)
    nav = Navigator(b)
    battle = Battle(b, reader)

    say(f"map {nav.current_map()} trainer={battle.is_trainer_battle()} "
        f"fainted={battle.party_fainted_count()} "
        f"enemy alive={battle.enemy_alive_count()}")
    b.screenshot(OUT + r"\sendnext_before.png")

    res = battle.fight_smart(narrate=say, turn_cap=60)
    say(f"fight_smart -> {res}")
    d = reader.read_party_details()
    say(f"party {[(m['hp'], m['max_hp']) for m in d]} "
        f"levels {[m['level'] for m in d]} money {reader.read_money()}")
    b.screenshot(OUT + r"\sendnext_after.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
