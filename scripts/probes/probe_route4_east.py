"""Probe the Route 4 east-exit shelf (slot 5 = just outside the Mt. Moon
east door, (3,22) x=19 y=10).

Live 2026-07-06: stage E EAST legs pinned at (21,10); the SOUTH alternation
ledge-dropped through the map seam back onto ROUTE 3 (the walkthrough says
Route 4 east is a HILL: "head east -> downhill to Cerulean"). This probe is
pure observation: dump the nav grid + ledge directions around the shelf,
then take single EAST presses with position reads + screenshots to find the
real way down/east.
"""
from __future__ import annotations

import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.perception.navigator import Navigator

OUT = r"C:\pokeai-states\probe_r4east"
SLOTS = r"C:\pokeai-states\slots"


def say(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    import os
    os.makedirs(OUT, exist_ok=True)
    b = BizHawkBridge(timeout=60)
    b.wait_for_bizhawk()
    nav = Navigator(b)

    if "--no-load" not in sys.argv:
        if not b.load_state(SLOTS + r"\slot_5.state"):
            say("slot 5 load FAILED")
            return 1
        time.sleep(1.2)
    say(f"map {nav.current_map()} pos {nav.vision.player_xy()}")

    grid = nav.vision.nav_grid()
    walk = grid["walk"]
    ledges = grid.get("ledge_dir") or {}
    px, py = nav.vision.player_xy()
    say(f"grid: {len(walk)} walkable tiles, {len(ledges)} ledge tiles, "
        f"w={grid.get('w')} h={grid.get('h')}")

    # ascii slice around the shelf: rows y 0..24, cols x 10..48
    x0, x1, y0, y1 = 10, 48, 0, 24
    say(f"slice x{x0}-{x1} y{y0}-{y1}: '.'=walk '#'=block, ledges v>^< , P=player")
    arrow = {"down": "v", "right": ">", "up": "^", "left": "<"}
    for y in range(y0, y1 + 1):
        row = ""
        for x in range(x0, x1 + 1):
            if (x, y) == (px, py):
                row += "P"
            elif (x, y) in ledges:
                row += arrow.get(str(ledges[(x, y)]).lower(), "L")
            elif (x, y) in walk:
                row += "."
            else:
                row += "#"
        say(f"  y{y:2d} {row}")

    # warps on this map
    for w in nav.map_warps_full():
        say(f"warp ({w['x']},{w['y']}) -> ({w['destGroup']},{w['destMap']})")

    # single EAST presses with verification
    say("=== single EAST presses ===")
    b.screenshot(OUT + r"\e0.png")
    for i in range(1, 16):
        before = nav.vision.player_xy()
        m_before = nav.current_map()
        b.press_direction_settle("RIGHT")
        time.sleep(0.3)
        after = nav.vision.player_xy()
        m_after = nav.current_map()
        say(f"E{i}: {before} -> {after}  map {m_before}->{m_after}")
        b.screenshot(OUT + rf"\e{i}.png")
        if m_after != m_before:
            say("MAP CHANGED - stopping")
            break
        if after == before:
            say("blocked - trying DOWN (ledge below?)")
            b.press_direction_settle("DOWN")
            time.sleep(0.3)
            after2 = nav.vision.player_xy()
            say(f"  DOWN: {after} -> {after2}  map {nav.current_map()}")
            b.screenshot(OUT + rf"\e{i}_down.png")
            if after2 == after:
                say("  DOWN also blocked - stopping for screenshot review")
                break
    say(f"final: map {nav.current_map()} pos {nav.vision.player_xy()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
