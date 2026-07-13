"""G2 foothold probe: from the post-rival lab state (slot 2), exit the lab,
cross Pallet Town north, and enter Route 1 (an edge connection, not a warp).
RAM-gated at every step. On success saves slot 3 = "Route 1 south edge".

Run me with stream.py STOPPED (I bind 51055; ai_bridge.lua reconnects ~8s).
"""
from __future__ import annotations

import json
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.emulator.firered_state_reader import FireRedStateReader
from pokeai.perception.navigator import Navigator
from pokeai.skills.navigate_to import NavigateTo
from pokeai.skills.overworld import Overworld

ROOT = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai"
SLOTS = ROOT + r"\states\slots"


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    b = BizHawkBridge(timeout=180)
    say("waiting for ai_bridge to (re)connect…")
    b.wait_for_bizhawk()
    reader = FireRedStateReader(b)
    nav = Navigator(b)
    skill = NavigateTo(b, nav)
    ow = Overworld(b, nav, reader)

    say("loading slot 2 (post-rival, lab)…")
    if not b.load_state(SLOTS + r"\slot_2.state"):
        say("FAIL: slot 2 load")
        return 1
    time.sleep(1.0)
    say(f"map {nav.current_map()} pos {b.player_xy()}")
    if nav.current_map() != (4, 3):
        say("FAIL: expected Oak's lab (4,3)")
        return 1

    say("step 1: leave the lab…")
    nav.leave_building()
    ow.wait_control(20)
    m = nav.current_map()
    say(f"after leave_building: map {m} pos {b.player_xy()}")
    if m != (3, 0):
        say("FAIL: expected Pallet Town (3,0)")
        return 1

    say("step 2: north across Pallet toward Route 1…")
    deadline = time.time() + 150
    while nav.current_map() == (3, 0) and time.time() < deadline:
        skill.overworld_exit("north")
        ow.wait_control(10)
    m = nav.current_map()
    say(f"after north exit: map {m} pos {b.player_xy()}")
    if m == (3, 0):
        say("FAIL: never left Pallet Town")
        return 1

    say(f"ROUTE 1 REACHED — map id {m} (record this in ROADMAP/G2)")
    s = reader.read()
    say(f"party ok: count={s.party_count} money={s.money}")

    if b.save_state(SLOTS + r"\slot_3.state"):
        with open(SLOTS + r"\slot_2.json", encoding="utf-8") as f:
            meta = json.load(f)
        meta.update(n=3, summary="Route 1 south edge (G2 probe)",
                    ts=time.strftime("%Y-%m-%d %H:%M"))
        with open(SLOTS + r"\slot_3.json", "w", encoding="utf-8") as f:
            json.dump(meta, f)
        say("saved slot 3 = Route 1 south edge")
    return 0


if __name__ == "__main__":
    sys.exit(main())
