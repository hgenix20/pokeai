"""From Pallet Town, walk north into the Oak-intercept trigger and ride out the
cutscene, to verify the reusable walk_until_event + ride_cutscene skills."""
from __future__ import annotations

from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.emulator.firered_state_reader import FireRedStateReader
from pokeai.perception.navigator import Navigator
from pokeai.skills.overworld import Overworld

OUT = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai\states\bizhawk"


def main() -> int:
    b = BizHawkBridge(timeout=60)
    print("waiting for ai_bridge…", flush=True)
    b.wait_for_bizhawk()
    print("connected:", b.ping(), flush=True)
    nav = Navigator(b)
    ow = Overworld(b, nav, Navigator and FireRedStateReader(b))
    print(f"start: map={nav.current_map()} pos={ow.pos()}")
    print("walking north until the game interrupts…", flush=True)
    r = ow.walk_until_event("UP", max_steps=16)
    print(f"  walk_until_event -> {r}  map={nav.current_map()} pos={ow.pos()}", flush=True)
    b.screenshot(OUT + r"\oak_1.png")
    print("riding out the cutscene…", flush=True)
    done = ow.ride_cutscene()
    print(f"  ride_cutscene -> {done}  map={nav.current_map()} pos={ow.pos()}", flush=True)
    b.screenshot(OUT + r"\oak_2.png")
    b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
