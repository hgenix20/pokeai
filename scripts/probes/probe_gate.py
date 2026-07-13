"""Diagnose the north-gate (15,3) south exit: dump the full gate grid + warps,
then try exits empirically (each warp, each approach, held pushes), reporting
exactly what fires. Uses the CURRENT live state (in the gate). stream.py OFF.
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

OUT = r"C:\Users\Sagac\AppData\Local\Temp\claude\C--Program-Files-Git\166a5709-56c5-4d9e-b14e-311acd851a68\scratchpad"


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    b = BizHawkBridge(timeout=120)
    b.wait_for_bizhawk()
    nav = Navigator(b)

    cur = nav.current_map()
    say(f"map {cur} pos {nav.vision.player_xy()}")
    b.screenshot(OUT + r"\gate.png")
    warps = nav.map_warps_full()
    say(f"warps: {[(w['x'], w['y'], (w['destGroup'], w['destMap'])) for w in warps]}")
    g = nav.vision.nav_grid()
    say(f"grid {g['w']}x{g['h']}")
    for y in range(g["h"]):
        row = ""
        for x in range(g["w"]):
            t = (x, y)
            if t == nav.vision.player_xy():
                row += "P"
            elif any((w["x"], w["y"]) == t for w in warps):
                row += "W"
            elif t in nav.vision.object_tiles():
                row += "N"
            elif t in g["walk"]:
                row += "."
            else:
                row += "#"
        say(f"  y={y:2d} {row}")

    # try the southmost warp with a direct walk-off
    w = max(warps, key=lambda t: t["y"])
    say(f"target warp ({w['x']},{w['y']}) -> ({w['destGroup']},{w['destMap']})")
    ok = nav.go_to((w["x"], w["y"] - 1), attempts=8)
    say(f"go_to above the warp -> {ok}; pos {nav.vision.player_xy()}")
    for i in range(3):
        b.press_button_held("DOWN", 32)
        time.sleep(1.0)
        say(f"  DOWN hold {i + 1}: map {nav.current_map()} pos {nav.vision.player_xy()}")
        if nav.current_map() != cur:
            say("EXITED")
            b.screenshot(OUT + r"\gate_after.png")
            return 0
    b.screenshot(OUT + r"\gate_stuck.png")
    return 2


if __name__ == "__main__":
    sys.exit(main())
