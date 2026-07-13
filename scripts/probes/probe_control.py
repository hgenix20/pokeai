"""Find the RAM 'player can move' signal: the player ObjectEvent (0x02036E38)
flags u32 has a `frozen` bit (set by scripts during cutscenes/dialogue, cleared
when control returns). Press A to advance Oak's dialogue and watch the flags change
from frozen (locked) to free (the 'choose a Pokémon' control point)."""
from __future__ import annotations

import time

from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.emulator.firered_state_reader import FireRedStateReader
from pokeai.perception.navigator import Navigator

PLAYER_OBJ = 0x02036E38


def main() -> int:
    b = BizHawkBridge(timeout=60)
    print("waiting for ai_bridge…", flush=True)
    b.wait_for_bizhawk()
    print("connected:", b.ping(), flush=True)
    nav = Navigator(b)
    reader = FireRedStateReader(b)

    def snap():
        f = b.read_u32(PLAYER_OBJ)
        bits = {n: (f >> n) & 1 for n in (0, 6, 7, 8, 9, 10)}
        return (f"flags=0x{f:08x} bit8(frozen)={bits[8]} bit9={bits[9]} "
                f"bit6={bits[6]} bit7={bits[7]} party={reader.read().party_count} "
                f"map={nav.current_map()} pos={nav.vision.player_xy()}")

    print("initial:", snap(), flush=True)
    for i in range(12):
        b.tap("A", 6)
        time.sleep(0.8)
        print(f"after A #{i}:", snap(), flush=True)
    b.screenshot(r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai\states\bizhawk\probe_control.png")
    b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
