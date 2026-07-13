"""Resume from a parked mid-cutscene state in Oak's lab: ride out the rest of
the scripted intro (long timeout — Oak + GROK talk a lot), pick a random
starter, nickname it CLAW, and save slot 1 (post-starter, pre-rival)."""
from __future__ import annotations

import json
import time

from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.emulator.firered_state_reader import FireRedStateReader
from pokeai.perception.navigator import Navigator
from pokeai.skills.overworld import Overworld

ROOT = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai"
SLOT1 = ROOT + r"\states\slots\slot_1.state"
SLOT1_JSON = ROOT + r"\states\slots\slot_1.json"
OUT = ROOT + r"\states\bizhawk"
SPECIES = {1: "Bulbasaur", 4: "Charmander", 7: "Squirtle"}


def main() -> int:
    b = BizHawkBridge(timeout=60)
    print("waiting for ai_bridge…", flush=True)
    b.wait_for_bizhawk()
    print("connected:", b.ping(), flush=True)

    nav = Navigator(b)
    reader = FireRedStateReader(b)
    ow = Overworld(b, nav, reader)

    print(f"start: map={nav.current_map()} pos={ow.pos()} "
          f"party={reader.read().party_count}", flush=True)

    print("riding out the lab cutscene (long timeout)…", flush=True)
    got_control = ow.wait_control(timeout=180)
    print(f"  control={got_control} pos={ow.pos()} "
          f"dialogue={ow.dialogue_open()}", flush=True)
    b.screenshot(OUT + r"\resume_control.png")

    print("picking starter (random, nickname CLAW)…", flush=True)
    species = ow.pick_starter(nickname="CLAW")
    s = reader.read()
    print(f"  species={species} ({SPECIES.get(species, '??')}) "
          f"party={s.party_count}", flush=True)
    b.screenshot(OUT + r"\resume_starter.png")

    if not species or s.party_count < 1:
        print("starter still not committed — needs a look.", flush=True)
        b.close()
        return 1

    print("saving slot 1 (post-starter, pre-rival)…", flush=True)
    b.save_state(SLOT1)
    ctx = {
        "n": 1,
        "intro_done": True,
        "strategy": "storyline",
        "goal": "Become the Pokémon League Champion",
        "tasks": [
            {"id": "adventure", "name": "Begin the adventure", "status": "done",
             "children": [
                 {"id": "name_self", "name": "Choose my name — CLAUDE", "status": "done"},
                 {"id": "name_rival", "name": "Name my rival — GROK", "status": "done"},
                 {"id": "enter_world", "name": "Wake up in Pallet Town", "status": "done"}]},
            {"id": "starter", "name": "Get my first Pokémon from Prof. Oak",
             "status": "done", "children": []},
            {"id": "rival1", "name": "Win my first battle vs GROK",
             "status": "active", "children": []},
        ],
        "summary": f"Starter {SPECIES.get(species, '??')} 'CLAW' in hand — GROK battle next",
        "ts": time.strftime("%Y-%m-%d %H:%M"),
    }
    with open(SLOT1_JSON, "w", encoding="utf-8") as f:
        json.dump(ctx, f)
    print("slot 1 saved.", flush=True)
    b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
