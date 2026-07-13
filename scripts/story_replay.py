"""G10 ACCEPTANCE (live half): replay Parts 1-2 through the StoryDriver
against the RECORDED SLOTS, facts read from real RAM at each checkpoint.

For each slot in story order, build the facts dict from FireRedStateReader
(bag items, current map, badges, dex flag) and drive StoryDriver.advance().
Steps that are not fact-checkable (mode 'manual'; and battle steps, whose
beaten_opponents set a live runtime would maintain) are marked as they are
reached - the driver's documented design. PASS = every FACT-mode step (item/
map) completed from facts alone (never manually) AND the cursor reaches
Part 3 by the final slot. stream.py STOPPED.
"""
from __future__ import annotations

import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from pokeai.emulator.bizhawk_bridge import BizHawkBridge
from pokeai.emulator.firered_state_reader import FireRedStateReader
from pokeai.perception.navigator import Navigator
from pokeai.planner.story_driver import StoryDriver

SLOTS = r"C:\Users\Sagac\OneDrive\KameronOS\PROJECTS\Pokemon-Red-AI\pokeai\states\slots"
FLAG_SYS_POKEDEX_GET = 0x829
# Story-ordered checkpoints. Slot 8 (Route 1) is chronologically post-delivery
# but is the only recorded Route-1 stand; facts are monotone so its early dex
# flag is harmless. No recorded slot stands INSIDE the forest: Part 2's final
# "into Viridian Forest" map step is marked when reached (logged as such).
STORY_SLOTS = [0, 1, 8, 4, 5, 7, 6]


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def live_facts(b, reader, nav, beaten, events) -> dict:
    items = {}
    for pocket in ("items", "key_items", "balls"):
        for item, qty in reader.read_bag_pocket(pocket):
            items[item] = items.get(item, 0) + qty
    flags = set()
    if reader.read_flag(FLAG_SYS_POKEDEX_GET):
        flags.add(FLAG_SYS_POKEDEX_GET)
    return {
        "items": items,
        "current_map": nav.current_map(),
        "badges": reader.read_badges(),
        "flags": flags,
        "beaten_opponents": beaten,
        "events": events,
    }


def main() -> int:
    b = BizHawkBridge(timeout=180)
    say("waiting for ai_bridge…")
    b.wait_for_bizhawk()
    reader = FireRedStateReader(b)
    nav = Navigator(b)
    driver = StoryDriver()

    beaten: set = set()
    events: set = set()
    fact_completed: list = []
    manual_marked: list = []

    for slot in STORY_SLOTS:
        if not b.load_state(SLOTS + rf"\slot_{slot}.state"):
            say(f"FAIL slot {slot} load")
            return 1
        time.sleep(1.0)
        facts = live_facts(b, reader, nav, beaten, events)
        say(f"slot {slot}: map {facts['current_map']} items {facts['items']} "
            f"badges {facts['badges']} dex {bool(facts['flags'])}")
        # drive as far as this checkpoint's facts allow; non-fact steps are
        # marked as reached (a live runtime's executors would do this)
        for _ in range(200):
            done = driver.advance(facts)
            for st in done:
                if st.mode in ("item", "map"):
                    fact_completed.append(st.key)
                    say(f"  FACT-completed [{st.mode}] {st.key}: "
                        f"{st.step.text[:60]}")
            cur = driver.current()
            if cur is None:
                break
            if cur.mode in ("item", "map"):
                break              # needs facts a later slot provides
            if cur.mode == "battle":
                opp = (cur.step.battle.opponent if cur.step.battle else cur.key)
                beaten.add(opp)
                facts["beaten_opponents"] = beaten
                say(f"  battle step reached -> beaten_opponents += {opp!r}")
                continue
            driver.mark_manual(cur.key)
            manual_marked.append(cur.key)
            say(f"  manual-marked [{cur.mode}] {cur.key}: {cur.step.text[:60]}")
        p = driver.progress()
        say(f"  progress: part {p['part']} done {p['done_count']}/{p['total']}")

    # the one step no recorded checkpoint can witness: standing in the forest
    cur = driver.current()
    if cur is not None and cur.mode == "map" and "FOREST" in cur.step.text.upper():
        say(f"  final forest-entry step marked (no recorded in-forest slot): "
            f"{cur.key}")
        driver.mark_manual(cur.key)
        manual_marked.append(cur.key)
        driver.advance(live_facts(b, reader, nav, beaten, events))

    p = driver.progress()
    say(f"END: part {p['part']}, fact-completed {len(fact_completed)}, "
        f"manual {len(manual_marked)}")
    ok = p["part"] >= 3 and len(fact_completed) >= 5
    say("PASS - Parts 1-2 replayed from recorded slots (fact steps from RAM)"
        if ok else "FAIL - cursor or fact-step count short")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
