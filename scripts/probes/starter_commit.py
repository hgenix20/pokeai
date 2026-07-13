"""Commit a RANDOM starter (viewers will choose via a Twitch bot later; random for
now). Back out of any parked YES/NO using a ground-truth control check (on a YES/NO
a direction only moves the cursor, not the player), pick a random ball, walk to it,
and confirm — stopping the instant party_count hits 1 so we don't mash into the
rival cutscene. Reads the committed species from RAM. Resettable via slot 0."""
from __future__ import annotations

import random
import time

from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.emulator.firered_state_reader import FireRedStateReader
from pokeai.perception.navigator import Navigator
from pokeai.skills.overworld import Overworld

OUT = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai\states\bizhawk"
BALLS = [(8, 4), (9, 4), (10, 4)]          # the three on Oak's table
SPECIES = {1: "Bulbasaur", 4: "Charmander", 7: "Squirtle"}


def backout_to_control(b, ow, tries=8) -> bool:
    """Press B until the player can actually MOVE — proof the YES/NO is gone and
    control is ours (Oak's 'Which one...' box may still linger, that's fine)."""
    for _ in range(tries):
        if b.press_direction_settle("DOWN") or b.press_direction_settle("UP"):
            return True
        b.tap("B", 8)
        time.sleep(0.35)
        ow.screen.wait_stable()
    return b.press_direction_settle("DOWN")


def main() -> int:
    b = BizHawkBridge(timeout=60)
    print("waiting for ai_bridge…", flush=True)
    b.wait_for_bizhawk()
    print("connected:", b.ping(), flush=True)
    nav = Navigator(b)
    reader = FireRedStateReader(b)
    ow = Overworld(b, nav, reader)
    print(f"start: map={nav.current_map()} pos={ow.pos()} party={reader.read().party_count}", flush=True)

    print("backing out to control…", flush=True)
    ctrl = backout_to_control(b, ow)
    print(f"  control={ctrl} pos={ow.pos()} party={reader.read().party_count}", flush=True)

    chosen = random.choice(BALLS)
    stand = (chosen[0], chosen[1] + 1)
    print(f"RANDOM starter ball = {chosen} (stand {stand})", flush=True)

    for _ in range(6):
        if ow.pos() == stand or nav.go_to(stand):
            break
        if ow.dialogue_open():
            b.tap("A", 6); time.sleep(0.2)
        ow.screen.wait_stable()
    print(f"  reached stand: pos={ow.pos()}", flush=True)

    b.press_button_held("UP", 12)          # face the ball
    time.sleep(0.2)
    got = False
    for i in range(12):
        if reader.read().party_count >= 1:
            got = True
            break
        b.tap("A", 6)                      # open -> "This is X" -> YES/NO -> YES
        time.sleep(0.45)
        ow.screen.wait_stable()
    party = reader.read().party_count
    print(f"  committed={got} party={party}", flush=True)

    if got:
        sp = ow.reader.read_species(0) if hasattr(ow.reader, "read_species") else reader.read_species(0)
        print(f"  STARTER species id={sp} -> {SPECIES.get(sp, '??')}", flush=True)
    b.screenshot(OUT + r"\starter_got.png")

    f = ow.screen.grab()
    print(f"  aftermath: dialogue={ow.dialogue_open(f)} keyboard={ow.screen.is_keyboard(f)} "
          f"map={nav.current_map()} pos={ow.pos()}", flush=True)
    b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
