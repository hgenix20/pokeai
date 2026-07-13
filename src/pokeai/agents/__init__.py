"""Agent factory. Maps config.agent.type -> instantiated Agent."""
from __future__ import annotations

from pokeai.agents.base import Agent
from pokeai.agents.heuristic_agent import HeuristicAgent
from pokeai.agents.random_agent import RandomAgent
from pokeai.config import Config


def build_agent(config: Config) -> Agent:
    """Build the configured agent. Takes the full Config because learning
    agents need environment (obs dims) + training hyperparameters."""
    agent_type = config.agent.type
    seed = config.agent.seed

    if agent_type == "random":
        return RandomAgent(seed=seed)
    if agent_type == "heuristic":
        return HeuristicAgent(seed=seed)
    if agent_type == "strategist":
        from pokeai.agents.strategist_agent import StrategistAgent

        return StrategistAgent(seed=seed)
    # The three game-playing brains (GameSense-based; replace the old learners).
    if agent_type == "planner":
        from pokeai.agents.brain_agents import PlannerAgent

        return PlannerAgent(seed=seed)
    if agent_type == "tactician":
        from pokeai.agents.brain_agents import BattleTacticianAgent

        return BattleTacticianAgent(seed=seed)
    if agent_type == "learner":
        from pokeai.agents.brain_agents import LearnerAgent

        return LearnerAgent(seed=seed)
    if agent_type == "catcher":
        from pokeai.agents.brain_agents import CatcherAgent

        return CatcherAgent(seed=seed)
    if agent_type == "adventurer":
        from pokeai.agents.brain_agents import AdventurerAgent

        return AdventurerAgent(seed=seed)
    raise ValueError(f"Unknown agent type: {agent_type}")
