"""Read the live 1F (Player's house) state to debug the house-exit door warp:
current map, player tile, every warp + its destination, NPCs, and the collision
grid. Run with the dashboard (stream.py) stopped; the ai_bridge keepalive will
reconnect to this within ~8s.
"""
from __future__ import annotations

from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.perception.navigator import Navigator

OUT = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai\states\bizhawk\probe_1f.png"


def main() -> int:
    b = BizHawkBridge(timeout=60)
    print("waiting for ai_bridge (keepalive should reconnect ~8s)…", flush=True)
    b.wait_for_bizhawk()
    print("connected. ping:", b.ping(), flush=True)
    nav = Navigator(b)
    px, py = nav.vision.player_xy()
    print(f"current_map = {nav.current_map()}   player tile = ({px},{py})")
    warps = nav.map_warps_full()
    print("warps:")
    for w in warps:
        print(f"  ({w['x']},{w['y']}) -> group {w['destGroup']} map {w['destMap']}")
    objs = nav.vision.object_tiles()
    print("NPCs/objects:", objs)
    w_, h_, m = nav.vision.layout()
    wset = {(x["x"], x["y"]) for x in warps}
    print(f"map {w_}x{h_}  (# wall  . floor  P player  W warp  N npc):")
    for y in range(h_):
        row = ""
        for x in range(w_):
            if (x, y) == (px, py):
                row += "P"
            elif (x, y) in wset:
                row += "W"
            elif (x, y) in objs:
                row += "N"
            else:
                row += "#" if (nav.vision.block_at(x, y, (w_, h_, m)) >> 10) & 3 else "."
        print("  " + row)
    b.screenshot(OUT)
    print("screenshot:", OUT)
    b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
