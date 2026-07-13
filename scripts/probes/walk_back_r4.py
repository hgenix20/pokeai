"""Walk back from Pewter to the Route 4 Center, heal, save slot 7.
(The purchase half of repel_trip.py was completed by hand 2026-07-06:
5 Repels, 3 Potions, 2 replacement Poke Balls, all bag-verified.)"""
from __future__ import annotations

import json
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.emulator.firered_state_reader import FireRedStateReader
from pokeai.perception.navigator import Navigator
from pokeai.skills.battle import Battle
from pokeai.skills.catch import Catch
from pokeai.skills.journey import WildPolicy, cross_edge, leave_building_safe
from pokeai.skills.overworld import Overworld
from pokeai.skills.services import Services

SLOTS = r"C:\pokeai-states\slots"
PEWTER = (3, 2)
ROUTE3 = (3, 21)
ROUTE4 = (3, 22)


def say(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    b = BizHawkBridge(timeout=300)
    say("waiting for ai_bridge…")
    b.wait_for_bizhawk()
    reader = FireRedStateReader(b)
    nav = Navigator(b)
    ow = Overworld(b, nav, reader)
    battle = Battle(b, reader)
    catch = Catch(b, battle)
    svc = Services(b, nav, ow, reader)
    policy = WildPolicy(b, battle, catch, narrate=say)

    say(f"start map {nav.current_map()} pos {nav.vision.player_xy()} "
        f"money {reader.read_money()} repels {reader.count_item(86)}")

    while nav.current_map()[0] not in (3,):
        leave_building_safe(b, nav)
    for leg in range(14):
        m = nav.current_map()
        if m == ROUTE4:
            break
        d = "EAST" if leg % 2 == 0 else "NORTH"
        say(f"return leg {leg + 1}: crossing {d} from "
            f"{nav.vision.player_xy()} on {m}")
        cross_edge(b, nav, ow, reader, policy, None, d, budget=300, narrate=say)
    if nav.current_map() != ROUTE4:
        say(f"FAIL: did not reach Route 4: {nav.current_map()}")
        return 1
    say("ROUTE 4 west reached - healing at the Center")
    svc.heal_at_center(ROUTE4)
    while nav.current_map() != ROUTE4:
        leave_building_safe(b, nav)
    s = reader.read()
    if b.save_state(SLOTS + r"\slot_7.state"):
        meta = json.load(open(SLOTS + r"\slot_2.json", encoding="utf-8"))
        meta.update(n=7, summary="Route 4 Center (repels+potions)",
                    ts=time.strftime("%Y-%m-%d %H:%M"))
        json.dump(meta, open(SLOTS + r"\slot_7.json", "w", encoding="utf-8"))
        say("saved slot 7 = Route 4 Center (repels+potions)")
    say(f"PASS - repels {reader.count_item(86)}, potions "
        f"{reader.count_item(13)}, money {reader.read_money()}, "
        f"hp {s.party_total_hp}/{s.party_total_max_hp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
