"""HeuristicAgent: scripted opening behavior only.

Scope (Phase 1): pipeline validation harness, not a general player.
Behavior:
  - In battle (battle_type != 0): mash A. This selects "Fight" then the
    first move repeatedly, which is enough to produce reward signal on
    wild encounters with the starter.
  - Out of battle: random walk biased toward UP, to push the agent out
    of the starting area and into grass tiles.

This is intentionally minimal. Anything more capable belongs in Phase 2.
"""
from __future__ import annotations

import numpy as np

from pokeai.agents.base import Agent
from pokeai.env.action_controller import Action
from pokeai.env.pokemon_red_env import OBS_FIELDS

_BATTLE_TYPE_IDX = OBS_FIELDS.index("battle_type")

# Bias overworld movement toward UP/DOWN/LEFT/RIGHT (no NOOP, A, or B spam).
_OVERWORLD_ACTIONS = [Action.UP, Action.DOWN, Action.LEFT, Action.RIGHT]
# Weight UP slightly higher to encourage leaving the starting room.
_OVERWORLD_WEIGHTS = [0.4, 0.2, 0.2, 0.2]


class HeuristicAgent(Agent):
    name = "heuristic"

    def __init__(self, seed: int = 42):
        self.rng = np.random.default_rng(seed)

    def act(self, observation: np.ndarray) -> int:
        battle_type = int(observation[_BATTLE_TYPE_IDX])
        if battle_type != 0:
            # In battle: spam A to advance dialogue and pick first move.
            self.thought = "In battle — mashing A to fight with first move"
            return int(Action.A)
        # Overworld: weighted random movement.
        choice = self.rng.choice(_OVERWORLD_ACTIONS, p=_OVERWORLD_WEIGHTS)
        direction = Action(int(choice)).name
        self.thought = f"Exploring — walking {direction} (UP-biased random walk)"
        return int(choice)
