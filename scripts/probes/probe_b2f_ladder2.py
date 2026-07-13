"""B2F (31,11) ladder probe WITH battle handling: fight through to (31,12),
clear any battle, single held UP, screenshots at every stage."""
from __future__ import annotations

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.emulator.firered_state_reader import FireRedStateReader
from pokeai.perception.navigator import Navigator
from pokeai.skills.battle import Battle
from pokeai.skills.catch import Catch
from pokeai.skills.journey import WildPolicy

OUT = r"C:\pokeai-states\probe_b2f"


def say(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    b = BizHawkBridge(timeout=60)
    b.wait_for_bizhawk()
    reader = FireRedStateReader(b)
    nav = Navigator(b)
    battle = Battle(b, reader)
    catch = Catch(b, battle)
    policy = WildPolicy(b, battle, catch, narrate=say)

    say(f"map {nav.current_map()} pos {nav.vision.player_xy()}")
    policy.handle()
    say(f"after battle clear: map {nav.current_map()} pos {nav.vision.player_xy()}")

    target = (31, 12)
    for attempt in range(15):
        if nav.vision.player_xy() == target:
            break
        if nav.go_to(target, attempts=8):
            break
        say(f"  approach interrupted (attempt {attempt + 1}); resolving battle")
        policy.handle()
    pos = nav.vision.player_xy()
    say(f"at neighbor? pos {pos}")
    b.screenshot(OUT + r"\p2_neighbor.png")
    if pos != target:
        say("could not reach (31,12)")
        return 1

    policy.handle()  # clear any arrival-step encounter
    before = nav.current_map()
    say("holding UP into the ladder tile…")
    b.press_button_held("UP", 32)
    time.sleep(1.5)
    say(f"after UP: map {nav.current_map()} pos {nav.vision.player_xy()}")
    b.screenshot(OUT + r"\p2_after_up.png")
    if nav.current_map() != before:
        say("LADDER TOOK")
        return 0
    # try stepping ON the tile with a second UP and a longer wait
    b.press_button_held("UP", 48)
    time.sleep(2.0)
    say(f"after UP #2: map {nav.current_map()} pos {nav.vision.player_xy()}")
    b.screenshot(OUT + r"\p2_after_up2.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
