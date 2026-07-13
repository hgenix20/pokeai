"""A remembered map of the world, in the game's own (map, x, y) coordinates.

The agent never sees the whole map at once — only the screen around it. The
WorldModel stitches those glimpses into a persistent memory keyed by the exact
position the game reports, so the agent can answer "where have I been, where is
a wall, where is a door, and what haven't I explored yet?" and plan a route.

How it learns each cell (no pixel calibration needed):
  - Standing on a tile proves it's a FLOOR.
  - The four tiles it currently faces are read from the semantic screen grid
    (the cells one step away in each direction) — fast vision-rate mapping.
  - Movement feedback is the ground truth that corrects vision: a step that
    leaves position unchanged means that neighbour is a WALL; a step that
    changes the current map means we just used a WARP (door/stairs/ledge).

Pure logic, no emulator or UI dependency, so it is unit-testable.
"""
from __future__ import annotations

from collections import deque
from enum import IntEnum

from pokeai.env.action_controller import Action

# Direction -> (dx, dy) in map coordinates (y grows south, matching the game).
DELTA: dict[Action, tuple[int, int]] = {
    Action.UP: (0, -1),
    Action.DOWN: (0, 1),
    Action.LEFT: (-1, 0),
    Action.RIGHT: (1, 0),
}
DIRECTIONS = list(DELTA.keys())

# Screen-grid cells (row, col) of the tile one step away in each direction. The
# player stands at the fixed centre block (rows 8-9, cols 8-9) of the 18x20
# grid, so the tile it faces is the row/col just beyond that block.
FACING_CELLS: dict[Action, list[tuple[int, int]]] = {
    Action.UP: [(7, 8), (7, 9)],
    Action.DOWN: [(10, 8), (10, 9)],
    Action.LEFT: [(8, 7), (9, 7)],
    Action.RIGHT: [(8, 10), (9, 10)],
}


class Cell(IntEnum):
    """What the agent knows about a map tile."""

    UNKNOWN = 0
    FLOOR = 1     # walkable ground we can stand on
    WALL = 2      # blocked — cannot move into it
    GRASS = 3     # walkable, but triggers wild encounters
    NPC = 4       # a person/object — walkable target you interact with (A)
    WARP = 5      # a door/staircase/ledge that moves you to another map


WALKABLE = {Cell.FLOOR, Cell.GRASS, Cell.NPC, Cell.WARP}


class WorldModel:
    """Persistent per-map memory of cells, with frontier + path queries."""

    def __init__(self) -> None:
        # map_id -> {(x, y): Cell}
        self.maps: dict[int, dict[tuple[int, int], Cell]] = {}

    # --- recording ---

    def _set(self, m: int, x: int, y: int, cell: Cell, *, overwrite: bool = True) -> None:
        grid = self.maps.setdefault(m, {})
        cur = grid.get((x, y), Cell.UNKNOWN)
        if not overwrite and cur != Cell.UNKNOWN:
            # Don't let soft vision downgrade a hard-won fact (e.g. a known WARP
            # or a WALL proven by bumping). Only fill if currently unknown.
            return
        grid[(x, y)] = cell

    def cell(self, m: int, x: int, y: int) -> Cell:
        return self.maps.get(m, {}).get((x, y), Cell.UNKNOWN)

    def observe(self, m: int, x: int, y: int, sem) -> None:
        """Record the tile we stand on and the four tiles we face, from the
        semantic screen grid `sem` (an 18x20 array of TileClass codes).

        Vision only ever asserts *positive* walkable facts (floor / grass / a
        person). It deliberately never marks a WALL: during cutscenes and menus
        the collision grid reads as walls everywhere, and trusting that would
        fabricate a boxed-in map. Walls are learned the reliable way — by
        bumping into them (`mark_blocked`)."""
        from pokeai.emulator.screen_reader import TileClass

        # We are standing here -> it is floor (a bump can never have been right).
        if self.cell(m, x, y) in (Cell.UNKNOWN, Cell.WALL):
            self._set(m, x, y, Cell.FLOOR)

        for action, cells in FACING_CELLS.items():
            dx, dy = DELTA[action]
            nx, ny = x + dx, y + dy
            classes = [int(sem[r, c]) for r, c in cells if 0 <= r < sem.shape[0] and 0 <= c < sem.shape[1]]
            if not classes:
                continue
            if any(cl == int(TileClass.GRASS) for cl in classes):
                self._set(m, nx, ny, Cell.GRASS, overwrite=False)
            elif any(cl == int(TileClass.NPC) for cl in classes):
                self._set(m, nx, ny, Cell.NPC, overwrite=False)
            elif any(cl == int(TileClass.WALKABLE) for cl in classes):
                self._set(m, nx, ny, Cell.FLOOR, overwrite=False)
            # all-WALL vision is ignored on purpose (see docstring).

        # Wide vision: the agent can SEE most of the screen, not just the tile it
        # faces, so record the whole visible region at once (positive facts only —
        # walls are still learned by bumping). This maps a room/town at a glance
        # instead of having to step on every tile. Screen↔map mapping: each map
        # tile is a 2x2 block in the 18x20 grid with the player tile at rows 8-9 /
        # cols 8-9 (consistent with FACING_CELLS), so map (x+dx, y+dy) lands at
        # block rows {8+2dy, 9+2dy}, cols {8+2dx, 9+2dx}.
        rows, cols = sem.shape
        _near = {(0, 0), (0, -1), (0, 1), (-1, 0), (1, 0)}  # already handled above
        for dy in range(-5, 6):
            for dx in range(-5, 6):
                if (dx, dy) in _near:
                    continue
                r0, r1, c0, c1 = 8 + 2 * dy, 9 + 2 * dy, 8 + 2 * dx, 9 + 2 * dx
                if not (0 <= r0 and r1 < rows and 0 <= c0 and c1 < cols):
                    continue
                block = [int(sem[r, c]) for r in (r0, r1) for c in (c0, c1)]
                nx, ny = x + dx, y + dy
                # Only record *static terrain* from a distance. NPCs are NOT
                # recorded here on purpose: people walk around, so a person seen
                # across the room is usually gone by the time we arrive — routing
                # to that ghost makes the agent circle an empty tile forever. NPCs
                # are only recorded from the immediately-faced tiles (above).
                if any(b == int(TileClass.GRASS) for b in block):
                    self._set(m, nx, ny, Cell.GRASS, overwrite=False)
                elif all(b == int(TileClass.WALKABLE) for b in block):
                    self._set(m, nx, ny, Cell.FLOOR, overwrite=False)
                # mixed / all-wall / npc vision ignored — walls proven by bumping.

    def mark_blocked(self, m: int, x: int, y: int, action: Action) -> None:
        """A move that didn't change position: the faced tile is a wall."""
        dx, dy = DELTA[action]
        self._set(m, x + dx, y + dy, Cell.WALL)

    def mark_warp(self, m: int, x: int, y: int, action: Action) -> None:
        """A move that changed the map: the tile we stepped onto is a warp."""
        dx, dy = DELTA[action]
        self._set(m, x + dx, y + dy, Cell.WARP)

    def mark_floor(self, m: int, x: int, y: int) -> None:
        self._set(m, x, y, Cell.FLOOR)

    # --- queries ---

    def walkable_dirs(self, m: int, x: int, y: int, *, include_warps: bool = True) -> list[Action]:
        """Directions whose neighbour is known-walkable (not a wall/unknown).
        With include_warps=False, a door/stairs tile is excluded — used by the
        idle wander so the agent never drifts into a building it's done with."""
        out = []
        for action in DIRECTIONS:
            dx, dy = DELTA[action]
            cell = self.cell(m, x + dx, y + dy)
            if cell not in WALKABLE:
                continue
            if not include_warps and cell == Cell.WARP:
                continue
            out.append(action)
        return out

    def is_frontier(self, m: int, x: int, y: int) -> bool:
        """A tile we can stand on (floor/grass) with at least one UNKNOWN
        neighbour — the edge of what we've explored, and worth heading toward.

        Warps and NPCs are excluded on purpose: a door's "unknown" neighbours are
        on another map (not ground to sweep here), so treating a door as frontier
        is what made the agent keep walking into buildings."""
        if self.cell(m, x, y) not in (Cell.FLOOR, Cell.GRASS):
            return False
        for action in DIRECTIONS:
            dx, dy = DELTA[action]
            if self.cell(m, x + dx, y + dy) == Cell.UNKNOWN:
                return True
        return False

    def has_frontier(self, m: int) -> bool:
        """True if this map still has any unexplored edge (a walkable tile with
        an unknown neighbour)."""
        return any(self.is_frontier(m, x, y) for (x, y) in self.maps.get(m, {}))

    def warp_tiles(self, m: int) -> list[tuple[int, int]]:
        return [xy for xy, c in self.maps.get(m, {}).items() if c == Cell.WARP]

    def npc_tiles(self, m: int) -> list[tuple[int, int]]:
        """Tiles holding a person/object we can walk up to and talk to (A).
        Talking is how the early game is unblocked (Pokédex, parcel, gym
        leaders), so the explorer routes to these once walking is exhausted."""
        return [xy for xy, c in self.maps.get(m, {}).items() if c == Cell.NPC]

    def _bfs(self, m: int, sx: int, sy: int, is_goal, *, blocked=()) -> list[Action] | None:
        """Shortest path (list of Actions) from (sx, sy) to the first cell that
        satisfies is_goal(x, y), walking only over known-walkable tiles. Returns
        None if no such cell is reachable. Only paths of length >= 1 are
        returned (the goal is sought among reachable *other* cells, so the agent
        always actually moves). Positions in `blocked` are never traversed (but
        may still be matched by is_goal as an endpoint)."""
        block = set(blocked)
        seen = {(sx, sy)}
        q: deque[tuple[int, int, list[Action]]] = deque([(sx, sy, [])])
        while q:
            x, y, path = q.popleft()
            for action in DIRECTIONS:
                dx, dy = DELTA[action]
                nx, ny = x + dx, y + dy
                if (nx, ny) in seen:
                    continue
                cell = self.cell(m, nx, ny)
                if cell not in WALKABLE:
                    continue
                npath = path + [action]
                if is_goal(nx, ny):
                    return npath
                seen.add((nx, ny))
                # Don't route *through* a warp tile (it would change maps) or an
                # NPC tile (a person blocks the square); both are only ever valid
                # as path endpoints, handled by is_goal above.
                if cell != Cell.WARP and (nx, ny) not in block:
                    q.append((nx, ny, npath))
        return None

    def path_to(self, m: int, sx: int, sy: int, tx: int, ty: int) -> list[Action] | None:
        return self._bfs(m, sx, sy, lambda x, y: x == tx and y == ty)

    def path_to_frontier(self, m: int, sx: int, sy: int) -> list[Action] | None:
        """Route to the nearest frontier tile (systematic exploration)."""
        return self._bfs(m, sx, sy, lambda x, y: self.is_frontier(m, x, y))

    def path_to_adjacent_npc(
        self, m: int, sx: int, sy: int, *, exclude=()
    ) -> list[Action] | None:
        """Route to the nearest walkable tile that *sits next to* a person/object
        we haven't handled yet (positions in `exclude` are ignored). The agent
        stands there and faces the NPC to talk — this is how it triggers the
        events that unblock progress once walking is exhausted."""
        ex = set(exclude)
        npcs = {xy for xy in self.npc_tiles(m) if xy not in ex}
        if not npcs:
            return None

        def adjacent_to_npc(x: int, y: int) -> bool:
            return any(
                (x + dx, y + dy) in npcs for dx, dy in DELTA.values()
            )

        # NPC tiles block movement, so never route through one (only stand beside).
        return self._bfs(m, sx, sy, adjacent_to_npc, blocked=npcs)

    def path_to_warp(self, m: int, sx: int, sy: int, *, exclude=()) -> list[Action] | None:
        """Route to the nearest known warp (e.g. the exit door of a building),
        excluding any positions in `exclude` (such as the warp we just came in
        through)."""
        ex = set(exclude)
        return self._bfs(
            m, sx, sy, lambda x, y: self.cell(m, x, y) == Cell.WARP and (x, y) not in ex
        )

    # --- stats (for the dashboard) ---

    def known_count(self, m: int) -> int:
        return len(self.maps.get(m, {}))

    def reset(self) -> None:
        self.maps.clear()
