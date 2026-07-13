"""Repel shopping trip: slot 5 (Route 4 west shelf) -> Route 3 -> Pewter
Mart -> buy Repels + Potions -> back to the Route 4 Center -> heal -> slot 7.

Why: Mt. Moon's encounter density (probed 05:58-07:13: a wild every 5-8
steps, 29 battles in one 30-min approach) makes bare traversal non-viable.
CLAW lv17+ outlevels every Mt. Moon wild, so Repels make the cave silent.

Purchases are ADAPTIVE: the Pewter shop-list order is unknown, so buy one
unit per candidate slot and identify by bag delta (RAM ground truth), then
bulk-buy at the discovered slots. ITEM_REPEL=86, ITEM_POTION=13.
"""
from __future__ import annotations

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
OUT = r"C:\pokeai-states\probe_r4east"
ITEM_REPEL = 86
ITEM_POTION = 13
PEWTER = (3, 2)
ROUTE3 = (3, 21)
ROUTE4 = (3, 22)


def say(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def fail(b, msg, shot):
    say(f"FAIL: {msg}")
    try:
        b.screenshot(OUT + rf"\{shot}.png")
    except Exception:
        pass
    return 1


def main() -> int:
    import json
    import os
    os.makedirs(OUT, exist_ok=True)
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

    if "--resume" not in sys.argv:
        if not b.load_state(SLOTS + r"\slot_5.state"):
            return fail(b, "slot 5 load", "rt_load")
        time.sleep(1.2)
    say(f"start map {nav.current_map()} pos {nav.vision.player_xy()} "
        f"money {reader.read_money()}")

    # --- stage 1: Route 4 west shelf -> Route 3 (SOUTH over the seam) ---
    while nav.current_map() not in (ROUTE3, PEWTER):
        if nav.current_map()[0] not in (3,):
            leave_building_safe(b, nav)
            continue
        say(f"crossing SOUTH from {nav.vision.player_xy()} on {nav.current_map()}")
        cross_edge(b, nav, ow, reader, policy, None, "SOUTH", budget=240, narrate=say)
        if nav.current_map() == ROUTE4:
            # also try WEST: the funnel pocket sits against the west column
            cross_edge(b, nav, ow, reader, policy, None, "WEST", budget=240, narrate=say)
    say(f"ROUTE 3 reached: {nav.current_map()} {nav.vision.player_xy()}")

    # --- stage 2: Route 3 -> Pewter (WEST legs, SOUTH alternation) ---
    for leg in range(12):
        if nav.current_map() == PEWTER:
            break
        d = "WEST" if leg % 2 == 0 else "SOUTH"
        say(f"Route 3 leg {leg + 1}: crossing {d} from {nav.vision.player_xy()}")
        cross_edge(b, nav, ow, reader, policy, None, d, budget=300, narrate=say)
    if nav.current_map() != PEWTER:
        return fail(b, f"did not reach Pewter: {nav.current_map()}", "rt_pewter")
    say(f"PEWTER reached at {nav.vision.player_xy()}")

    # --- stage 3: adaptive purchases at the Mart ---
    # scan order: Repel usually sits late in FRLG shop lists
    found: dict[int, int] = {}       # item_id -> slot
    money_floor = 600                # never spend the last cushion
    for slot in (6, 5, 7, 4, 1, 2, 3, 0):
        if ITEM_REPEL in found and ITEM_POTION in found:
            break
        if reader.read_money() < money_floor:
            say("money floor reached during scan")
            break
        say(f"probe-buy 1 unit at slot {slot}…")
        r = svc.buy_at_mart(qty=1, slot=slot, city_map=PEWTER)
        say(f"  -> {r}")
        if not r.get("ok"):
            continue
        for item_id, delta in (r.get("item_deltas") or {}).items():
            if delta > 0:
                found[item_id] = slot
                say(f"  slot {slot} = item {item_id}")
        if r.get("balls_added"):
            found[4] = slot
            say(f"  slot {slot} = poke balls")
    say(f"scan result: {found}")
    if ITEM_REPEL not in found:
        return fail(b, f"no repel slot found (have {found})", "rt_norepel")

    r = svc.buy_at_mart(qty=4, slot=found[ITEM_REPEL], city_map=PEWTER)
    say(f"bulk repel buy: {r}")
    if ITEM_POTION in found and reader.read_money() >= 4 * 300 + money_floor:
        r = svc.buy_at_mart(qty=4, slot=found[ITEM_POTION], city_map=PEWTER)
        say(f"bulk potion buy: {r}")
    items = dict(reader.read_bag_pocket("items"))
    say(f"items pocket now: {items}; money {reader.read_money()}")
    if items.get(ITEM_REPEL, 0) < 3:
        return fail(b, f"repel count too low: {items}", "rt_low")

    # --- stage 4: back out and east to the Route 4 Center ---
    leave_building_safe(b, nav)
    for leg in range(12):
        if nav.current_map() == ROUTE4:
            break
        d = "EAST" if leg % 2 == 0 else "NORTH"
        say(f"return leg {leg + 1}: crossing {d} from "
            f"{nav.vision.player_xy()} on {nav.current_map()}")
        cross_edge(b, nav, ow, reader, policy, None, d, budget=300, narrate=say)
    if nav.current_map() != ROUTE4:
        return fail(b, f"did not reach Route 4: {nav.current_map()}", "rt_back")
    say("ROUTE 4 west reached - healing at the Center")
    if not svc.heal_at_center(ROUTE4):
        say("heal failed (continuing - party may be healthy enough)")

    while nav.current_map() != ROUTE4:
        leave_building_safe(b, nav)
    s = reader.read()
    if b.save_state(SLOTS + r"\slot_7.state"):
        meta = json.load(open(SLOTS + r"\slot_2.json", encoding="utf-8"))
        meta.update(n=7, summary="Route 4 Center (repels+potions)",
                    ts=time.strftime("%Y-%m-%d %H:%M"))
        json.dump(meta, open(SLOTS + r"\slot_7.json", "w", encoding="utf-8"))
        say("saved slot 7 = Route 4 Center (repels+potions)")
    say(f"PASS - repels {items.get(ITEM_REPEL, 0)}, potions "
        f"{items.get(ITEM_POTION, 0)}, money {reader.read_money()}, "
        f"hp {s.party_total_hp}/{s.party_total_max_hp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
