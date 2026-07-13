"""Tests for the G10 StoryDriver (planner/story_driver.py), run against the
REAL docs/Pokemon-FireRed-Walkthrough.md plus synthetic edge cases.

Ground truth for Parts 1+2 (26 steps total), derived by the compiler itself
and pinned here as the G10 acceptance anchor:
  * fact-driven ("auto") steps: 4 item + 2 battle + 2 map + 2 note = 10
  * manual-mark steps: 16 (menuing, NPC talks, tutorials, the unknown-name
    'Deliver Oak's Parcel' acquisition, and the optional Route 22 detour)
The replay test walks Parts 1-2 with facts snapshots that mirror the recorded
save slots (route1 / part2_parcel / deliver_oak / forest entrance) and no
hand-coded steps. Assertion messages stay ASCII (cp1252 console): doc text
goes through ascii().
"""
from __future__ import annotations

from collections import Counter

import pytest

from pokeai.planner.story_driver import (
    BADGE_FLAG_FIRST,
    GYM_BADGES,
    ITEM_IDS,
    MAP_IDS,
    MODES,
    StoryDriver,
)
from pokeai.planner.story_parser import (
    Walkthrough,
    load_walkthrough,
    parse_walkthrough,
)
from pokeai.planner.task import Task, TaskKind, TaskStatus
from pokeai.planner.task_queue import TaskQueue

# ---------------------------------------------------------------------------
# fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def wt():
    load_walkthrough.cache_clear()
    walkthrough = load_walkthrough()
    assert walkthrough.parts, "real walkthrough doc failed to load or parse"
    return walkthrough


def _find(driver, fragment):
    """First compiled step whose text contains `fragment` (ASCII fragments)."""
    for compiled in driver.compiled:
        if fragment in compiled.step.text:
            return compiled
    raise AssertionError(f"no compiled step contains {fragment!r}")


# Facts snapshots simulating the recorded save slots along Parts 1-2.
_SLOT_ROUTE1 = {                       # rival beaten, standing on Route 1
    "beaten_opponents": {"Rival [Grok]"},
    "current_map": (3, 19),
    "items": {13: 1},
    "badges": 0,
}
_SLOT_VIRIDIAN_PARCEL = {              # part2_parcel: parcel in key items
    "beaten_opponents": {"Rival [Grok]"},
    "current_map": (3, 1),
    "items": {349: 1, 13: 2},
    "badges": 0,
}
_SLOT_DELIVERED = {                    # deliver_oak: balls + Town Map + Teachy TV
    "beaten_opponents": {"Rival [Grok]"},
    "current_map": (3, 1),
    "items": {4: 5, 361: 1, 366: 1, 13: 2},
    "badges": 0,
}
_SLOT_FOREST = {                       # stepped into Viridian Forest
    "beaten_opponents": {"Rival [Grok]"},
    "current_map": (1, 0),
    "items": {4: 5, 361: 1, 366: 1, 13: 2, 14: 1},
    "badges": 0,
}


def _replay(driver, snapshots, until_part):
    """Drive the story like the live loop would: advance on the current facts
    snapshot; a stalled manual step gets mark_manual (recorded), a stalled
    fact step moves to the next snapshot. Returns the marked keys in order."""
    marked = []
    index = 0
    for _ in range(500):
        compiled = driver.current()
        if compiled is None or compiled.step.part > until_part:
            return marked
        if driver.advance(snapshots[index]):
            continue
        if compiled.mode == "manual":
            driver.mark_manual(compiled.key)
            marked.append(compiled.key)
        else:
            index += 1
            assert index < len(snapshots), (
                f"ran out of facts snapshots at {ascii(compiled.step.text)}"
            )
    raise AssertionError("replay did not terminate")


# ---------------------------------------------------------------------------
# known tables
# ---------------------------------------------------------------------------


def test_known_id_tables():
    assert ITEM_IDS["OAK'S PARCEL"] == 349
    assert ITEM_IDS["TOWN MAP"] == 361
    assert ITEM_IDS["TEACHY TV"] == 366
    assert ITEM_IDS["POKE BALL"] == 4
    assert ITEM_IDS["POTION"] == 13
    assert ITEM_IDS["ANTIDOTE"] == 14
    assert MAP_IDS["PALLET TOWN"] == (3, 0)
    assert MAP_IDS["VIRIDIAN CITY"] == (3, 1)
    assert MAP_IDS["PEWTER CITY"] == (3, 2)
    assert MAP_IDS["ROUTE 1"] == (3, 19)
    assert MAP_IDS["ROUTE 2"] == (3, 20)
    assert MAP_IDS["VIRIDIAN FOREST"] == (1, 0)
    assert GYM_BADGES["BROCK"] == 1


# ---------------------------------------------------------------------------
# start state + keys
# ---------------------------------------------------------------------------


def test_default_driver_loads_real_walkthrough():
    driver = StoryDriver()
    assert driver.progress()["total"] > 0
    assert driver.current_step().part == 1


def test_starts_at_part1_step1(wt):
    driver = StoryDriver(wt)
    current = driver.current_step()
    assert current.part == 1
    assert current.text == "Press A/Start on title screen"
    progress = driver.progress()
    assert set(progress) == {"part", "section", "step_index", "done_count", "total"}
    assert progress["part"] == 1
    assert progress["step_index"] == 0
    assert progress["done_count"] == 0
    assert progress["total"] == sum(1 for _ in wt.steps())


def test_step_keys_stable_and_unique(wt):
    keys_a = [c.key for c in StoryDriver(wt).compiled]
    keys_b = [c.key for c in StoryDriver(wt).compiled]
    assert keys_a == keys_b, "keys must be stable across driver instances"
    assert len(set(keys_a)) == len(keys_a), "keys must be unique"
    for compiled in StoryDriver(wt).compiled:
        assert compiled.key.startswith(f"{compiled.step.part}/")
        assert compiled.key.endswith(f"/{compiled.index}")
        assert compiled.mode in MODES


# ---------------------------------------------------------------------------
# predicate compilation over the real doc
# ---------------------------------------------------------------------------


def test_parts_1_2_mode_histogram(wt):
    driver = StoryDriver(wt)
    counts = Counter(c.mode for c in driver.compiled if c.step.part <= 2)
    assert counts == {"manual": 16, "item": 4, "battle": 2, "map": 2, "note": 2}
    part1 = Counter(c.mode for c in driver.compiled if c.step.part == 1)
    assert part1 == {"manual": 9, "note": 1, "battle": 1, "map": 1}


def test_parcel_item_step_completes_from_bag_facts(wt):
    compiled = _find(StoryDriver(wt), "shopkeeper gives Oak's Parcel")
    assert compiled.mode == "item"
    assert compiled.step.part == 2
    facts = {"items": {349: 1}}
    before = {"items": {349: 1}}
    assert compiled.completes_when(facts) is True
    assert compiled.completes_when(facts) is True, "same facts -> same result"
    assert facts == before, "predicates must not mutate facts"
    assert compiled.completes_when({"items": {}}) is False
    assert compiled.completes_when({"items": {349: 0}}) is False
    assert compiled.completes_when({}) is False
    assert compiled.completes_when({"items": {349}}) is True, "id sets work too"


def test_deliver_parcel_step_is_manual(wt):
    # 'Oak gives Pokedex + 5 Poke Balls each' is an unknown item name: it must
    # NOT complete from bag facts (not even the parcel), only via events.
    compiled = _find(StoryDriver(wt), "Deliver Oak's Parcel")
    assert compiled.mode == "manual"
    assert compiled.completes_when({"items": {349: 1, 4: 5}}) is False
    assert compiled.completes_when({"events": {compiled.key}}) is True


def test_teachy_tv_prefix_name_maps_to_item(wt):
    # "Old man gives Teachy TV demonstration" -> prefix match on TEACHY TV
    compiled = _find(StoryDriver(wt), "gives Teachy TV demonstration")
    assert compiled.mode == "item"
    assert compiled.completes_when({"items": {366: 1}}) is True
    assert compiled.completes_when({"items": {361: 1}}) is False


def test_viridian_forest_move_step_completes_on_map(wt):
    compiled = _find(StoryDriver(wt), "into Viridian Forest")
    assert compiled.mode == "map"
    assert compiled.completes_when({"current_map": (1, 0)}) is True
    assert compiled.completes_when({"current_map": (3, 20)}) is False
    assert compiled.completes_when({"current_map": (1 << 8) | 0}) is True


def test_pewter_city_move_step_synthetic():
    driver = StoryDriver(parse_walkthrough(
        "## PART 3 - Synthetic\n### To Pewter\n1. Continue north to Pewter City\n"
    ))
    compiled = driver.current()
    assert compiled.mode == "map"
    assert compiled.completes_when({"current_map": (3, 2)}) is True
    assert compiled.completes_when({"current_map": (3, 1)}) is False


def test_last_map_mention_wins_as_destination():
    driver = StoryDriver(parse_walkthrough(
        "## PART 1 - Synthetic\n### Road\n"
        "1. Leave Pallet Town and head north to Viridian City\n"
    ))
    compiled = driver.current()
    assert compiled.mode == "map"
    assert compiled.completes_when({"current_map": (3, 1)}) is True
    assert compiled.completes_when({"current_map": (3, 0)}) is False


def test_rival_battle_completes_via_beaten_opponents(wt):
    driver = StoryDriver(wt)
    compiled = next(c for c in driver.compiled
                    if c.step.battle and "[Grok]" in c.step.battle.opponent)
    assert compiled.mode == "battle"
    assert compiled.completes_when({"beaten_opponents": {"Rival [Grok]"}}) is True
    assert compiled.completes_when({"beaten_opponents": {"rival [grok]"}}) is True
    assert compiled.completes_when({"beaten_opponents": {"Brock"}}) is False
    assert compiled.completes_when({}) is False


def test_brock_completes_via_badge_or_beaten_or_flag(wt):
    driver = StoryDriver(wt)
    compiled = next(c for c in driver.compiled
                    if c.step.battle and c.step.battle.opponent == "Brock")
    assert compiled.mode == "battle"
    assert compiled.completes_when({"badges": 0}) is False
    assert compiled.completes_when({"badges": 1}) is True
    assert compiled.completes_when({"beaten_opponents": ["BROCK"]}) is True
    assert compiled.completes_when({"flags": {BADGE_FLAG_FIRST}}) is True


def test_predicates_never_raise_on_garbage_facts(wt):
    garbage = {"items": 7, "current_map": "nope", "beaten_opponents": 9,
               "badges": "x", "flags": 3, "events": None}
    for compiled in StoryDriver(wt).compiled[:60]:
        result = compiled.completes_when(garbage)
        assert result in (True, False)
        if compiled.mode != "note":
            assert result is False


# ---------------------------------------------------------------------------
# the acceptance test: replay Parts 1-2 with no hand-coded steps
# ---------------------------------------------------------------------------


def test_replay_parts_1_2_from_slot_snapshots(wt):
    driver = StoryDriver(wt)
    snapshots = [_SLOT_ROUTE1, _SLOT_VIRIDIAN_PARCEL, _SLOT_DELIVERED, _SLOT_FOREST]
    marked = _replay(driver, snapshots, until_part=2)

    expected_manual = [c.key for c in driver.compiled
                       if c.step.part <= 2 and c.mode == "manual"]
    assert marked == expected_manual, "only manual steps may need marking"
    assert len(marked) == 16

    part12_total = sum(1 for c in driver.compiled if c.step.part <= 2)
    assert part12_total == 26
    progress = driver.progress()
    assert progress["done_count"] == part12_total
    assert progress["part"] == 3
    assert driver.remaining(1) == []
    assert driver.remaining(2) == []

    # fact-driven steps completed WITHOUT marks: items, battles, maps, notes
    auto_keys = {c.key for c in driver.compiled if c.step.part <= 2 and c.auto}
    assert len(auto_keys) == 10
    assert auto_keys.isdisjoint(marked)
    assert _find(driver, "shopkeeper gives Oak's Parcel").key not in marked
    assert _find(driver, "Deliver Oak's Parcel").key in marked
    assert _find(driver, "go west to Route 22").key in marked


def test_advance_flushes_consecutive_passing_steps(wt):
    driver = StoryDriver(wt)
    assert driver.advance({}) == []
    assert driver.advance(None) == []
    first = driver.current()
    assert first.mode == "manual"
    driver.mark_manual(first.key)
    done = driver.advance({})
    assert [c.key for c in done] == [first.key]
    assert driver.progress()["done_count"] == 1


def test_events_facts_complete_without_mark_manual(wt):
    driver = StoryDriver(wt)
    first_key = driver.current().key
    done = driver.advance({"events": {first_key}})
    assert [c.key for c in done] == [first_key]
    assert driver.advance({}) == [], "next manual step must still be gated"


def test_start_part_skips_earlier_parts(wt):
    driver = StoryDriver(wt, start_part=3)
    assert driver.current_step().part == 3
    expected = sum(1 for part in wt.parts if part.n >= 3 for _ in part.steps())
    assert driver.progress()["total"] == expected
    assert driver.remaining(1) == []


# ---------------------------------------------------------------------------
# to_task: the planner seam
# ---------------------------------------------------------------------------


def test_to_task_shape_and_queue_integration(wt):
    driver = StoryDriver(wt)
    task = driver.to_task()
    assert isinstance(task, Task)
    assert task.kind is TaskKind.ADVANCE_STORY
    assert task.source == "story"
    assert task.note == driver.current_step().text
    key = driver.current().key
    assert task.params == {"step": key}
    assert task.id == f"advance_story(step={key})"
    assert task.is_satisfied({}) is False

    queue = TaskQueue()
    queue.enqueue(task)
    queue.tick({})
    assert task.status is TaskStatus.PENDING
    driver.mark_manual(key)                 # satisfied() honors later marks
    queue.tick({})
    assert task.status is TaskStatus.DONE

    # standing task: re-emitting the same step dedupes to the same id
    assert driver.to_task().id == task.id


def test_to_task_follows_the_cursor(wt):
    driver = StoryDriver(wt)
    first = driver.to_task()
    driver.advance({"events": {driver.current().key}})
    second = driver.to_task()
    assert second.id != first.id
    assert second.note == driver.current_step().text


# ---------------------------------------------------------------------------
# synthetic edge cases
# ---------------------------------------------------------------------------


def test_empty_walkthrough():
    driver = StoryDriver(walkthrough=Walkthrough())
    assert driver.current() is None
    assert driver.current_step() is None
    assert driver.advance({}) == []
    assert driver.progress() == {"part": None, "section": None,
                                 "step_index": None, "done_count": 0, "total": 0}
    assert driver.to_task() is None
    assert driver.remaining(1) == []


def test_all_notes_section_auto_advances():
    driver = StoryDriver(parse_walkthrough(
        "## PART 1 - Synthetic\n"
        "### Chatter\n"
        "- NOTE: first note\n"
        "- NOTE: second note\n"
        "> a plain quote also lands as a note\n"
    ))
    done = driver.advance({})
    assert [c.mode for c in done] == ["note", "note", "note"]
    assert driver.current_step() is None
    assert driver.progress()["done_count"] == 3
    assert driver.to_task() is None
