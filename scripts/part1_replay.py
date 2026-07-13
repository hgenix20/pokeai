"""Replay Part 1 from slot 0 (bedroom, post-intro) to the post-starter point in
Oak's lab, then save slot 1 so future sessions resume right before the GROK
rival battle. Uses the verified reusable arsenal (Overworld + Navigator +
NavigateTo + run_part1). Watchable live in the BizHawk window."""
from __future__ import annotations

import json
import time

from pokeai.agents.firered_part1 import run_part1
from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.emulator.firered_state_reader import FireRedStateReader
from pokeai.perception.navigator import Navigator
from pokeai.skills.navigate_to import NavigateTo
from pokeai.skills.overworld import Overworld

ROOT = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai"
SLOT0 = ROOT + r"\states\slots\slot_0.state"
SLOT1 = ROOT + r"\states\slots\slot_1.state"
SLOT1_JSON = ROOT + r"\states\slots\slot_1.json"
OUT = ROOT + r"\states\bizhawk"


class PrintHooks:
    """Console narration so the operator can follow along."""

    def phase(self, task_id, action):
        print(f"  [{task_id}] {action}", flush=True)

    def done_task(self, task_id):
        print(f"  [{task_id}] DONE", flush=True)


def main() -> int:
    b = BizHawkBridge(timeout=60)
    print("waiting for ai_bridge…", flush=True)
    b.wait_for_bizhawk()
    print("connected:", b.ping(), flush=True)

    # OneDrive can leave the .state as a dehydrated placeholder — the first
    # savestate.load then fails/stalls. Verify the load actually took (raw obj
    # xy leaves (0,0)) and retry until it does.
    print("loading slot 0 (bedroom, post-intro)…", flush=True)
    for attempt in range(5):
        ok = b.load_state(SLOT0)
        time.sleep(1.5)
        if ok and b.player_xy() != (0, 0):
            break
        print(f"  load attempt {attempt + 1} didn't take (ok={ok}, "
              f"xy={b.player_xy()}); retrying…", flush=True)
    else:
        print("slot 0 never loaded — aborting.", flush=True)
        b.close()
        return 1

    nav = Navigator(b)
    reader = FireRedStateReader(b)
    ow = Overworld(b, nav, reader)
    skill = NavigateTo(b, nav)

    s = reader.read()
    print(f"start: map={nav.current_map()} pos={ow.pos()} money={s.money} "
          f"party={s.party_count}", flush=True)

    ok = run_part1(ow, nav, skill, PrintHooks())
    s = reader.read()
    species = reader.read_species(0) if s.party_count else 0
    print(f"part1 ok={ok} map={nav.current_map()} pos={ow.pos()} "
          f"party={s.party_count} species={species}", flush=True)
    b.screenshot(OUT + r"\part1_done.png")

    if ok and s.party_count >= 1:
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
            "summary": "Starter CLAW in hand in Oak's lab — GROK battle next",
            "ts": time.strftime("%Y-%m-%d %H:%M"),
        }
        with open(SLOT1_JSON, "w", encoding="utf-8") as f:
            json.dump(ctx, f)
        print("slot 1 saved.", flush=True)

    b.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
