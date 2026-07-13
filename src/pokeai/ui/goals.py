"""Milestone / achievement tracking for the dashboard's goal panel.

Turns the live game state into a checklist of Pokémon Red milestones so stream
viewers can see what the AI is working toward and how close it is. Goals are
"sticky" — once reached they stay checked for the rest of the session, even if
the AI later blacks out and reloads.

Pure logic, no UI dependency (testable without pygame).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from pokeai.emulator.state_reader import GameState


@dataclass
class _Ctx:
    badge_count: int
    party_count: int
    party_total_level: int
    maps_seen: set[int]


@dataclass
class Goal:
    key: str
    label: str
    done: bool = False


@dataclass
class _GoalDef:
    key: str
    label: str
    test: Callable[[_Ctx], bool]


# Ordered early/mid-game milestones, all observable from RAM state. Map IDs match
# pokeai.knowledge.game_data.MAP_NAMES.
_GOAL_DEFS: list[_GoalDef] = [
    _GoalDef("starter", "Get your first Pokémon", lambda c: c.party_count >= 1),
    _GoalDef("route1", "Set out on Route 1", lambda c: 0x0C in c.maps_seen),
    _GoalDef("viridian", "Reach Viridian City", lambda c: 0x01 in c.maps_seen),
    _GoalDef("forest", "Enter Viridian Forest", lambda c: 0x33 in c.maps_seen),
    _GoalDef("team10", "Train your team to Lv10+", lambda c: c.party_total_level >= 10),
    _GoalDef("pewter", "Reach Pewter City", lambda c: 0x02 in c.maps_seen),
    _GoalDef("badge1", "Win the Boulder Badge", lambda c: c.badge_count >= 1),
    _GoalDef("cerulean", "Reach Cerulean City", lambda c: 0x03 in c.maps_seen),
    _GoalDef("badge2", "Win the Cascade Badge", lambda c: c.badge_count >= 2),
    _GoalDef("vermilion", "Reach Vermilion City", lambda c: 0x05 in c.maps_seen),
    _GoalDef("badge3", "Win the Thunder Badge", lambda c: c.badge_count >= 3),
    _GoalDef("champion", "Become Champion (8 badges)", lambda c: c.badge_count >= 8),
]


@dataclass
class GoalTracker:
    goals: list[Goal] = field(default_factory=lambda: [Goal(d.key, d.label) for d in _GOAL_DEFS])
    maps_seen: set[int] = field(default_factory=set)
    #: (label, monotonic time) of the most recent unlock, for the celebration banner.
    last_unlock: tuple[str, float] | None = None

    def reset_run(self) -> None:
        for g in self.goals:
            g.done = False
        self.maps_seen.clear()
        self.last_unlock = None

    def observe(self, state: GameState) -> None:
        """Update progress from the current game state."""
        self.maps_seen.add(state.current_map)
        ctx = _Ctx(
            badge_count=state.badge_count,
            party_count=state.party_count,
            party_total_level=state.party_total_level,
            maps_seen=self.maps_seen,
        )
        for goal, gdef in zip(self.goals, _GOAL_DEFS):
            if not goal.done and gdef.test(ctx):
                goal.done = True
                self.last_unlock = (goal.label, time.monotonic())

    @property
    def completed(self) -> int:
        return sum(1 for g in self.goals if g.done)

    @property
    def total(self) -> int:
        return len(self.goals)

    def current_goal(self) -> str | None:
        """Label of the next unfinished milestone (the active objective)."""
        for g in self.goals:
            if not g.done:
                return g.label
        return None

    def recent_unlock(self, within_s: float = 6.0) -> str | None:
        """Label of a milestone unlocked within the last `within_s` seconds."""
        if self.last_unlock is None:
            return None
        label, t = self.last_unlock
        return label if (time.monotonic() - t) <= within_s else None
