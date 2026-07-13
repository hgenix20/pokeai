"""BFS pathing over a walkability predicate (F2).

Pure logic: `bfs_path` takes a `passable(x, y) -> bool` callable (e.g.
FireRedVision.walkable) and finds a shortest 4-directional path of button
directions from start to goal. Because vision is authoritative (the collision
grid is exact), the agent plans a full path instead of bumping walls to learn
them — the core of "vision-authoritative navigation" in docs/FIRERED_REDESIGN.md.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Callable

_DIRS: dict[str, tuple[int, int]] = {
    "up": (0, -1),
    "down": (0, 1),
    "left": (-1, 0),
    "right": (1, 0),
}


def bfs_path(
    start: tuple[int, int],
    goal: tuple[int, int],
    passable: Callable[[int, int], bool],
    max_nodes: int = 20000,
    jump_ledges: dict[tuple[int, int], str] | None = None,
) -> list[str] | None:
    """Shortest list of directions from start to goal, or None if unreachable.

    The goal tile is reached even if it isn't itself `passable` (a warp/door/NPC
    tile may report blocked but is still a valid destination to step onto/face),
    while every intermediate tile must be passable.

    `jump_ledges` maps a one-way ledge tile -> the direction it is hopped. When a
    move would step INTO such a ledge in its hop direction, the agent jumps OVER
    it, landing 2 tiles away (a single button press), and the landing tile must
    be passable. This lets descents cross the one-way ledges that fence routes.
    """
    if start == goal:
        return []
    jl = jump_ledges or {}
    seen = {start}
    q: deque[tuple[tuple[int, int], list[str]]] = deque([(start, [])])
    nodes = 0
    while q and nodes < max_nodes:
        (x, y), path = q.popleft()
        nodes += 1
        for name, (dx, dy) in _DIRS.items():
            nxt = (x + dx, y + dy)
            # one-way ledge hop: pressing `name` into a ledge hopped in `name`
            # lands 2 tiles out in a single press.
            if jl.get(nxt) == name:
                land = (x + 2 * dx, y + 2 * dy)
                if land == goal:
                    return path + [name]
                if land in seen or not passable(*land):
                    continue
                seen.add(land)
                q.append((land, path + [name]))
                continue
            if nxt == goal:
                return path + [name]
            if nxt in seen or not passable(*nxt):
                continue
            seen.add(nxt)
            q.append((nxt, path + [name]))
    return None
