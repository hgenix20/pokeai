"""Agent interface. All agents implement act(observation) -> action."""
from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class Agent(ABC):
    """Abstract base for all agents.

    Phase 1 agents are stateless or near-stateless. Future RL/evo agents
    will extend this with learning hooks (observe_transition, train, etc.).
    """

    name: str = "base"

    #: Human-readable rationale for the most recent act() decision.
    #: Displayed in the dashboard's THOUGHTS panel. Agents should update
    #: this inside act().
    thought: str = ""

    @abstractmethod
    def act(self, observation: np.ndarray) -> int:
        """Return an integer action given the current observation."""
        ...

    def reset(self) -> None:
        """Reset any episode-scoped state. Default: no-op.

        Note: agents that carry *run-scoped* memory (e.g. a remembered world
        map) should KEEP it here and only wipe it in full_reset(), so knowledge
        accumulated over a run survives between episodes."""
        return None

    def full_reset(self) -> None:
        """Wipe run-scoped memory too (mirrors env.full_reset). Called by the
        loop on the periodic complete reset and when starting from the title
        screen. Default: no-op."""
        return None

    def attach_env(self, env) -> None:
        """Give the agent access to the live env (RAM, collision, memory).

        Called by the training loop and dashboard after the env is built.
        Agents that only consume the observation vector ignore this.
        """
        return None

    # --- Learning hooks (no-ops for non-learning agents) ---

    def observe(
        self,
        obs: np.ndarray,
        action: int,
        reward: float,
        next_obs: np.ndarray,
        terminated: bool,
    ) -> None:
        """Called after each env step with the transition. Learning agents
        store it and train; scripted agents ignore it."""
        return None

    def end_episode(self, episode_index: int, run_dir) -> None:
        """Called after each episode (checkpointing, schedule updates)."""
        return None
