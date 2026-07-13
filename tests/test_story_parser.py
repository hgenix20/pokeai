"""Tests for the G10 walkthrough parser (planner/story_parser.py), run against
the REAL docs/Pokemon-FireRed-Walkthrough.md plus a few synthetic edge cases.

Ground truth for the whole-doc tests (grep of the doc): 21 '## PART' headers,
numbered 1..21; first [[Verify]] tag is the Jynx trade in Part 5 (~line 129).
Assertion messages stay ASCII (cp1252 console): doc text goes through ascii().
"""
from __future__ import annotations

import pytest

from pokeai.planner.story_parser import (
    DEFAULT_WALKTHROUGH_PATH,
    STEP_KINDS,
    BattleInfo,
    ItemInfo,
    StoryStep,
    load_walkthrough,
    parse_walkthrough,
)

# ---------------------------------------------------------------------------
# real-doc fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def wt():
    load_walkthrough.cache_clear()
    walkthrough = load_walkthrough()
    assert walkthrough.parts, "real walkthrough doc failed to load or parse"
    return walkthrough


def test_default_path_points_at_real_doc():
    assert DEFAULT_WALKTHROUGH_PATH.is_file()
    assert DEFAULT_WALKTHROUGH_PATH.name == "Pokemon-FireRed-Walkthrough.md"


def test_load_walkthrough_is_cached():
    load_walkthrough.cache_clear()
    assert load_walkthrough() is load_walkthrough()


# ---------------------------------------------------------------------------
# whole-doc structure
# ---------------------------------------------------------------------------


def test_part_count_and_numbering(wt):
    # grep '^## PART' over the doc finds exactly 21 headers, numbered 1..21
    assert [p.n for p in wt.parts] == list(range(1, 22))


def test_every_part_has_sections_and_every_section_has_steps(wt):
    for part in wt.parts:
        assert part.sections, f"part {part.n} has no sections"
        for section in part.sections:
            assert section.steps, f"part {part.n} section {ascii(section.title)} is empty"


def test_every_step_is_well_formed(wt):
    for step in wt.steps():
        assert isinstance(step, StoryStep)
        assert step.kind in STEP_KINDS
        assert step.text.strip(), "step with empty text"
        assert 1 <= step.part <= 21
        assert step.section.strip(), "step without a section title"
        if step.kind == "battle":
            assert isinstance(step.battle, BattleInfo) and step.battle.opponent
        if step.kind == "item":
            assert isinstance(step.item, ItemInfo) and step.item.name


def test_placeholders_kept_verbatim(wt):
    p1 = wt.part(1)
    texts = [s.text for s in p1.steps()]
    assert any("[Claude]" in t for t in texts), "player placeholder was rewritten"
    assert any("[Grok]" in t for t in texts), "rival placeholder was rewritten"


# ---------------------------------------------------------------------------
# Part 1
# ---------------------------------------------------------------------------


def test_part1_rival_battle(wt):
    p1 = wt.part(1)
    rivals = [
        s for s in p1.steps()
        if s.kind == "battle" and s.battle and "[Grok]" in s.battle.opponent
    ]
    assert rivals, "Part 1 rival battle not parsed"
    battle = rivals[0].battle
    assert battle.reward_text == "$80"
    assert "lv5" in battle.team_text


def test_part1_note_step(wt):
    p1 = wt.part(1)
    notes = [s for s in p1.steps() if s.kind == "note"]
    assert any("type-advantage" in s.text for s in notes)


# ---------------------------------------------------------------------------
# Part 2
# ---------------------------------------------------------------------------


def test_part2_oaks_parcel_item(wt):
    p2 = wt.part(2)
    parcels = [
        s for s in p2.steps()
        if s.kind == "item" and s.item and "Oak's Parcel" in s.item.name
    ]
    assert parcels, "Oak's Parcel item step not found in Part 2"
    source = parcels[0].item.source
    assert "Mart" in source or "clerk" in source.lower()


def test_part2_town_map_and_teachy_tv(wt):
    p2 = wt.part(2)
    items = [s for s in p2.steps() if s.kind == "item" and s.item]
    town_map = [s for s in items if s.item.name == "Town Map"]
    assert town_map and "Daisy" in town_map[0].item.source
    assert any(s.item.name == "Teachy TV" for s in items)


def test_part2_route22_optional_section_and_rival(wt):
    p2 = wt.part(2)
    route22 = p2.section("Route 22")
    assert route22 is not None
    assert route22.optional, "Route 22 (Optional) section not flagged optional"
    rivals = [s for s in route22.steps if s.kind == "battle" and s.battle]
    assert rivals and rivals[0].battle.reward_text == "$144"
    assert rivals[0].optional, "steps in an optional section should inherit the flag"


def test_part2_optional_step_prefix(wt):
    p2 = wt.part(2)
    optional_steps = [s for s in p2.steps() if s.optional and "Route 22" in s.text]
    assert optional_steps, "'Optional: go west to Route 22' step not flagged"


# ---------------------------------------------------------------------------
# Part 3
# ---------------------------------------------------------------------------


def test_part3_three_bug_catcher_battles(wt):
    p3 = wt.part(3)
    forest = p3.section("Viridian Forest")
    assert forest is not None
    bug_catchers = [
        s for s in forest.steps
        if s.kind == "battle" and s.battle and "Bug Catcher" in s.battle.opponent
    ]
    assert len(bug_catchers) == 3
    opponents = " / ".join(s.battle.opponent for s in bug_catchers)
    for name in ("Rick", "Doug", "Sammy"):
        assert name in opponents, f"Bug Catcher {name} missing"


def test_part3_brock_battle(wt):
    p3 = wt.part(3)
    brock = [
        s for s in p3.steps()
        if s.kind == "battle" and s.battle and s.battle.opponent == "Brock"
    ]
    assert brock, "Brock battle not parsed"
    battle = brock[0].battle
    assert "Geodude" in battle.team_text and "Onix" in battle.team_text
    assert battle.reward_text == "$1,400"


def test_part3_boulder_badge_reward_text_present(wt):
    p3 = wt.part(3)
    assert any("Boulder Badge" in s.text for s in p3.steps())


def test_part3_hm_tm_line_becomes_item(wt):
    p3 = wt.part(3)
    items = [s for s in p3.steps() if s.kind == "item" and s.item]
    assert any(s.item.name == "TM39 Rock Tomb" for s in items)


# ---------------------------------------------------------------------------
# tags
# ---------------------------------------------------------------------------


def test_verify_tags_doc_wide(wt):
    tagged = [
        s for s in wt.steps() if any(t.startswith("Verify") for t in s.tags)
    ]
    assert tagged, "no [[Verify]] tags found doc-wide"
    first = tagged[0]
    # first Verify in the doc is the Jynx-for-Poliwhirl trade (Part 5, ~line 129)
    assert first.part == 5
    assert any("Poliwhirl" in t for t in first.tags)
    assert "Jynx" in first.text


def test_missing_tags_doc_wide(wt):
    tagged = [
        s for s in wt.steps() if any(t.startswith("Missing") for t in s.tags)
    ]
    assert tagged, "no [[Missing]] tags found doc-wide"


# ---------------------------------------------------------------------------
# synthetic edge cases
# ---------------------------------------------------------------------------

_MALFORMED = """\
## PART 1 - Synthetic
### Battles Gone Wrong
> BATTLE
> BATTLE:
> BATTLE missing colon | team | reward
> (Battle Grunts if present)
1. a normal step
"""


def test_malformed_battle_lines_degrade_without_raising():
    wt = parse_walkthrough(_MALFORMED)
    steps = list(wt.steps())
    assert len(steps) == 5
    assert all(s.kind in STEP_KINDS for s in steps)
    # none of the malformed quote lines may become a battle
    assert [s.kind for s in steps[:4]] == ["note", "note", "note", "note"]
    assert steps[4].kind == "move" and steps[4].text == "a normal step"


_EMPTY_SECTION = """\
## PART 1 - Synthetic
### Totally Empty

### Full
1. do the thing
## PART 2 - Also Synthetic
### Later
- another thing
"""


def test_empty_section_tolerated_and_dropped():
    wt = parse_walkthrough(_EMPTY_SECTION)
    part1 = wt.part(1)
    assert part1 is not None
    assert [s.title for s in part1.sections] == ["Full"]
    assert wt.part(2) is not None


def test_weird_lines_become_move_steps():
    text = (
        "## PART 3 - Synthetic\n"
        "### Junk Drawer\n"
        "| a | table | row |\n"
        "?? mystery line with pipes | and | stuff\n"
        "      deeply indented free text\n"
    )
    wt = parse_walkthrough(text)
    steps = list(wt.steps())
    assert len(steps) == 3
    assert all(s.kind == "move" for s in steps)
    assert all(s.part == 3 and s.section == "Junk Drawer" for s in steps)


def test_battle_fields_partial_pipes():
    wt = parse_walkthrough(
        "## PART 1 - Synthetic\n### S\n> BATTLE: Gym Trainers | Geodude lines\n"
    )
    step = next(wt.steps())
    assert step.kind == "battle"
    assert step.battle == BattleInfo("Gym Trainers", "Geodude lines", "")


def test_steps_before_any_section_get_implicit_section():
    # Part 21 in the real doc has no '###' headers at all
    wt = parse_walkthrough("## PART 21 - Event Only\n[[Missing: page blank]]\n- info line\n")
    part = wt.part(21)
    assert part is not None and len(part.sections) == 1
    steps = part.sections[0].steps
    assert steps[0].kind == "note" and steps[0].tags == ("Missing: page blank",)
    assert steps[1].kind == "move"


def test_empty_and_missing_input():
    assert parse_walkthrough("").parts == ()
    assert load_walkthrough.__wrapped__("Z:\\nope\\definitely-missing.md").parts == ()
