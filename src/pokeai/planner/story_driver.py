"""G10 StoryDriver: the standing ADVANCE_STORY seam over the parsed walkthrough.

Pairs with planner/story_parser.py (the other half of ROADMAP G10). The parser
turns docs/Pokemon-FireRed-Walkthrough.md into typed StorySteps; this module
compiles each step into a pure `completes_when` predicate over a FACTS dict and
walks the steps in order. The driver never touches the emulator: callers
assemble facts from FireRedStateReader reads plus sets they maintain:

    facts = {
        "items": {item_id: qty},          # bag: reader.read_bag_pocket()/count_item()
        "current_map": (group, num),      # or packed (group << 8) | num
        "badges": 1,                      # reader.read_badges() popcount
        "flags": {0x820, ...},            # optional: set flag ids (reader.read_flag)
        "beaten_opponents": {"Brock"},    # caller-maintained battle results
        "events": {step_key, ...},        # caller-marked manual completions
    }

Predicate vocabulary, compiled FROM step content (CompiledStep.mode):
  * "item":   known item name -> completes when the id is in facts["items"]
  * "battle": opponent in facts["beaten_opponents"]; gym leaders also pass on
              facts["badges"] >= n or the badge flag id in facts["flags"]
  * "map":    move step naming a known map -> facts["current_map"] equals it
              (the LAST map named in the text wins: it reads as the destination)
  * "note":   non-actionable, completes immediately
  * "manual": no known fact source; completes only via facts["events"] or
              StoryDriver.mark_manual()
Every predicate also passes when the step's own key is in facts["events"], so a
stuck step can always be overridden. Predicates are pure (same facts, same
result) and never raise. Pure logic, no emulator/UI imports, like task_queue.py.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from pokeai.planner.story_parser import StoryStep, Walkthrough, load_walkthrough
from pokeai.planner.task import Task, TaskKind

MODES = ("item", "battle", "map", "note", "manual")

# Known Gen-3 (FRLG) item ids. OAK'S PARCEL / TOWN MAP / TEACHY TV / POKE BALL
# were discovered or verified live (emulator/firered_state_reader.py). Unknown
# names stay manual-mark: no id guessing.
ITEM_IDS: dict[str, int] = {
    "POKE BALL": 4,
    "POTION": 13,
    "ANTIDOTE": 14,
    "OAK'S PARCEL": 349,
    "TOWN MAP": 361,
    "TEACHY TV": 366,
}

# Known (mapGroup, mapNum) ids. ROUTE 1 / VIRIDIAN CITY are live-verified
# (agents/field_brain.py); the rest follow the same pokefirered map tables.
MAP_IDS: dict[str, tuple[int, int]] = {
    "PALLET TOWN": (3, 0),
    "VIRIDIAN CITY": (3, 1),
    "PEWTER CITY": (3, 2),
    "ROUTE 1": (3, 19),
    "ROUTE 2": (3, 20),
    "VIRIDIAN FOREST": (1, 0),
}

# Kanto gym leaders -> 1-based badge number. Badge flags are FLAG_BADGE01..08 =
# 0x820..0x827 (firered_state_reader.BADGE_FLAG_FIRST), so leader n's flag id
# is BADGE_FLAG_FIRST + n - 1.
BADGE_FLAG_FIRST = 0x820
GYM_BADGES: dict[str, int] = {
    "BROCK": 1, "MISTY": 2, "LT. SURGE": 3, "ERIKA": 4,
    "KOGA": 5, "SABRINA": 6, "BLAINE": 7, "GIOVANNI": 8,
}

# Accent/quote folding so doc spellings (e-acute in "Poke Ball", curly
# apostrophes) hit the ASCII table keys above. Codepoints: e-acute, E-acute,
# right single quote, left single quote.
_FOLD = {0xE9: "E", 0xC9: "E", 0x2019: "'", 0x2018: "'"}
_WS_RE = re.compile(r"\s+")


def _norm(text) -> str:
    """Uppercase, accent-folded, whitespace-collapsed form used for matching."""
    return _WS_RE.sub(" ", str(text).translate(_FOLD).upper()).strip()


_MAP_PATTERNS = [
    (re.compile(rf"\b{re.escape(name)}\b"), map_id)
    for name, map_id in MAP_IDS.items()
]


def item_id_for(name: str) -> int | None:
    """Known item id for a doc item name: exact normalized match, or a known
    name as a word-boundary PREFIX ("Teachy TV demonstration" -> TEACHY TV).
    Unknown names return None (the step becomes manual-mark)."""
    norm = _norm(name)
    for key, item_id in ITEM_IDS.items():
        if norm.startswith(key) and (len(norm) == len(key)
                                     or not norm[len(key)].isalnum()):
            return item_id
    return None


def map_id_for(text: str) -> tuple[int, int] | None:
    """The known map named LAST in `text` (reads as the destination), or None.
    Word-boundary matching keeps ROUTE 1 out of ROUTE 11 / ROUTE 22 etc."""
    norm = _norm(text)
    best, best_pos = None, -1
    for pattern, map_id in _MAP_PATTERNS:
        for match in pattern.finditer(norm):
            if match.start() > best_pos:
                best, best_pos = map_id, match.start()
    return best


# --------------------------------------------------------------------------
# facts readers (tolerant: any malformed fact just fails the predicate)
# --------------------------------------------------------------------------

def _as_map(value) -> tuple[int, int] | None:
    """Normalize a current_map fact: a (group, num) pair or a packed int."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return divmod(value, 256)
    if isinstance(value, (tuple, list)) and len(value) == 2:
        try:
            return int(value[0]), int(value[1])
        except (TypeError, ValueError):
            return None
    return None


def _has_item(facts: Mapping, item_id: int) -> bool:
    """True when the bag facts contain item_id: {id: qty} mapping or id set."""
    items = facts.get("items")
    if items is None:
        return False
    if isinstance(items, Mapping):
        return bool(items.get(item_id))
    return item_id in items


# --------------------------------------------------------------------------
# predicate factories (one per vocabulary mode)
# --------------------------------------------------------------------------

def _note_predicate() -> Callable[[Mapping], bool]:
    def completes(facts: Mapping) -> bool:
        return True
    return completes


def _item_predicate(item_id: int) -> Callable[[Mapping], bool]:
    def completes(facts: Mapping) -> bool:
        return _has_item(facts, item_id)
    return completes


def _map_predicate(map_id: tuple[int, int]) -> Callable[[Mapping], bool]:
    def completes(facts: Mapping) -> bool:
        return _as_map(facts.get("current_map")) == map_id
    return completes


def _battle_predicate(opponent: str) -> Callable[[Mapping], bool]:
    opp = _norm(opponent)
    badge_n = GYM_BADGES.get(opp)

    def completes(facts: Mapping) -> bool:
        beaten = facts.get("beaten_opponents") or ()
        if any(_norm(b) == opp for b in beaten):
            return True
        if badge_n is not None:
            if int(facts.get("badges") or 0) >= badge_n:
                return True
            if (BADGE_FLAG_FIRST + badge_n - 1) in (facts.get("flags") or ()):
                return True
        return False
    return completes


def _with_events(key: str, base: Callable[[Mapping], bool] | None,
                 ) -> Callable[[Mapping], bool]:
    """Final predicate: facts['events'] containing the step key always passes;
    otherwise defer to the compiled base (None = manual-only). Never raises."""
    def completes_when(facts: Mapping) -> bool:
        try:
            if key in (facts.get("events") or ()):
                return True
            return bool(base(facts)) if base is not None else False
        except Exception:
            return False
    return completes_when


# --------------------------------------------------------------------------
# compilation
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class CompiledStep:
    """One walkthrough step with its stable key and completion predicate."""

    key: str                                   # "part/section title/index"
    index: int                                 # step index within its section
    step: StoryStep
    mode: str                                  # one of MODES
    completes_when: Callable[[Mapping], bool]

    @property
    def auto(self) -> bool:
        """True when a game fact can complete this step without a manual mark."""
        return self.mode != "manual"


def compile_step(step: StoryStep, key: str, index: int = 0) -> CompiledStep:
    """Compile one StoryStep into (mode, completes_when) from its content."""
    mode: str = "manual"
    base: Callable[[Mapping], bool] | None = None
    if step.kind == "note":
        mode, base = "note", _note_predicate()
    elif step.kind == "item" and step.item is not None:
        item_id = item_id_for(step.item.name)
        if item_id is not None:
            mode, base = "item", _item_predicate(item_id)
    elif step.kind == "battle" and step.battle is not None:
        mode, base = "battle", _battle_predicate(step.battle.opponent)
    elif step.kind == "move":
        map_id = map_id_for(step.text)
        if map_id is not None:
            mode, base = "map", _map_predicate(map_id)
    return CompiledStep(key=key, index=index, step=step, mode=mode,
                        completes_when=_with_events(key, base))


def _compile(walkthrough: Walkthrough, start_part: int) -> list[CompiledStep]:
    """All steps of parts >= start_part, in doc order, with stable unique keys
    (a repeated section title within a part gets a '#2' style suffix)."""
    out: list[CompiledStep] = []
    for part in walkthrough.parts:
        if part.n < start_part:
            continue
        seen: dict[str, int] = {}
        for section in part.sections:
            n = seen.get(section.title, 0)
            seen[section.title] = n + 1
            title = section.title if n == 0 else f"{section.title}#{n + 1}"
            for i, step in enumerate(section.steps):
                out.append(compile_step(step, f"{part.n}/{title}/{i}", i))
    return out


# --------------------------------------------------------------------------
# the driver
# --------------------------------------------------------------------------

class StoryDriver:
    """Walks the walkthrough steps in order against caller-fed facts.

    Holds a cursor over the compiled steps. `advance(facts)` completes every
    consecutive step whose predicate passes and returns them. `to_task()`
    exposes the current step as the standing ADVANCE_STORY planner Task (note =
    step text, satisfied = the step's predicate); calling it every tick is
    dedupe-safe because equal step keys yield equal task ids. This is the seam
    stream.py's task tree and the FieldBrain 'progress' executor consume.
    """

    def __init__(self, walkthrough: Walkthrough | None = None,
                 start_part: int = 1):
        self.walkthrough = (walkthrough if walkthrough is not None
                            else load_walkthrough())
        self.start_part = start_part
        self.compiled: tuple[CompiledStep, ...] = tuple(
            _compile(self.walkthrough, start_part))
        self._cursor = 0
        self._manual: set[str] = set()

    # --- inspection ---

    def current(self) -> CompiledStep | None:
        """The compiled step the story is waiting on (None when finished)."""
        if self._cursor < len(self.compiled):
            return self.compiled[self._cursor]
        return None

    def current_step(self) -> StoryStep | None:
        """The parsed StoryStep the story is waiting on (None when finished)."""
        compiled = self.current()
        return compiled.step if compiled is not None else None

    def progress(self) -> dict:
        """{part, section, step_index, done_count, total} for the UI/boards."""
        compiled = self.current()
        return {
            "part": compiled.step.part if compiled else None,
            "section": compiled.step.section if compiled else None,
            "step_index": compiled.index if compiled else None,
            "done_count": self._cursor,
            "total": len(self.compiled),
        }

    def remaining(self, part_n: int) -> list[CompiledStep]:
        """Not-yet-completed steps of PART part_n, in order."""
        return [c for c in self.compiled[self._cursor:] if c.step.part == part_n]

    # --- completion ---

    def mark_manual(self, step_key: str) -> None:
        """Record that the caller completed a step the facts cannot verify."""
        self._manual.add(step_key)

    def _facts_with_manual(self, facts: Mapping) -> Mapping:
        if not self._manual:
            return facts
        merged = dict(facts)
        merged["events"] = set(merged.get("events") or ()) | self._manual
        return merged

    def advance(self, facts: Mapping | None) -> list[CompiledStep]:
        """Complete every consecutive step whose predicate passes against
        `facts` (plus any mark_manual events); return the newly completed
        steps. Stops at the first step that does not pass."""
        merged = self._facts_with_manual(facts or {})
        completed: list[CompiledStep] = []
        while True:
            compiled = self.current()
            if compiled is None or not compiled.completes_when(merged):
                return completed
            completed.append(compiled)
            self._cursor += 1

    # --- planner seam ---

    def to_task(self, base_priority: float = 1.0) -> Task | None:
        """The standing ADVANCE_STORY Task for the current step (None when the
        story is finished). satisfied() takes the same facts dict advance()
        does and honors later mark_manual() calls on this driver."""
        compiled = self.current()
        if compiled is None:
            return None

        def satisfied(facts, _compiled=compiled):
            try:
                return _compiled.completes_when(self._facts_with_manual(facts))
            except Exception:
                return False

        return Task(
            kind=TaskKind.ADVANCE_STORY,
            params={"step": compiled.key},
            base_priority=base_priority,
            source="story",
            note=compiled.step.text,
            satisfied=satisfied,
        )
