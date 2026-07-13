"""Thought narration: turns state transitions into human-readable "AI thoughts".

Two thought sources feed the dashboard's THOUGHTS panel:
  1. The agent's own decision rationale (Agent.thought, set in act()).
  2. Event thoughts generated here by diffing consecutive GameStates —
     new maps, getting stuck, battles, damage, catching Pokemon, blackouts.

Pure logic, no UI dependency (testable without pygame).
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from pokeai.emulator.state_reader import GameState
from pokeai.knowledge.game_data import map_name, species_name


@dataclass(frozen=True)
class Thought:
    step: int
    text: str
    kind: str  # "agent" | "event" | "alert"


class ThoughtTracker:
    """Watches consecutive states and produces event thoughts."""

    # Steps without position/map change before we call it "stuck"
    STUCK_THRESHOLD = 8

    def __init__(self, max_thoughts: int = 50):
        self.thoughts: deque[Thought] = deque(maxlen=max_thoughts)
        self._prev: GameState | None = None
        self._prev_species: set[int] = set()
        self._steps_stuck = 0
        self._stuck_reported = False
        self._blackout_reported = False

    def reset_episode(self) -> None:
        self._prev = None
        self._prev_species = set()
        self._steps_stuck = 0
        self._stuck_reported = False
        self._blackout_reported = False
        self.thoughts.clear()

    @property
    def steps_stuck(self) -> int:
        return self._steps_stuck

    def add_agent_thought(self, step: int, text: str) -> None:
        if text:
            self.thoughts.appendleft(Thought(step, text, "agent"))

    def observe(self, step: int, state: GameState, party_species: list[int] | None = None) -> None:
        """Diff against the previous state and emit event thoughts."""
        prev = self._prev
        self._prev = state
        species_now = set(party_species or [])

        if prev is None:
            self._prev_species = species_now
            self._add(step, f"Waking up in {map_name(state.current_map)}", "event")
            return

        # --- Movement / stuck detection ---
        moved = (
            state.x_pos != prev.x_pos
            or state.y_pos != prev.y_pos
            or state.current_map != prev.current_map
        )
        if moved:
            if self._stuck_reported:
                self._add(step, "Finally moving again!", "event")
            self._steps_stuck = 0
            self._stuck_reported = False
        elif state.battle_type == 0:
            # Only count stuck steps outside of battle (battles legitimately hold position)
            self._steps_stuck += 1
            if self._steps_stuck >= self.STUCK_THRESHOLD and not self._stuck_reported:
                self._add(
                    step,
                    f"I'm stuck — {self._steps_stuck} steps without moving "
                    f"at ({state.x_pos},{state.y_pos})",
                    "alert",
                )
                self._stuck_reported = True

        # --- Map discovery ---
        if state.current_map != prev.current_map:
            self._add(step, f"Entered {map_name(state.current_map)}", "event")

        # --- Battle transitions ---
        if prev.battle_type == 0 and state.battle_type != 0:
            self._add(step, "A battle started!", "event")
        elif prev.battle_type != 0 and state.battle_type == 0:
            self._add(step, "Battle is over", "event")

        # --- Party changes (caught/received a Pokemon) ---
        new_species = species_now - self._prev_species
        for sp in new_species:
            self._add(step, f"Got a Pokemon: {species_name(sp)}!", "event")
        if state.party_count > prev.party_count and not new_species:
            self._add(step, "My party grew!", "event")
        self._prev_species = species_now

        # --- Health ---
        if state.party_count > 0 and prev.party_count > 0:
            if state.party_total_hp < prev.party_total_hp:
                frac = (
                    state.party_total_hp / state.party_total_max_hp
                    if state.party_total_max_hp
                    else 0
                )
                if frac <= 0.25 and state.party_total_hp > 0:
                    self._add(
                        step,
                        f"Taking damage — HP critical "
                        f"({state.party_total_hp}/{state.party_total_max_hp})",
                        "alert",
                    )
            if state.all_party_fainted and not self._blackout_reported:
                self._add(step, "Everything went black...", "alert")
                self._blackout_reported = True

        # --- Progress ---
        if state.badge_count > prev.badge_count:
            self._add(step, f"EARNED A BADGE! ({state.badge_count} total)", "event")
        if state.event_flags_set > prev.event_flags_set:
            delta = state.event_flags_set - prev.event_flags_set
            self._add(step, f"Something happened (+{delta} game events)", "event")
        if state.money > prev.money:
            self._add(step, f"Got ${state.money - prev.money}", "event")
        elif state.money < prev.money:
            self._add(step, f"Lost ${prev.money - state.money}", "event")

    def _add(self, step: int, text: str, kind: str) -> None:
        self.thoughts.appendleft(Thought(step, text, kind))
