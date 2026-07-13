"""Per-episode metrics record."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class TerminationReason(str, Enum):
    MAX_STEPS = "MAX_STEPS"
    BLACKOUT = "BLACKOUT"
    ALL_BADGES = "ALL_BADGES"
    MANUAL = "MANUAL"


@dataclass
class RunMetrics:
    run_id: str
    agent_name: str
    config_hash: str
    episode_index: int
    steps_taken: int
    badges_earned: int
    events_triggered: int
    unique_maps_visited: int
    total_party_level: int
    blackout_occurred: bool
    terminated_reason: TerminationReason
    cumulative_reward: float
    wall_clock_seconds: float
    # --- Skills-profile metrics ---
    # 5.1 Curiosity: unique positions visited this episode (should rise)
    unique_tiles_visited: int = 0
    # 5.2 Adaptability: fraction of steps repeating an action without moving
    # (should fall as anti-perseveration develops)
    repeat_action_rate: float = 0.0
    # Steps spent not moving at all (out of battle)
    total_steps_stuck: int = 0
    # Intrinsic reward earned this episode
    curiosity_reward_total: float = 0.0
    # 5.3 Adversity: recovered from <=25% HP back to >=50%
    recovered_from_low_hp: bool = False
    # 8.2 Strategic: enemy mons KO'd this episode (battle shaping, reward v2)
    battles_won: int = 0
    # 6.1 Learning Agility: exploration rate of the learner (None for non-RL agents)
    agent_epsilon: float | None = None
    # Mean TD loss over the episode (None for non-RL agents)
    agent_loss: float | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["terminated_reason"] = self.terminated_reason.value
        return d
