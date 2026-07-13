"""Validate the starter gate end-to-end WITHOUT committing a starter:
ride Oak's dialogue to control (new reliable Overworld.wait_control), navigate to
the middle Poké Ball, open the 'Do you want this POKéMON?' prompt, read
frozen/party/dialogue at the prompt, then CANCEL with B so party stays 0.
Everything is resettable via slot 0 (bedroom) regardless."""
from __future__ import annotations

import time

from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.emulator.firered_state_reader import FireRedStateReader
from pokeai.perception.navigator import Navigator
from pokeai.skills.overworld import Overworld

OUT = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai\states\bizhawk"
# left->right on the table: Bulbasaur, Charmander, Squirtle
BALLS = {"left/Bulbasaur": (8, 4), "middle/Charmander": (9, 4), "right/Squirtle": (10, 4)}


def st(b, ow, reader, nav):
    return (f"map={nav.current_map()} pos={ow.pos()} party={reader.read().party_count} "
            f"frozen={ow.frozen()} dialogue={ow.dialogue_open()}")


def main() -> int:
    b = BizHawkBridge(timeout=60)
    print("waiting for ai_bridge…", flush=True)
    b.wait_for_bizhawk()
    print("connected:", b.ping(), flush=True)
    nav = Navigator(b)
    reader = FireRedStateReader(b)
    ow = Overworld(b, nav, reader)
    print("start:", st(b, ow, reader, nav), flush=True)

    print("riding Oak's intro to control…", flush=True)
    got = ow.wait_control(timeout=40)
    print(f"  control={got}  {st(b, ow, reader, nav)}", flush=True)
    b.screenshot(OUT + r"\starter_control.png")

    # geometry: which tiles around the table are walkable?
    walk = {t: nav.vision.walkable(*t) for t in
            [(7, 4), (8, 5), (9, 5), (10, 5), (9, 4), (8, 4), (10, 4)]}
    print("  walkable:", walk, flush=True)

    target = BALLS["middle/Charmander"]
    stand = (target[0], target[1] + 1)  # tile below the ball; face UP
    print(f"walking to {stand} to face the middle ball at {target}…", flush=True)
    reached = nav.go_to(stand)
    print(f"  reached={reached} pos={ow.pos()}", flush=True)

    b.press_button_held("UP", 12)   # face the ball
    time.sleep(0.2)
    b.tap("A", 6)                   # open it
    time.sleep(0.4)
    ow.screen.wait_stable()
    print(f"  after A#1: {st(b, ow, reader, nav)}", flush=True)
    b.screenshot(OUT + r"\starter_prompt1.png")

    if ow.dialogue_open():          # advance the "This is the FIRE POKéMON" line to the YES/NO
        b.tap("A", 6)
        time.sleep(0.4)
        ow.screen.wait_stable()
        print(f"  after A#2 (expect YES/NO): {st(b, ow, reader, nav)}", flush=True)
        b.screenshot(OUT + r"\starter_prompt2.png")

    # CANCEL — do not commit a starter yet
    b.tap("B", 6); time.sleep(0.3)
    b.tap("B", 6); time.sleep(0.3)
    ow.screen.wait_stable()
    print(f"after cancel: {st(b, ow, reader, nav)}", flush=True)
    b.screenshot(OUT + r"\starter_cancel.png")
    b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
