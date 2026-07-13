"""G10 walkthrough parser: docs/Pokemon-FireRed-Walkthrough.md -> StorySteps.

The walkthrough doc is machine-readable markdown (see its lines 1-9 for the
format legend): '## PART N' part headers, '### Location' sections (plus a few
'#### Sub-part' and '**area:**' markers), numbered/bulleted steps, and tagged
lines ('> BATTLE: name | team | reward', 'ITEM: name | source', 'HM/TM:',
'NOTE:', '[[Verify: ...]]', '[[Missing: ...]]'). This module turns that doc
into typed, frozen StorySteps for the StoryDriver (planner ADVANCE_STORY
tasks), the same way knowledge/roots.py turns AGENT_ROOTS.md into priors.

Parsing is deliberately tolerant: no line ever raises. Anything unrecognized
becomes a kind='move' free-text step, a '>' quote that is not a well-formed
BATTLE degrades to a note, and player/rival name placeholders ([Claude],
[Grok]) are kept verbatim. '## APPENDIX' blocks (reference tables) are kept
as raw text, not steps. Pure logic, no emulator/UI imports.
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# The walkthrough lives at the project root (....../pokeai/docs/), three parents
# up from this file (....../pokeai/src/pokeai/planner/story_parser.py), the same
# layout knowledge/roots.py uses for DEFAULT_ROOTS_PATH.
DEFAULT_WALKTHROUGH_PATH = (
    Path(__file__).resolve().parents[3] / "docs" / "Pokemon-FireRed-Walkthrough.md"
)

STEP_KINDS = ("move", "battle", "item", "note")

# --- headers (em/en dash or plain dash between the PART number and title) ---
_PART_RE = re.compile(r"^##\s+PART\s+(\d+)\s*[—–-]*\s*(.*)$")
_H2_RE = re.compile(r"^##(?!#)\s*(.*)$")          # any other h2 = appendix/reference
_SECTION_RE = re.compile(r"^###(?!#)\s*(.*)$")
_SUBSECTION_RE = re.compile(r"^####\s*(.*)$")
_HRULE_RE = re.compile(r"^-{3,}$")

# --- step-level markers ---
_LIST_MARKER_RE = re.compile(r"^(?:\d+[.)]\s+|[-*+•]\s+)")
_TAG_RE = re.compile(r"\[\[\s*(Verify|Missing)\s*:?\s*([^\]]*?)\s*\]\]", re.IGNORECASE)
_ITEM_MARKER_RE = re.compile(r"\bITEMS?:\s*")
_HM_MARKER_RE = re.compile(r"\bHM/TM:\s*")
# Free-text battles ("Battle Bug Catcher Rick", "defeat Bug Catcher Sammy",
# "Pass Bug Catcher Doug"): verb followed by a Capitalized Name sequence.
# Lowercase objects ("battle wild Pokemon", "Defeat 5 trainers") do not match.
_BATTLE_VERB_RE = re.compile(
    r"\b(?:[Bb]attle|[Dd]efeat|[Pp]ass)\s+([A-Z][\w'.’-]*(?:\s+[A-Z][\w'.’-]*)*)"
)
# "<giver> gives <Item Name>": an NPC handing the player something capitalized
# (catches un-tagged acquisitions like "shopkeeper gives Oak's Parcel").
_GIVES_RE = re.compile(r"\bgives\s+([A-Z][^,.;:(→—\[]*)")
# Characters stripped from a mid-line item source prefix (arrows, dots, dashes).
_PREFIX_JUNK = " \t-;:—–→·"


@dataclass(frozen=True)
class BattleInfo:
    opponent: str
    team_text: str = ""
    reward_text: str = ""


@dataclass(frozen=True)
class ItemInfo:
    name: str
    source: str = ""


@dataclass(frozen=True)
class StoryStep:
    kind: str                        # one of STEP_KINDS
    text: str                        # step text, list marker stripped, otherwise verbatim
    part: int                        # PART number this step belongs to
    section: str                     # section title this step belongs to
    battle: BattleInfo | None = None
    item: ItemInfo | None = None
    optional: bool = False
    tags: tuple[str, ...] = ()       # e.g. ("Verify: Poliwhirl availability",)


@dataclass(frozen=True)
class StorySection:
    title: str
    steps: tuple[StoryStep, ...] = ()
    optional: bool = False


@dataclass(frozen=True)
class StoryPart:
    n: int
    title: str
    sections: tuple[StorySection, ...] = ()

    def steps(self) -> Iterator[StoryStep]:
        for section in self.sections:
            yield from section.steps

    def section(self, title: str) -> StorySection | None:
        """First section whose title contains `title` (case-insensitive)."""
        needle = title.lower()
        for section in self.sections:
            if needle in section.title.lower():
                return section
        return None


@dataclass(frozen=True)
class Walkthrough:
    parts: tuple[StoryPart, ...] = ()
    appendices: tuple[tuple[str, str], ...] = ()   # (title, raw text) reference blocks

    def part(self, n: int) -> StoryPart | None:
        for part in self.parts:
            if part.n == n:
                return part
        return None

    def steps(self) -> Iterator[StoryStep]:
        for part in self.parts:
            yield from part.steps()

    def battles(self) -> list[StoryStep]:
        return [s for s in self.steps() if s.kind == "battle"]

    def items(self) -> list[StoryStep]:
        return [s for s in self.steps() if s.kind == "item"]


# --------------------------------------------------------------------------
# line-level helpers
# --------------------------------------------------------------------------

def _strip_list_marker(line: str) -> str:
    """Remove leading '1. ' / '- ' / '* ' markers (nested markers included)."""
    text = line.strip()
    prev = None
    while prev != text:
        prev = text
        text = _LIST_MARKER_RE.sub("", text, count=1).strip()
    return text


def _extract_tags(text: str) -> tuple[str, ...]:
    """[[Verify: x]] / [[Missing: x]] / bare [[Missing]] -> ('Verify: x', ...)."""
    tags = []
    for kind, payload in _TAG_RE.findall(text):
        kind = kind.capitalize()
        tags.append(f"{kind}: {payload}" if payload else kind)
    return tuple(tags)


def _strip_trailing_paren(name: str) -> str:
    """Drop one trailing '(...)' aside ("Vs. Seeker (recharges...)" -> "Vs. Seeker")."""
    name = name.strip()
    if name.endswith(")") and " (" in name:
        name = name[: name.rindex(" (")]
    return name.strip()


def _parse_battle_fields(after: str) -> BattleInfo | None:
    """'opponent | team | reward' after a 'BATTLE:' marker; None if no opponent."""
    fields = [f.strip() for f in after.split("|")]
    opponent = fields[0]
    if not opponent:
        return None
    team = fields[1] if len(fields) > 1 else ""
    reward = " | ".join(fields[2:]) if len(fields) > 2 else ""
    return BattleInfo(opponent=opponent, team_text=team, reward_text=reward)


def _parse_item_fields(probe: str, marker: re.Match) -> ItemInfo | None:
    """An ITEM:/ITEMS:/HM/TM: marker anywhere in the step. 'name | source' when a
    pipe is present; otherwise name = remainder and source = the text before the
    marker (e.g. "PokeCenter: talk to Ace Trainer -> ITEM: Vs. Seeker")."""
    remainder = probe[marker.end():].strip()
    if not remainder:
        return None
    prefix = probe[: marker.start()].strip(_PREFIX_JUNK)
    if "|" in remainder:
        name, source = (piece.strip() for piece in remainder.split("|", 1))
    else:
        name, source = _strip_trailing_paren(remainder), prefix
    if not name:
        return None
    return ItemInfo(name=name, source=source)


def _classify(body: str, probe: str) -> tuple[str, BattleInfo | None, ItemInfo | None]:
    """Decide (kind, battle, item) for one step. `body` is the verbatim step text,
    `probe` is body with tags/bold markers (and any 'Optional:' prefix) removed."""
    low = probe.lower()
    if not probe:
        return "note", None, None                       # tag-only / decoration line
    if probe.startswith(">"):
        content = probe.lstrip("> ").strip()
        if content.lower().startswith("battle:"):
            battle = _parse_battle_fields(content[len("battle:"):].strip())
            if battle is not None:
                return "battle", battle, None
        return "note", None, None                       # malformed BATTLE / plain quote
    if low.startswith(("note:", "warning:", "reward:")):
        return "note", None, None

    markers = [m for m in (_ITEM_MARKER_RE.search(probe), _HM_MARKER_RE.search(probe)) if m]
    if markers:
        item = _parse_item_fields(probe, min(markers, key=lambda m: m.start()))
        if item is not None:
            return "item", None, item

    verb = _BATTLE_VERB_RE.search(probe)
    if verb:
        return "battle", BattleInfo(opponent=verb.group(1).strip(" .,")), None

    gives = _GIVES_RE.search(probe)
    if gives:
        name = _strip_trailing_paren(gives.group(1).strip(" .!"))
        source = probe[: gives.start()].strip(_PREFIX_JUNK) or probe
        if name:
            return "item", None, ItemInfo(name=name, source=source)

    if body.startswith("**") and probe.endswith(":"):
        return "note", None, None                       # '**1F NE:**' area label
    return "move", None, None


def _make_step(body: str, part_n: int, section: str, section_optional: bool) -> StoryStep:
    tags = _extract_tags(body)
    probe = _TAG_RE.sub("", body).replace("**", "").strip()
    optional = section_optional
    if probe.lower().startswith("optional:"):
        optional = True
        probe = probe[len("optional:"):].strip()
    kind, battle, item = _classify(body, probe)
    return StoryStep(kind=kind, text=body, part=part_n, section=section,
                     battle=battle, item=item, optional=optional, tags=tags)


# --------------------------------------------------------------------------
# document-level parse
# --------------------------------------------------------------------------

def parse_walkthrough(text: str) -> Walkthrough:
    """Parse the whole walkthrough doc. Tolerant: unknown lines become free-text
    'move' steps, empty sections are dropped, nothing raises."""
    parts: list[StoryPart] = []
    appendices: list[tuple[str, list[str]]] = []

    in_part = False
    in_appendix = False
    part_n, part_title = 0, ""
    sections: list[StorySection] = []
    sec_title: str | None = None
    sec_optional = False
    sec_steps: list[StoryStep] = []
    last_h3 = ""

    def close_section() -> None:
        nonlocal sec_title, sec_optional, sec_steps
        if sec_title is not None and sec_steps:
            sections.append(
                StorySection(title=sec_title, steps=tuple(sec_steps), optional=sec_optional)
            )
        sec_title, sec_optional, sec_steps = None, False, []

    def close_part() -> None:
        nonlocal in_part, sections, last_h3
        close_section()
        if in_part:
            parts.append(StoryPart(n=part_n, title=part_title, sections=tuple(sections)))
        sections, last_h3, in_part = [], "", False

    for raw in text.splitlines():
        line = raw.strip()
        if not line or _HRULE_RE.match(line):
            continue

        match = _PART_RE.match(line)
        if match:
            close_part()
            in_appendix = False
            in_part = True
            part_n, part_title = int(match.group(1)), match.group(2).strip()
            continue

        match = _H2_RE.match(line)
        if match:                                    # non-PART h2: appendix block
            close_part()
            in_appendix = True
            appendices.append((match.group(1).strip(), []))
            continue

        if in_appendix:
            appendices[-1][1].append(raw)
            continue
        if not in_part:                              # preamble before PART 1
            continue

        match = _SUBSECTION_RE.match(line)
        if match:                                    # '####' = sub-section of last '###'
            close_section()
            sub = match.group(1).strip()
            sec_title = f"{last_h3} / {sub}" if last_h3 else sub
            sec_optional = "optional" in sec_title.lower()
            continue

        match = _SECTION_RE.match(line)
        if match:
            close_section()
            last_h3 = match.group(1).strip()
            sec_title = last_h3
            sec_optional = "optional" in sec_title.lower()
            continue

        body = _strip_list_marker(line)
        if not body:
            continue
        if sec_title is None:                        # steps before any '###' (Part 21)
            sec_title, sec_optional = part_title or "(intro)", False
        sec_steps.append(_make_step(body, part_n, sec_title, sec_optional))

    close_part()
    return Walkthrough(
        parts=tuple(parts),
        appendices=tuple((title, "\n".join(lines).strip()) for title, lines in appendices),
    )


@lru_cache(maxsize=1)
def load_walkthrough(path: str | None = None) -> Walkthrough:
    """Load + cache the walkthrough. Missing file -> empty Walkthrough."""
    p = Path(path) if path else DEFAULT_WALKTHROUGH_PATH
    try:
        return parse_walkthrough(p.read_text(encoding="utf-8"))
    except OSError:
        return Walkthrough()
