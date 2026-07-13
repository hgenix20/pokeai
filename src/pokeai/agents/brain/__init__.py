"""GameSense: the shared "brain" the new strategies are born with.

This package is the game-literacy foundation that lets a strategy reason about
*the game* instead of relearning how to walk from tile to tile. It gives every
brain built on it three innate things a person picking up Pokemon already has:

  - world_model: a remembered map of where it has been (walls, paths, doors,
    warps, people) in the game's own (map, x, y) coordinates — so it can tell
    where it is and plan a route, instead of seeing only the screen in front of
    it. Learned with no pixel calibration: from the tiles it faces each step and
    from movement feedback (a move that fails is a wall; one that changes the
    map is a doorway).
  - navigator: breadth-first pathfinding over that remembered map — to a chosen
    target, or to the nearest frontier (the edge of the unknown) so exploration
    is systematic, not a random wander that gets stuck on a fence.

The affordances + goal manager (what A/B/people/doors mean, and what the agent
is trying to do) live alongside these and build on top.
"""
from __future__ import annotations

from pokeai.agents.brain.gamesense import GameSense
from pokeai.agents.brain.world_model import Cell, WorldModel

__all__ = ["Cell", "GameSense", "WorldModel"]
