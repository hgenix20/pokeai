"""Read-only live snapshot of the FireRed game running in BizHawk.

Connects to ai_bridge.lua (already loaded in EmuHawk), proves the link, then
prints where the player actually is right now: ROM header, map, position,
money, party, walkable neighbours, and an ASCII collision grid. Presses NOTHING
— pure observation, so it's safe to run against the live CrowdControl game.
"""
from __future__ import annotations

import sys

from pokeai.agents.firered_story import vision_ascii
from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.emulator.firered_state_reader import FireRedStateReader
from pokeai.perception.navigator import Navigator


def main() -> int:
    b = BizHawkBridge(timeout=30)
    print("listening on 127.0.0.1:51055 — waiting for ai_bridge.lua…", flush=True)
    try:
        b.wait_for_bizhawk()
    except Exception as e:
        print(f"FAIL: BizHawk never connected ({type(e).__name__}: {e})")
        return 2
    print("connected. ping:", b.ping(), flush=True)

    title = bytes(b.read_range(0x080000A0, 0x080000AC)).decode("ascii", "replace")
    code = bytes(b.read_range(0x080000AC, 0x080000B0)).decode("ascii", "replace")
    print(f"ROM: title={title!r} code={code!r}")

    nav = Navigator(b)
    reader = FireRedStateReader(b)
    vision = nav.vision
    try:
        cur = nav.current_map()
    except Exception as e:
        cur = f"<err {type(e).__name__}>"
    print(f"current_map (group,num) = {cur}")
    print(f"raw player object xy    = {b.player_xy()}")
    try:
        s = reader.read()
        print(f"map_id={s.current_map} pos=({s.x_pos},{s.y_pos}) money={s.money} "
              f"party={s.party_count} badges={s.badge_count} "
              f"hp={s.party_total_hp}/{s.party_total_max_hp}")
    except Exception as e:
        print(f"state read failed: {type(e).__name__}: {e}")
    try:
        print("walkable neighbours:", vision.walkable_neighbors())
    except Exception as e:
        print(f"walkable_neighbors failed: {type(e).__name__}: {e}")
    try:
        print("warps on this map:", nav.map_warps_full())
    except Exception as e:
        print(f"warps read failed: {type(e).__name__}: {e}")
    print("collision grid (# wall  . floor  P player  W warp  N npc):")
    for row in vision_ascii(vision, nav):
        print("    " + row)

    b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
