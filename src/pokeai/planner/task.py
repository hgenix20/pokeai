"""The Task model for the planner (F4, docs/FIRERED_REDESIGN.md §6.1).

A Task is one durable intent ("buy 2 Antidotes", "reach Pewter City", "use Cut on
that tree"). Tasks carry a live priority, a status, dependencies on other tasks,
and two predicates over the game state: `satisfied` (auto-complete) and
`still_relevant` (auto-abandon). Skills execute tasks; this module only models
them.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskKind(Enum):
    ADVANCE_STORY = "advance_story"     # do the current walkthrough step
    NAVIGATE_TO = "navigate_to"         # reach a map / landmark / coords
    FIND_POKEMON = "find_pokemon"       # encounter + catch a species
    EARN_MONEY = "earn_money"           # reach a money floor
    BUY_ITEM = "buy_item"               # purchase N of an item
    HEAL = "heal"                       # restore the party
    USE_FIELD_MOVE = "use_field_move"   # cut/surf/strength at a tile
    OBTAIN_HM = "obtain_hm"             # acquire an HM
    TEACH_MOVE = "teach_move"           # teach a move to a party mon
    DEFEAT_TRAINER = "defeat_trainer"   # beat a specific/blocking trainer
    GRIND_TO_LEVEL = "grind_to_level"   # train the party to a level floor
    RECOVER = "recover"                 # respond to a detected setback


class TaskStatus(Enum):
    PENDING = "pending"      # ready to run once deps are met
    ACTIVE = "active"        # currently being executed
    BLOCKED = "blocked"      # waiting on dependency tasks
    DONE = "done"
    FAILED = "failed"
    ABANDONED = "abandoned"  # no longer relevant


# statuses that still count as "open work"
OPEN = (TaskStatus.PENDING, TaskStatus.ACTIVE, TaskStatus.BLOCKED)
CLOSED = (TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.ABANDONED)


def task_id(kind: TaskKind, params: dict | None = None) -> str:
    """Canonical id = the dedup identity of a task (same kind + params -> same id)."""
    params = params or {}
    body = ",".join(f"{k}={params[k]}" for k in sorted(params))
    return f"{kind.value}({body})"


@dataclass
class Task:
    kind: TaskKind
    params: dict = field(default_factory=dict)
    base_priority: float = 0.0
    priority: float | None = None           # live priority (defaults to base)
    status: TaskStatus = TaskStatus.PENDING
    depends_on: list[str] = field(default_factory=list)  # task ids
    source: str = "planner"                 # story|roots|vision|disruption|crowd|planner
    progress: float = 0.0                   # 0..1, for the UI
    note: str = ""
    satisfied: Callable[[Any], bool] | None = None      # done when this holds
    still_relevant: Callable[[Any], bool] | None = None  # else abandon
    id: str = ""
    seq: int = 0                            # insertion order (set by the queue)

    def __post_init__(self):
        if self.priority is None:
            self.priority = self.base_priority
        if not self.id:
            self.id = task_id(self.kind, self.params)

    def is_satisfied(self, state) -> bool:
        try:
            return bool(self.satisfied(state)) if self.satisfied else False
        except Exception:
            return False

    def is_relevant(self, state) -> bool:
        try:
            return bool(self.still_relevant(state)) if self.still_relevant else True
        except Exception:
            return True

    def label(self) -> str:
        p = " ".join(f"{k}={v}" for k, v in self.params.items())
        return f"{self.kind.value}{(' ' + p) if p else ''}"
