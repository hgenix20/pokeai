"""G5 catching, step 1: from slot 6 (post-delivery, 5 Poke Balls) reach Route 1
grass, save slot 8 (Route 1 WITH balls) as the catch-iteration checkpoint, then
trigger a wild battle and screenshot the battle menu + open the BAG so we can
map the FireRed in-battle bag layout (old Red 0xCC36 is obsolete). stream.py
STOPPED. Run once; then iterate catch attempts cheaply from slot 8.
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
from pokeai.emulator.firered_state_reader import FireRedStateReader
from pokeai.perception.navigator import Navigator
from pokeai.skills.battle import Battle
from pokeai.skills.navigate_to import NavigateTo
from pokeai.skills.overworld import Overworld

SLOTS = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai\states\slots"
OUT = r"C:\Users\Sagac\AppData\Local\Temp\claude\C--Program-Files-Git\0ce068f5-fdaf-4e80-b3d3-05f89c188438\scratchpad"
PALLET, ROUTE1 = (3, 0), (3, 19)


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    b = BizHawkBridge(timeout=180)
    say("waiting for ai_bridge…")
    b.wait_for_bizhawk()
    reader = FireRedStateReader(b)
    nav = Navigator(b)
    ow = Overworld(b, nav, reader)
    skill = NavigateTo(b, nav)
    battle = Battle(b)

    if not b.load_state(SLOTS + r"\slot_6.state"):
        say("FAIL: slot 6 load")
        return 1
    time.sleep(1.2)
    say(f"start {nav.current_map()} pos {nav.vision.player_xy()}")

    # leave Oak's lab -> Pallet
    if nav.current_map() != PALLET:
        nav.leave_building()
        ow.wait_control(12)
    say(f"in Pallet: {nav.current_map()} pos {nav.vision.player_xy()}")

    # north across Pallet into Route 1
    for _ in range(8):
        if nav.current_map() == ROUTE1:
            break
        skill.overworld_exit("north")
        ow.wait_control(8)
    if nav.current_map() != ROUTE1:
        say(f"FAIL: not on Route 1 (map {nav.current_map()})")
        b.screenshot(OUT + r"\catch_setup_stuck.png")
        return 1
    say(f"on Route 1: {nav.current_map()} pos {nav.vision.player_xy()}")

    # checkpoint: Route 1 with balls
    if b.save_state(SLOTS + r"\slot_8.state"):
        m = json.load(open(SLOTS + r"\slot_6.json", encoding="utf-8"))
        m.update(n=8, summary="Route 1 with 5 Poke Balls (catch checkpoint)",
                 ts=time.strftime("%Y-%m-%d %H:%M"))
        json.dump(m, open(SLOTS + r"\slot_8.json", "w", encoding="utf-8"))
        say("saved slot 8 = Route 1 with balls")

    # pace grass to trigger a wild battle
    pattern = ["LEFT", "LEFT", "UP", "DOWN", "LEFT", "RIGHT", "UP", "DOWN"]
    for step in range(40):
        if battle.active():
            break
        b.press_direction_settle(pattern[step % len(pattern)])
        time.sleep(0.05)
    if not battle.active():
        say("no wild battle in 40 grass steps")
        return 1
    lvl, hp, mx = battle.enemy_stats()
    say(f"WILD BATTLE: enemy lv{lvl} {hp}/{mx}")
    b.screenshot(OUT + r"\catch_battle_menu.png")

    # open the BAG: from the 2x2 action menu (FIGHT/BAG top, POKEMON/RUN bottom),
    # cursor defaults to FIGHT; RIGHT -> BAG, A opens it.
    b.tap("RIGHT", 6)
    time.sleep(0.4)
    b.screenshot(OUT + r"\catch_menu_bag_hover.png")
    b.tap("A", 6)
    time.sleep(0.8)
    b.screenshot(OUT + r"\catch_bag_open.png")
    say("opened bag; screenshots saved (menu, bag hover, bag open)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
