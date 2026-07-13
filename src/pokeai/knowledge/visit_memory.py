"""Visit memory: per-position visit counts across episodes.

This is the spatial memory the agent accumulates over a run — which maps and
tiles it has seen, and how often. The dashboard's MEMORY panel reads it to show
what the AI "knows"; Phase 2A-2 will reuse it as the count-based curiosity
signal (bonus ~ 1/sqrt(visit_count)).

Pure logic, no UI or emulator dependency.
"""
from __future__ import annotations

from collections import Counter

Position = tuple[int, int, int]  # (map_id, x, y)


class VisitMemory:
    """Counts visits to (map, x, y) positions, per-episode and per-run."""

    def __init__(self):
        self.run_counts: Counter[Position] = Counter()
        self.episode_counts: Counter[Position] = Counter()
        self.maps_seen_run: set[int] = set()
        self.maps_seen_episode: set[int] = set()

    def reset_episode(self) -> None:
        """New episode: clear episode-scoped memory, keep run-scoped memory."""
        self.episode_counts.clear()
        self.maps_seen_episode.clear()

    def reset_run(self) -> None:
        """Complete reset: forget everything, run- and episode-scoped. Used by
        the periodic full-reset so curiosity starts from a blank slate."""
        self.run_counts.clear()
        self.episode_counts.clear()
        self.maps_seen_run.clear()
        self.maps_seen_episode.clear()

    def record(self, map_id: int, x: int, y: int) -> None:
        pos = (map_id, x, y)
        self.run_counts[pos] += 1
        self.episode_counts[pos] += 1
        self.maps_seen_run.add(map_id)
        self.maps_seen_episode.add(map_id)

    def visit_count(self, map_id: int, x: int, y: int) -> int:
        """How many times this exact position was visited this run."""
        return self.run_counts[(map_id, x, y)]

    @property
    def unique_positions_run(self) -> int:
        return len(self.run_counts)

    @property
    def unique_positions_episode(self) -> int:
        return len(self.episode_counts)

    @property
    def total_steps_run(self) -> int:
        return sum(self.run_counts.values())

    def top_visited(self, n: int = 3) -> list[tuple[Position, int]]:
        """Most-visited positions this run (loop/stuck hotspots)."""
        return self.run_counts.most_common(n)

    def novelty(self, map_id: int, x: int, y: int) -> float:
        """1.0 = never seen, approaches 0 as visits grow. (2A-2 curiosity shape.)"""
        count = self.run_counts[(map_id, x, y)]
        return 1.0 / (1.0 + count) ** 0.5
