"""ROM-free unit tests for FireRedVision (map-grid walkability).

A sparse-memory mock serves a hand-built map layout + collision grid through the
real vision reader, so the address-chain + bit math is verified on Windows
without mGBA.
"""
from __future__ import annotations

import numpy as np

from pokeai.emulator import firered_state_reader as fsr
from pokeai.perception.vision import FireRedVision, TileClass

LAYOUT = 0x08200000
MAPDATA = 0x08200100
WALL = 1 << 10  # collision bit set


class MockGBA:
    def __init__(self):
        self.mem: dict[int, int] = {}

    def w16(self, a, v):
        self.mem[a] = v & 0xFF
        self.mem[a + 1] = (v >> 8) & 0xFF

    def w32(self, a, v):
        self.w16(a, v & 0xFFFF)
        self.w16(a + 2, v >> 16)

    def read_byte(self, a):
        return self.mem.get(a, 0)

    def read_u16(self, a):
        return self.mem.get(a, 0) | (self.mem.get(a + 1, 0) << 8)

    def read_u32(self, a):
        return self.read_u16(a) | (self.read_u16(a + 2) << 16)


def _build(player_map=(1, 2)) -> MockGBA:
    m = MockGBA()
    # gMapHeader -> layout
    from pokeai.perception.vision import GMAPHEADER
    m.w32(GMAPHEADER + 0x00, LAYOUT)
    w, h = 4, 3
    m.w32(LAYOUT + 0x00, w)
    m.w32(LAYOUT + 0x04, h)
    m.w32(LAYOUT + 0x0C, MAPDATA)
    # collision grid:  row0 all wall; (2,1) wall; rest floor
    grid = [
        [1, 1, 1, 1],
        [0, 0, 1, 0],
        [0, 0, 0, 0],
    ]
    for y in range(h):
        for x in range(w):
            block = (WALL if grid[y][x] else 0) | 0x123  # metatile id in low bits
            m.w16(MAPDATA + 2 * (y * w + x), block)
    # player object coords = map coords + 7
    pmx, pmy = player_map
    m.w16(fsr.GOBJECT_EVENTS + fsr.OBJ_CUR_X_OFF, pmx + fsr.OBJ_COORD_BIAS)
    m.w16(fsr.GOBJECT_EVENTS + fsr.OBJ_CUR_Y_OFF, pmy + fsr.OBJ_COORD_BIAS)
    return m


def test_layout_and_player():
    v = FireRedVision(_build())
    assert v.layout() == (4, 3, MAPDATA)
    assert v.player_xy() == (1, 2)


def test_walkable_and_walls():
    v = FireRedVision(_build())
    assert v.walkable(0, 2) is True       # floor
    assert v.walkable(0, 0) is False      # wall row
    assert v.walkable(2, 1) is False      # internal wall
    assert v.tile_class(2, 1) == TileClass.WALL
    assert v.tile_class(0, 2) == TileClass.WALKABLE


def test_offmap_is_unknown_and_blocked():
    v = FireRedVision(_build())
    assert v.collision_at(-1, 0) is None
    assert v.walkable(99, 99) is False
    assert v.tile_class(5, 5) == TileClass.UNKNOWN


def test_walkable_neighbors_match_grid():
    v = FireRedVision(_build(player_map=(1, 2)))
    nb = v.walkable_neighbors()
    assert nb == {"up": True, "down": False, "left": True, "right": True}
    # down is off-map (y=3) -> blocked


def test_object_tiles_excludes_player_includes_npcs():
    from pokeai.perception.vision import OBJ_ACTIVE_BIT, OBJECT_EVENT_SIZE
    m = _build(player_map=(1, 2))
    base = fsr.GOBJECT_EVENTS
    # slot 0 = player (active) — must be excluded
    m.mem[base + 0 * OBJECT_EVENT_SIZE] = OBJ_ACTIVE_BIT
    # slot 1 = an NPC at map (3, 4) -> object coords (3+7, 4+7)
    a1 = base + 1 * OBJECT_EVENT_SIZE
    m.mem[a1] = OBJ_ACTIVE_BIT
    m.w16(a1 + fsr.OBJ_CUR_X_OFF, 3 + fsr.OBJ_COORD_BIAS)
    m.w16(a1 + fsr.OBJ_CUR_Y_OFF, 4 + fsr.OBJ_COORD_BIAS)
    # slot 2 = inactive (flags default 0) -> ignored
    tiles = FireRedVision(m).object_tiles()
    assert tiles == {(3, 4)}


def test_local_grid_centered_on_player():
    v = FireRedVision(_build(player_map=(1, 2)))
    g = v.local_grid(radius=1)
    expected = np.array([
        [TileClass.WALKABLE, TileClass.WALKABLE, TileClass.WALL],
        [TileClass.WALKABLE, TileClass.PLAYER, TileClass.WALKABLE],
        [TileClass.UNKNOWN, TileClass.UNKNOWN, TileClass.UNKNOWN],
    ], dtype=np.int8)
    assert np.array_equal(g, expected)
