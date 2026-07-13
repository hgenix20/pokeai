"""Tests for the GameSense WorldModel (remembered map + pathfinding)."""
from __future__ import annotations

import numpy as np

from pokeai.agents.brain.world_model import Cell, WorldModel
from pokeai.emulator.screen_reader import TileClass
from pokeai.env.action_controller import Action


def _sem_all(klass: TileClass) -> np.ndarray:
    """An 18x20 semantic grid filled with one class, player at the centre."""
    g = np.full((18, 20), int(klass), dtype=np.int8)
    for r in (8, 9):
        for c in (8, 9):
            g[r, c] = int(TileClass.PLAYER)
    return g


def test_standing_records_floor():
    wm = WorldModel()
    wm.observe(0, 5, 5, _sem_all(TileClass.WALKABLE))
    assert wm.cell(0, 5, 5) == Cell.FLOOR


def test_faces_record_walkable_neighbours_only():
    wm = WorldModel()
    g = _sem_all(TileClass.WALKABLE)
    # A wall ahead (going UP) must NOT be trusted from vision — it stays UNKNOWN
    # until we actually bump it. Walkable neighbours are recorded.
    for r, c in ((7, 8), (7, 9)):
        g[r, c] = int(TileClass.WALL)
    wm.observe(0, 5, 5, g)
    assert wm.cell(0, 5, 4) == Cell.UNKNOWN  # north: vision wall is ignored
    assert wm.cell(0, 5, 6) == Cell.FLOOR    # south: walkable recorded


def test_grass_neighbour_detected():
    wm = WorldModel()
    g = _sem_all(TileClass.WALKABLE)
    for r, c in ((10, 8), (10, 9)):  # facing DOWN
        g[r, c] = int(TileClass.GRASS)
    wm.observe(0, 5, 5, g)
    assert wm.cell(0, 5, 6) == Cell.GRASS


def test_wide_vision_maps_the_whole_visible_screen():
    """Vision records far tiles it can see, not just the one it faces, so a room
    is mapped at a glance. Map (x+dx, y+dy) is the 2x2 block at rows {8+2dy,
    9+2dy}, cols {8+2dx, 9+2dx}."""
    wm = WorldModel()
    g = _sem_all(TileClass.WALL)  # walls are ignored by vision (proven by bumping)
    # Make the tile 3 east + 2 north of the player walkable: dx=3, dy=-2.
    for r in (8 + 2 * -2, 9 + 2 * -2):       # rows 4,5
        for c in (8 + 2 * 3, 9 + 2 * 3):     # cols 14,15
            g[r, c] = int(TileClass.WALKABLE)
    wm.observe(0, 5, 5, g)
    assert wm.cell(0, 8, 3) == Cell.FLOOR    # (x+3, y-2) recorded from a distance
    assert wm.cell(0, 5, 5) == Cell.FLOOR    # standing tile
    assert wm.cell(0, 9, 3) == Cell.UNKNOWN  # a wall-only block stays unknown


def test_movement_feedback_marks_wall_and_warp():
    wm = WorldModel()
    wm.mark_blocked(0, 5, 5, Action.RIGHT)
    assert wm.cell(0, 6, 5) == Cell.WALL
    wm.mark_warp(0, 5, 5, Action.UP)
    assert wm.cell(0, 5, 4) == Cell.WARP


def test_blocked_overwrites_vision_floor():
    """A bump (ground truth) corrects an optimistic vision FLOOR."""
    wm = WorldModel()
    g = _sem_all(TileClass.WALKABLE)
    wm.observe(0, 5, 5, g)
    assert wm.cell(0, 6, 5) == Cell.FLOOR
    wm.mark_blocked(0, 5, 5, Action.RIGHT)
    assert wm.cell(0, 6, 5) == Cell.WALL


def test_frontier_detection():
    wm = WorldModel()
    wm.mark_floor(0, 5, 5)
    # (5,5) has all-unknown neighbours -> frontier.
    assert wm.is_frontier(0, 5, 5)
    # Surround it with known floor -> no longer a frontier.
    for x, y in ((4, 5), (6, 5), (5, 4), (5, 6)):
        wm.mark_floor(0, x, y)
    assert not wm.is_frontier(0, 5, 5)


def test_path_to_target_straight_line():
    wm = WorldModel()
    for x in range(5, 9):
        wm.mark_floor(0, x, 5)
    path = wm.path_to(0, 5, 5, 8, 5)
    assert path == [Action.RIGHT, Action.RIGHT, Action.RIGHT]


def test_path_routes_around_wall():
    wm = WorldModel()
    # Build an L: (5,5)->(5,6)->(6,6), with (6,5) a wall.
    for x, y in ((5, 5), (5, 6), (6, 6)):
        wm.mark_floor(0, x, y)
    wm.mark_blocked(0, 5, 5, Action.RIGHT)  # (6,5) wall
    path = wm.path_to(0, 5, 5, 6, 6)
    assert path == [Action.DOWN, Action.RIGHT]


def test_path_to_warp_excludes_entry():
    wm = WorldModel()
    for x in range(5, 9):
        wm.mark_floor(0, x, 5)
    wm.mark_warp(0, 5, 5, Action.LEFT)   # entry warp at (4,5)
    wm.mark_warp(0, 5, 5, Action.RIGHT)  # but that overwrites (6,5)... use distinct
    # Set a clean exit warp at (8,5) explicitly.
    wm._set(0, 8, 5, Cell.WARP)
    path = wm.path_to_warp(0, 5, 5, exclude={(4, 5)})
    assert path is not None and path[-1] == Action.RIGHT


def test_no_path_returns_none():
    wm = WorldModel()
    wm.mark_floor(0, 5, 5)
    # Target not connected to anything known.
    assert wm.path_to(0, 5, 5, 20, 20) is None


def test_has_frontier_and_warp_tiles():
    wm = WorldModel()
    wm.mark_floor(0, 5, 5)
    assert wm.has_frontier(0)  # lone floor has unknown neighbours
    # Box it in -> no frontier.
    for x, y in ((4, 5), (6, 5), (5, 4), (5, 6)):
        wm.mark_floor(0, x, y)
        for d in (Action.UP, Action.DOWN, Action.LEFT, Action.RIGHT):
            wm.mark_blocked(0, x, y, d)
    assert not wm.has_frontier(0)
    wm.mark_warp(0, 5, 5, Action.UP)  # warp at (5, 4)
    assert (5, 4) in wm.warp_tiles(0)


def test_walkable_dirs_can_exclude_warps():
    wm = WorldModel()
    wm.mark_floor(0, 5, 5)
    wm.mark_floor(0, 4, 5)            # walkable to the left
    wm._set(0, 6, 5, Cell.WARP)       # a door to the right
    assert set(wm.walkable_dirs(0, 5, 5)) == {Action.LEFT, Action.RIGHT}
    # The idle wander must never drift onto a door.
    assert wm.walkable_dirs(0, 5, 5, include_warps=False) == [Action.LEFT]


def test_npc_tiles_and_route_to_adjacent_npc():
    wm = WorldModel()
    # A short corridor of floor with a person standing at the end (8,5).
    for x in range(5, 8):
        wm.mark_floor(0, x, 5)
    wm._set(0, 8, 5, Cell.NPC)
    assert wm.npc_tiles(0) == [(8, 5)]
    # Route stops on the tile *next to* the NPC (7,5), never onto it.
    path = wm.path_to_adjacent_npc(0, 5, 5)
    assert path == [Action.RIGHT, Action.RIGHT]
    # Excluding that NPC leaves nobody to visit.
    assert wm.path_to_adjacent_npc(0, 5, 5, exclude={(8, 5)}) is None
