"""G5 ACCEPTANCE (final): the Field Brain economy loop, live, from slot 9.

Slot 9 = Route 1 post-catch (party ~3, lead fainted or hurt, ~2-3 balls). The
NeedsArbiter should sequence the drives on its own:

    survive        -> travel to Viridian, heal at the Center (RAM: party full)
    restock_balls  -> Viridian Mart, buy Poke Balls (RAM: money+bag delta)
    fill_party     -> travel to Route 1, weaken-first catching
    ... repeating as needs fire ...
    complete       -> party_count >= 6 and party_hp_fraction >= 0.85

PASS == FieldBrain returns 'complete' AND party count is 6 by RAM. Saves the
finished state to slot 9 (the G7 starting roster). stream.py STOPPED.
"""
from __future__ import annotations

import json
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from pokeai.agents.field_brain import build_fill6_brain
from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.emulator.firered_state_reader import FireRedStateReader
from pokeai.perception.navigator import Navigator
from pokeai.skills.battle import Battle
from pokeai.skills.catch import Catch
from pokeai.skills.overworld import Overworld
from pokeai.skills.services import Services
from pokeai.strategies.catcher import CatcherStrategy

SLOTS = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai\states\slots"
OUT = r"C:\Users\Sagac\AppData\Local\Temp\claude\C--Program-Files-Git\166a5709-56c5-4d9e-b14e-311acd851a68\scratchpad"


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    b = BizHawkBridge(timeout=180)
    b.wait_for_bizhawk()
    reader = FireRedStateReader(b)
    nav = Navigator(b)
    ow = Overworld(b, nav, reader)
    battle = Battle(b)
    catch = Catch(b, battle)
    services = Services(b, nav, ow, reader)
    catcher = CatcherStrategy(b, nav, battle, catch, target_party=6, reader=reader)

    if not b.load_state(SLOTS + r"\slot_9.state"):
        say("FAIL slot 9 load")
        return 1
    time.sleep(1.2)
    d0 = reader.read_party_details()
    say(f"start: map {nav.current_map()} party {len(d0)} "
        f"hp {[(m['hp'], m['max_hp']) for m in d0]} "
        f"balls {reader.ball_count()} money {reader.read_money()}")

    def on_decision(d, ctx):
        say(f"DRIVE={d.drive} goal={d.goal} critical={d.critical} | "
            f"party {ctx['party_count']} hp {ctx['party_hp_fraction']:.2f} "
            f"fainted {ctx['fainted_count']} balls {ctx['ball_count']} "
            f"money {ctx['money']}")

    brain = build_fill6_brain(b, nav, battle, catch, services, reader, catcher,
                              narrate=say, on_decision=on_decision)
    res = brain.run(max_cycles=20)
    b.screenshot(OUT + r"\field_run_result.png")

    d1 = reader.read_party_details()
    say(f"END status={res['status']} cycles={res['cycles']}")
    for drive, goal, outcome in res["history"]:
        say(f"  {drive} -> {goal}: {outcome}")
    say(f"party {len(d1)} hp {[(m['hp'], m['max_hp']) for m in d1]} "
        f"balls {reader.ball_count()} money {reader.read_money()}")
    for i in range(len(d1)):
        say(f"  slot {i}: species {reader.read_species(i)} lv{d1[i]['level']}")

    ok = res["status"] == "complete" and len(d1) >= 6
    if ok and b.save_state(SLOTS + r"\slot_9.state"):
        meta = json.load(open(SLOTS + r"\slot_9.json", encoding="utf-8"))
        meta.update(summary="Route 1/Viridian: FULL PARTY OF 6 (field brain loop)",
                    ts=time.strftime("%Y-%m-%d %H:%M"))
        json.dump(meta, open(SLOTS + r"\slot_9.json", "w", encoding="utf-8"))
        say("saved slot 9 = full party of 6")
    say("PASS" if ok else "FAIL")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
