"""Trace the ACTUAL 1F house-exit trajectory tile-by-tile to see where the sprite
bumps/circles (the [Fix] is still visibly ugly even though leave_building
succeeds). Loads slot 0 (bedroom), stairs to 1F, then wraps every movement call
so we log (direction, before, after) for the whole leave_building — revealing the
path, dud warp attempts, and any backtracking. Read-only diagnosis: fixes come
after we can SEE it."""
from __future__ import annotations

import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.perception.navigator import Navigator
from pokeai.agents.firered_story import vision_ascii

SLOT0 = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai\states\slots\slot_0.state"
OUT = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai\states\bizhawk"


def main() -> int:
    b = BizHawkBridge(timeout=60)
    b.wait_for_bizhawk()
    print("connected:", b.ping(), flush=True)
    nav = Navigator(b)

    for _ in range(5):
        b.load_state(SLOT0)
        time.sleep(1.2)
        if b.player_xy() != (0, 0):
            break
    print(f"bedroom: map={nav.current_map()} pos={nav.vision.player_xy()}", flush=True)

    # 2F -> 1F
    warps = nav.map_warps()
    if warps:
        nav.take_warp(warps[0])
    time.sleep(0.6)
    f1 = nav.current_map()
    print(f"\n=== ON 1F: map={f1} pos={nav.vision.player_xy()} ===", flush=True)

    # full warp table + which are exit doors
    print("all warps (full):", flush=True)
    for w in nav.map_warps_full():
        tag = "EXIT-DOOR" if w["destGroup"] != f1[0] else "internal"
        print(f"   ({w['x']},{w['y']}) -> grp{w['destGroup']}/map{w['destMap']}  [{tag}]", flush=True)
    print("collision grid (# wall . floor P player W warp N npc):", flush=True)
    for row in vision_ascii(nav.vision, nav):
        print("   " + row, flush=True)

    # instrument every movement so we SEE the trajectory
    trace = []
    orig_pds = b.press_direction_settle
    orig_pbh = b.press_button_held

    def traced_pds(d, *a, **k):
        before = nav.vision.player_xy()
        r = orig_pds(d, *a, **k)
        after = nav.vision.player_xy()
        trace.append(("settle", d, before, after))
        return r

    def traced_pbh(d, frames=16, *a, **k):
        before = nav.vision.player_xy()
        m0 = nav.current_map()
        r = orig_pbh(d, frames, *a, **k)
        time.sleep(0.2)
        after = nav.vision.player_xy()
        warped = nav.current_map() != m0
        trace.append(("held", d, before, after if not warped else "WARP->" + str(nav.current_map())))
        return r

    b.press_direction_settle = traced_pds
    b.press_button_held = traced_pbh

    print("\n=== leave_building() trajectory ===", flush=True)
    result = nav.leave_building()
    for i, step in enumerate(trace):
        print(f"   {i:2d}. {step[0]:6s} {step[1]:5s} {step[2]} -> {step[3]}", flush=True)
    print(f"\nleave_building -> {result}  final map={nav.current_map()} "
          f"pos={nav.vision.player_xy()}  ({len(trace)} movement calls)", flush=True)
    b.screenshot(OUT + r"\door_trace_end.png")
    b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
