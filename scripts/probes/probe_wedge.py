"""Diagnose the (12,27) Route-1 travel wedge: dump the nav grid around the
player, the planned first steps, and what actually happens on each direction
press. Uses the CURRENT live state (no slot load). stream.py STOPPED.
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
from pokeai.skills.battle import Battle

OUT = r"C:\Users\Sagac\AppData\Local\Temp\claude\C--Program-Files-Git\166a5709-56c5-4d9e-b14e-311acd851a68\scratchpad"


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    b = BizHawkBridge(timeout=120)
    b.wait_for_bizhawk()
    nav = Navigator(b)
    battle = Battle(b)

    say(f"map {nav.current_map()} pos {nav.vision.player_xy()} "
        f"battle.active={battle.active()}")
    b.screenshot(OUT + r"\wedge.png")

    g = nav.vision.nav_grid()
    px, py = nav.vision.player_xy()
    npcs = nav.vision.object_tiles()
    say(f"npcs: {sorted(npcs)}")
    say("local grid (7x7 around player; #=wall .=walk g=grass L=ledge N=npc P=me):")
    for y in range(py - 3, py + 4):
        row = ""
        for x in range(px - 3, px + 4):
            t = (x, y)
            if t == (px, py):
                row += "P"
            elif t in npcs:
                row += "N"
            elif t in g["ledge"]:
                row += "L"
            elif t in g["grass"]:
                row += "g"
            elif t in g["walk"]:
                row += "."
            else:
                row += "#"
        say(f"  y={y:2d}  {row}")
    say(f"ledge_dir near: { {k: v for k, v in g['ledge_dir'].items() if abs(k[0]-px) <= 3 and abs(k[1]-py) <= 3} }")

    path = nav.plan((px, 0))
    say(f"plan to ({px},0): {path[:10] if path else None}... ({len(path) if path else 0} steps)")

    for d in ("UP", "LEFT", "RIGHT", "DOWN"):
        p0 = nav.vision.player_xy()
        moved = b.press_direction_settle(d)
        p1 = nav.vision.player_xy()
        say(f"press {d}: settle={moved} {p0} -> {p1}")
        if p1 != p0:
            # step back to keep the wedge state for a second look
            back = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}[d]
            b.press_direction_settle(back)
    b.screenshot(OUT + r"\wedge_after.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
