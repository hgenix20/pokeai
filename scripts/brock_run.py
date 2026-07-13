"""G8 ACCEPTANCE: beat Brock — Boulder Badge verified by the RAM flag.

From slot 3 (Pewter, party leveled by the grind): buy potions at the Pewter
Mart (cookie-cutter interior: stand (4,3) face LEFT; Potion assumed at list
slot 1 and verified by the bag delta), enter the gym (interior (6,2)), walk
the aisle north (the gym trainer's sight line fires - fight_smart), then
Brock (Geodude lv12 + Onix lv14): fight_smart with potions.

PASS = FLAG_BADGE01 (0x820) SET + badge_count == 1 (+ payout money delta
logged). Saves slot 2 = "Boulder Badge" (slot 2's post-rival checkpoint is
long superseded). stream.py STOPPED.
"""
from __future__ import annotations

import json
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.emulator.firered_state_reader import ITEM_POTION, FireRedStateReader
from pokeai.perception.navigator import Navigator
from pokeai.skills.battle import Battle
from pokeai.skills.catch import Catch
from pokeai.skills.overworld import Overworld
from pokeai.skills.services import MARTS, Services

SLOTS = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai\states\slots"
OUT = r"C:\Users\Sagac\AppData\Local\Temp\claude\C--Program-Files-Git\166a5709-56c5-4d9e-b14e-311acd851a68\scratchpad"
PEWTER = (3, 2)
GYM = (6, 2)
FLAG_BADGE01 = 0x820


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def fail(b, msg, shot):
    say(f"FAIL: {msg}")
    try:
        b.screenshot(OUT + rf"\{shot}.png")
    except Exception:
        pass
    return 1


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

    if "--resume" not in sys.argv:
        if not b.load_state(SLOTS + r"\slot_3.state"):
            return fail(b, "slot 3 load", "br_load")
        time.sleep(1.2)
    d = reader.read_party_details()
    say(f"start map {nav.current_map()} levels {[m['level'] for m in d]} "
        f"money {reader.read_money()} potions {reader.count_heal_items()} "
        f"badge01 {reader.read_flag(FLAG_BADGE01)}")
    if reader.read_flag(FLAG_BADGE01):
        say("badge already earned?!")
        return 0

    # make sure we're outside in Pewter
    while nav.current_map()[0] not in (3,):
        if nav.leave_building() is None:
            for _ in range(8):
                p0 = b.player_xy()
                b.press_direction_settle("DOWN")
                if b.player_xy() != p0:
                    break
                b.tap("B", 5)
                time.sleep(0.4)
    if nav.current_map() != PEWTER:
        return fail(b, f"not in Pewter: {nav.current_map()}", "br_city")

    # --- potions from the Pewter Mart (discover the door once) ---
    if reader.count_heal_items() < 3 and reader.read_money() >= 900:
        say("finding the Pewter Mart for potions…")
        mart_row = None
        for w in nav.map_warps_full():
            dest = (w["destGroup"], w["destMap"])
            if dest in ((6, 0), (6, 2), (6, 5)):   # museum/gym/center: skip
                continue
            if not nav.go_to((w["x"], w["y"] + 1), attempts=8):
                continue
            if nav.take_warp((w["x"], w["y"])) is None:
                b.press_button_held("UP", 32)
                time.sleep(1.0)
            if nav.current_map() == PEWTER:
                continue
            interior = nav.current_map()
            ow.wait_control(10)
            npcs = sorted(nav.vision.object_tiles())
            g = nav.vision.nav_grid()
            say(f"  interior {interior} {g['w']}x{g['h']} npcs {npcs}")
            if any(t[0] <= 3 for t in npcs) and g["w"] <= 16:
                # west-counter clerk = mart signature (cookie-cutter layout)
                mart_row = {"map": interior, "door": (w["x"], w["y"]),
                            "clerk": (2, 3), "stand": (4, 3), "face": "LEFT"}
                MARTS[PEWTER] = mart_row
                say(f"  MART row: {PEWTER}: {mart_row}")
                res = svc.buy_at_mart(qty=5, slot=1, city_map=PEWTER)
                say(f"  buy potions -> {res}")
                if res.get("item_deltas", {}).get(ITEM_POTION, 0) <= 0:
                    say("  slot 1 was not Potion; trying slot 0")
                    res = svc.buy_at_mart(qty=3, slot=0, city_map=PEWTER)
                    say(f"  retry -> {res}")
            nav.leave_building()
            ow.wait_control(10)
            if mart_row:
                break
        say(f"potions now {reader.count_heal_items()} money {reader.read_money()}")

    # --- into the gym ---
    say("entering the gym…")
    gymdoors = [w for w in nav.map_warps_full()
                if (w["destGroup"], w["destMap"]) == GYM]
    if not gymdoors:
        return fail(b, "no gym door found", "br_nogym")
    w = gymdoors[0]
    nav.go_to((w["x"], w["y"] + 1), attempts=8)
    if nav.take_warp((w["x"], w["y"])) != GYM:
        b.press_button_held("UP", 32)
        time.sleep(1.0)
    if nav.current_map() != GYM:
        return fail(b, f"could not enter the gym: {nav.current_map()}", "br_enter")
    ow.wait_control(10)
    say(f"in the gym at {nav.vision.player_xy()}; npcs {sorted(nav.vision.object_tiles())}")

    # --- walk the aisle north; fight whoever engages; then Brock ---
    wins = 0
    deadline = time.time() + 1500
    while time.time() < deadline:
        if reader.read_flag(FLAG_BADGE01):
            break
        if reader.read().all_party_fainted:
            say("BLACKOUT in the gym - riding out + walking back")
            battle.ride_out_end(button="A", cap=80)
            # respawn at the Center: heal is implicit; walk back to the gym
            gymdoors = [w2 for w2 in nav.map_warps_full()
                        if (w2["destGroup"], w2["destMap"]) == GYM]
            if gymdoors:
                w2 = gymdoors[0]
                nav.go_to((w2["x"], w2["y"] + 1), attempts=10)
                if nav.take_warp((w2["x"], w2["y"])) != GYM:
                    b.press_button_held("UP", 32)
                    time.sleep(1.0)
            continue
        if battle.active() and catch.confirm_real_battle():
            res = battle.fight_smart(narrate=say, turn_cap=60)
            say(f"gym battle -> {res}")
            if res == "win":
                wins += 1
            continue
        if nav.current_map() != GYM:
            # got bounced outside somehow: re-enter
            gymdoors = [w2 for w2 in nav.map_warps_full()
                        if (w2["destGroup"], w2["destMap"]) == GYM]
            if gymdoors:
                w2 = gymdoors[0]
                nav.go_to((w2["x"], w2["y"] + 1), attempts=10)
                nav.take_warp((w2["x"], w2["y"]))
            continue
        # move north toward Brock; interact when adjacent to the top NPC
        npcs = sorted(nav.vision.object_tiles(), key=lambda t: t[1])
        if npcs:
            brock = npcs[0]
            px, py = nav.vision.player_xy()
            if abs(px - brock[0]) + abs(py - brock[1]) <= 2:
                say(f"challenging the leader at {brock}…")
                ow.interact(brock, rounds=4)
                time.sleep(1.0)
                continue
            nav.go_to((brock[0], brock[1] + 2), attempts=8)
        else:
            p0 = b.player_xy()
            b.press_direction_settle("UP")
            if b.player_xy() == p0:
                b.tap("A", 6)
                time.sleep(0.4)
    else:
        return fail(b, "gym deadline hit without the badge", "br_cap")

    badge = reader.read_flag(FLAG_BADGE01)
    s = reader.read()
    say(f"badge01 {badge}  badges {s.badge_count}  money {s.money}")
    b.screenshot(OUT + r"\brock_done.png")
    if not badge:
        return fail(b, "badge flag not set", "br_flag")
    if b.save_state(SLOTS + r"\slot_2.state"):
        meta = json.load(open(SLOTS + r"\slot_3.json", encoding="utf-8"))
        meta.update(n=2, summary="BOULDER BADGE earned (Brock beaten)",
                    ts=time.strftime("%Y-%m-%d %H:%M"))
        json.dump(meta, open(SLOTS + r"\slot_2.json", "w", encoding="utf-8"))
        say("saved slot 2 = Boulder Badge")
    say(f"PASS - BOULDER BADGE (gym wins {wins})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
