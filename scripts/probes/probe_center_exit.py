"""Diagnose leave_building failing inside the Viridian Pokemon Center (5,4).
Dump warps/grid/pos, try leave_building with timing, then manual exit paths.
Uses the CURRENT live state. stream.py STOPPED.
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

    say(f"map {nav.current_map()} pos {nav.vision.player_xy()}")
    b.screenshot(OUT + r"\center_exit.png")
    warps = nav.map_warps_full()
    say(f"warps: {[(w['x'], w['y'], (w['destGroup'], w['destMap'])) for w in warps]}")
    g = nav.vision.nav_grid()
    say(f"grid {g['w']}x{g['h']}")
    px, py = nav.vision.player_xy()
    for y in range(max(0, py - 2), min(g['h'], py + 5)):
        row = ""
        for x in range(max(0, px - 5), min(g['w'], px + 6)):
            t = (x, y)
            if t == (px, py):
                row += "P"
            elif t in nav.vision.object_tiles():
                row += "N"
            elif any((w["x"], w["y"]) == t for w in warps):
                row += "W"
            elif t in g["walk"]:
                row += "."
            else:
                row += "#"
        say(f"  y={y:2d}  {row}")

    t0 = time.time()
    res = nav.leave_building()
    say(f"leave_building -> {res} in {time.time() - t0:.1f}s; "
        f"now map {nav.current_map()} pos {nav.vision.player_xy()}")
    if nav.current_map() != (5, 4):
        say("EXITED OK")
        b.screenshot(OUT + r"\center_exit_after.png")
        return 0

    # manual: go to each warp tile's ABOVE neighbour and hold DOWN
    for w in warps:
        wx, wy = w["x"], w["y"]
        say(f"manual attempt: warp ({wx},{wy}) from above")
        nav.go_to((wx, wy - 1), attempts=6)
        say(f"  at {nav.vision.player_xy()}")
        b.press_button_held("DOWN", 32)
        time.sleep(1.2)
        say(f"  after hold-DOWN: map {nav.current_map()} pos {nav.vision.player_xy()}")
        if nav.current_map() != (5, 4):
            say("MANUAL EXIT OK")
            b.screenshot(OUT + r"\center_exit_after.png")
            return 0
    b.screenshot(OUT + r"\center_exit_fail.png")
    return 2


if __name__ == "__main__":
    sys.exit(main())
