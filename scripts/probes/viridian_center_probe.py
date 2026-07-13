"""Confirm the Viridian Pokemon Center: the FRLG reference map shows the red-roof
P.C. at the city's bottom-center = door (26,26) -> interior (5,4), which the 7/3
session mis-labeled "HOUSE (TV)". Enter it, dump the interior + NPCs, find the
nurse, counter-talk heal, and print the CENTERS row. From slot 5. stream.py OFF.
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
from pokeai.skills.overworld import Overworld
from pokeai.skills.services import Services

SLOTS = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai\states\slots"
OUT = r"C:\Users\Sagac\AppData\Local\Temp\claude\C--Program-Files-Git\166a5709-56c5-4d9e-b14e-311acd851a68\scratchpad"
DOOR = (26, 26)


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    b = BizHawkBridge(timeout=180)
    b.wait_for_bizhawk()
    reader = FireRedStateReader(b)
    nav = Navigator(b)
    ow = Overworld(b, nav, reader)
    svc = Services(b, nav, ow, reader)

    if not b.load_state(SLOTS + r"\slot_5.state"):
        say("FAIL slot load")
        return 1
    time.sleep(1.0)
    s0 = reader.read()
    say(f"start map {nav.current_map()} pos {nav.vision.player_xy()} "
        f"HP {s0.party_total_hp}/{s0.party_total_max_hp}")

    say(f"entering door {DOOR}…")
    if not nav.go_to((DOOR[0], DOOR[1] + 1)):
        say("FAIL: can't reach the door")
        return 1
    if nav.take_warp(DOOR) is None:
        b.press_button_held("UP", 32)
        time.sleep(1.0)
    interior = nav.current_map()
    if interior == (3, 1):
        say("FAIL: did not enter")
        return 1
    ow.wait_control(10)
    grid = nav.vision.nav_grid()
    npcs = sorted(nav.vision.object_tiles())
    say(f"interior map {interior} size {grid['w']}x{grid['h']} npcs {npcs}")
    b.screenshot(OUT + r"\vc_interior.png")

    cx = grid["w"] // 2
    nurse = min(npcs, key=lambda t: (t[1], abs(t[0] - cx))) if npcs else None
    if not nurse:
        say("FAIL: no NPCs found")
        return 1
    stand = (nurse[0], nurse[1] + 2)
    say(f"nurse guess {nurse} stand {stand} walkable={nav.vision.walkable(*stand)}")
    healed = svc.heal_here(nurse, stand=stand)
    s1 = reader.read()
    say(f"heal_here -> {healed} (HP {s1.party_total_hp}/{s1.party_total_max_hp})")
    b.screenshot(OUT + r"\vc_heal.png")

    if healed:
        say(f'CENTERS row: (3, 1): {{"map": {interior}, "door": {DOOR}, '
            f'"nurse": {nurse}, "stand": {stand}}}')
        say("PASS")
        return 0
    say("heal not confirmed — check vc_interior.png / vc_heal.png")
    return 2


if __name__ == "__main__":
    sys.exit(main())
