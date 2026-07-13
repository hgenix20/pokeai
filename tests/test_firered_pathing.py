"""ROM-free unit tests for the BFS pather."""
from __future__ import annotations

from pokeai.perception.pathing import bfs_path

# 5x5 grid; '#' blocked, '.' open.
GRID = [
    ".....",
    ".###.",
    ".#...",
    ".#.#.",
    "...#.",
]


def passable(x: int, y: int) -> bool:
    return 0 <= y < len(GRID) and 0 <= x < len(GRID[0]) and GRID[y][x] == "."


def _walk(start, path):
    d = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
    x, y = start
    for step in path:
        dx, dy = d[step]
        x, y = x + dx, y + dy
    return (x, y)


def test_trivial_same_tile():
    assert bfs_path((0, 0), (0, 0), passable) == []


def test_straight_line():
    p = bfs_path((0, 0), (4, 0), passable)
    assert p == ["right", "right", "right", "right"]


def test_around_obstacle_reaches_goal():
    start, goal = (0, 0), (4, 4)
    p = bfs_path(start, goal, passable)
    assert p is not None
    assert _walk(start, p) == goal
    assert all(passable(*_walk(start, p[:i])) for i in range(1, len(p)))


def test_shortest_length():
    p = bfs_path((0, 0), (0, 4), passable)
    assert p is not None and len(p) == 4


def test_unreachable_returns_none():
    walled = [".#.", ".#.", ".#."]

    def pa(x, y):
        return 0 <= y < 3 and 0 <= x < 3 and walled[y][x] == "."

    assert bfs_path((0, 0), (2, 0), pa) is None


def test_goal_may_be_blocked_but_reachable():
    p = bfs_path((0, 0), (1, 1), passable)  # (1,1) is '#'
    assert p is not None and _walk((0, 0), p) == (1, 1)
