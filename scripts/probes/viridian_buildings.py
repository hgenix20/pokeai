"""G2: identify Viridian City's building interiors (which grp-5 map is the
Pokemon Center vs the Mart). Enters each front-door warp, screenshots the
interior + records its map id, then leaves. Run from slot 4, stream.py STOPPED.
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
from pokeai.skills.overworld import Overworld
from pokeai.emulator.firered_state_reader import FireRedStateReader

SLOTS = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai\states\slots"
OUT = r"C:\Users\Sagac\AppData\Local\Temp\claude\C--Program-Files-Git\0ce068f5-fdaf-4e80-b3d3-05f89c188438\scratchpad"


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    b = BizHawkBridge(timeout=180)
    b.wait_for_bizhawk()
    nav = Navigator(b)
    ow = Overworld(b, nav, FireRedStateReader(b))
    # front-door warps discovered on slot 4 (x,y): try the 4 non-gym buildings
    warps = [(25, 11), (36, 10), (25, 18), (36, 19), (26, 26)]
    for wx, wy in warps:
        if not b.load_state(SLOTS + r"\slot_4.state"):
            say("FAIL slot load")
            return 1
        time.sleep(0.8)
        city = nav.current_map()
        say(f"heading to door ({wx},{wy}) from {nav.vision.player_xy()}")
        dest = nav.take_warp((wx, wy))
        if dest is None or dest == city:
            # approach the tile from below then step up into it
            nav.go_to((wx, wy + 1))
            b.press_button_held("UP", 32)
            time.sleep(1.0)
            dest = nav.current_map()
        if dest == city:
            say(f"  door ({wx},{wy}) did not warp (skip)")
            continue
        time.sleep(0.8)
        tag = f"vbldg_{wx}_{wy}_map{dest[0]}_{dest[1]}"
        b.screenshot(OUT + f"\\{tag}.png")
        # nearest NPC = candidate nurse/clerk
        objs = nav.vision.object_tiles()
        say(f"  door ({wx},{wy}) -> map {dest}; npcs={sorted(objs)[:4]}; shot {tag}.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
