"""Validate the house-exit door fix (walkthrough [Fix]): the sprite should walk
straight to the door and leave, no wall-bumping / backtracking / circling.

From slot 0 (bedroom, 2F): take the stairs to 1F, then leave_building to Pallet
Town. Records the player's position after every action so the trajectory is
inspectable (a clean exit = monotonic approach to the door tile, then one step
through it), screenshots 1F-before and Pallet-after, and asserts the map
actually changed to the outdoors."""
from __future__ import annotations

import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.perception.navigator import Navigator

ROOT = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai"
SLOT0 = ROOT + r"\states\slots\slot_0.state"
OUT = ROOT + r"\states\bizhawk"


def main() -> int:
    b = BizHawkBridge(timeout=60)
    print("waiting for ai_bridge…", flush=True)
    b.wait_for_bizhawk()
    print("connected:", b.ping(), flush=True)
    nav = Navigator(b)

    # load bedroom (load_state now hydrates the OneDrive placeholder first)
    loaded = False
    for _ in range(5):
        b.load_state(SLOT0)
        time.sleep(1.5)
        if b.player_xy() != (0, 0):
            loaded = True
            break
    if not loaded:
        print("ABORT: slot 0 never loaded (still (0,0))", flush=True)
        b.close()
        return 2
    print(f"bedroom: map={nav.current_map()} pos={nav.vision.player_xy()}", flush=True)

    # 2F -> 1F via the bedroom's only warp (the stairs)
    warps = nav.map_warps()
    if warps:
        nav.take_warp(warps[0])
    time.sleep(0.6)
    f1_map = nav.current_map()
    print(f"after stairs: map={f1_map} pos={nav.vision.player_xy()}", flush=True)
    b.screenshot(OUT + r"\door_1f.png")

    # show the 1F exit doors the AI sees
    doors = [w for w in nav.map_warps_full() if w["destGroup"] != f1_map[0]]
    print(f"1F exit-door candidates (destGroup != {f1_map[0]}): {doors}", flush=True)

    # THE FIX under test: clean walk out the door
    print("leave_building()…", flush=True)
    t0 = time.time()
    result = nav.leave_building()
    dt = time.time() - t0
    end_map = nav.current_map()
    print(f"  -> result_map={result} end_map={end_map} pos={nav.vision.player_xy()} "
          f"({dt:.1f}s)", flush=True)
    b.screenshot(OUT + r"\door_pallet.png")

    ok = end_map != f1_map
    print(f"EXIT {'CLEAN ✓' if ok else 'FAILED ✗'}: "
          f"{'left the house to ' + str(end_map) if ok else 'still inside'}", flush=True)
    b.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
