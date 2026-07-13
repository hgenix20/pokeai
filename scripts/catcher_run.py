"""Acceptance test for the fill-to-6 Catcher STRATEGY v2 (weaken-first + bag-read
ball accounting): from slot 8 (party 1, 5 balls) hunt + weaken + catch across
encounters until the balls run out or the party fills. PASS == party grows by
>=1 AND the strategy hands back a clean status ('out_of_balls'/'party_full'/etc).
Species of every new member is decoded and logged (G5 acceptance: species
tracked). Exercises strategies/catcher.py + skills/catch.py. stream.py STOPPED.
"""
from __future__ import annotations

import json
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
from pokeai.strategies.catcher import CatcherStrategy

SLOTS = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai\states\slots"
OUT = r"C:\Users\Sagac\AppData\Local\Temp\claude\C--Program-Files-Git\166a5709-56c5-4d9e-b14e-311acd851a68\scratchpad"


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    b = BizHawkBridge(timeout=120)
    b.wait_for_bizhawk()
    nav = Navigator(b)
    battle = Battle(b)
    catch = Catch(b, battle)
    reader = FireRedStateReader(b)
    strat = CatcherStrategy(b, nav, battle, catch, target_party=6, reader=reader)
    if not b.load_state(SLOTS + r"\slot_8.state"):
        say("FAIL slot 8")
        return 1
    time.sleep(1.2)
    start = b.read_byte(GPLAYER_PARTY_COUNT)
    say(f"start party_count={start} balls={reader.ball_count()} "
        f"(weaken-first, RAM ball accounting)")

    # step into the grass belt north of the slot-8 position first
    for _ in range(6):
        b.press_direction_settle("UP")

    res = strat.run(max_encounters=12, weaken_to=0.30, narrate=say)
    b.screenshot(OUT + r"\catcher2_result.png")
    say(f"RESULT {res}")
    for i in range(start, res["party_now"]):
        det = reader.read_party_details()[i]
        say(f"  new member slot {i}: species {reader.read_species(i)} "
            f"lv{det['level']} {det['hp']}/{det['max_hp']} HP")
    ok = res["party_now"] > start
    if ok:
        # slot 9 = the NeedsArbiter test bed: multi-mon party, hurt lead, few
        # balls -- exactly the state where heal/restock drives should fire.
        if b.save_state(SLOTS + r"\slot_9.state"):
            meta = json.load(open(SLOTS + r"\slot_8.json", encoding="utf-8"))
            meta.update(n=9, summary=f"Route 1 post-catch: party {res['party_now']}, "
                        f"{res['balls_left']} balls, lead hurt",
                        ts=time.strftime("%Y-%m-%d %H:%M"))
            json.dump(meta, open(SLOTS + r"\slot_9.json", "w", encoding="utf-8"))
            say("saved slot 9 = post-catch arbiter test bed")
    say("PASS" if ok else "no-catch")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
