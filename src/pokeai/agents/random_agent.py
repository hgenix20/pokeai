"""RandomAgent: uniform random over the discrete action space."""
from __future__ import annotations

import numpy as np

from pokeai.agents.base import Agent
from pokeai.env.action_controller import ACTION_SPACE_SIZE, Action


class RandomAgent(Agent):
    name = "random"

    def __init__(self, seed: int = 42):
        self.rng = np.random.default_rng(seed)

    def act(self, observation: np.ndarray) -> int:
        action = int(self.rng.integers(0, ACTION_SPACE_SIZE))
        self.thought = f"No strategy — trying {Action(action).name} at random"
        return action
