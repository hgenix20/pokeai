"""From inside Oak's lab, ride out the scripted intro (Oak + rival arrival) until
control returns, then walk to a starter ball and pick it — verifying the gate can
be passed by navigating to a ball (not A-mashing). Observational + screenshots."""
from __future__ import annotations

import time

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
    reader = FireRedStateReader(b)
    ow = Overworld(b, nav, reader)
    print(f"start: map={nav.current_map()} pos={ow.pos()} party={reader.read().party_count}", flush=True)

    print("riding Oak's intro / rival arrival until control returns…", flush=True)
    ow.ride_cutscene(rounds=12)
    print(f"  after: map={nav.current_map()} pos={ow.pos()} dialogue_open={ow.dialogue_open()}", flush=True)
    b.screenshot(OUT + r"\starter_1.png")

    # the 3 starter balls sit on the table at (8,4)/(9,4)/(10,4)
    for ball in [(9, 4), (8, 4), (10, 4)]:
        if reader.read().party_count >= 1:
            break
        print(f"walking to the ball at {ball} and pressing A…", flush=True)
        ow.interact(ball)
        time.sleep(0.4)
        print(f"  party={reader.read().party_count} map={nav.current_map()} pos={ow.pos()}", flush=True)
    b.screenshot(OUT + r"\starter_2.png")
    print(f"FINAL party_count = {reader.read().party_count}", flush=True)
    b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
