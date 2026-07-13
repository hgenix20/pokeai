"""Probe the B2F (31,11) ladder that has failed every take tonight.

Screenshot-first: where is the player, where is the ladder, what does a
single-step approach + step-in actually do?
"""
from __future__ import annotations

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.perception.navigator import Navigator
from pokeai.skills.overworld import Overworld
from pokeai.emulator.firered_state_reader import FireRedStateReader

OUT = r"C:\pokeai-states\probe_b2f"


def say(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    b = BizHawkBridge(timeout=60)
    b.wait_for_bizhawk()
    reader = FireRedStateReader(b)
    nav = Navigator(b)

    m = nav.current_map()
    pos = nav.vision.player_xy()
    say(f"map {m} pos {pos}")
    b.screenshot(OUT + r"\start.png")

    for w in nav.map_warps_full():
        say(f"warp ({w['x']},{w['y']}) -> ({w['destGroup']},{w['destMap']})")

    grid = nav.vision.nav_grid()
    walk = grid["walk"]
    px, py = pos
    say("neighborhood of (31,11): walkable flags")
    for y in range(8, 15):
        row = ""
        for x in range(27, 36):
            row += "P" if (x, y) == (px, py) else (
                "." if (x, y) in walk else "#")
        say(f"  y{y:2d} {row}")

    # single steps toward the ladder, screenshot each
    say("=== walking to (31,12) then stepping UP into (31,11) ===")
    path = nav.plan((31, 12))
    say(f"plan to (31,12): {path if path is None else len(path)} steps")
    if path is None:
        for nb in ((30, 11), (32, 11), (31, 10)):
            p2 = nav.plan(nb)
            say(f"plan to {nb}: {p2 if p2 is None else len(p2)} steps")
        b.screenshot(OUT + r"\no_path.png")
        return 1
    ok = nav.go_to((31, 12), attempts=10)
    say(f"go_to (31,12): {ok}; pos {nav.vision.player_xy()}")
    b.screenshot(OUT + r"\at_neighbor.png")
    if not ok:
        return 1
    before = nav.current_map()
    b.press_button_held("UP", 32)
    time.sleep(1.5)
    say(f"after UP: map {nav.current_map()} pos {nav.vision.player_xy()}")
    b.screenshot(OUT + r"\after_up.png")
    if nav.current_map() != before:
        say("LADDER TOOK - it works with a plain held UP")
    return 0


if __name__ == "__main__":
    sys.exit(main())
