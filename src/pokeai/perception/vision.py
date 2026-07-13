"""FireRed map-grid perception (F2) — walkability that is AUTHORITATIVE for nav.

Reads the current map's metatile/collision grid straight from RAM via the FireRed
map header, so the agent never has to bump a wall to learn it (docs/FIRERED_REDESIGN
.md §5.2). This is the GBA replacement for the Red build's PyBoy collision grid.

Address chain (CONFIRMED — Skeli789 BPRE.ld + live cross-check):
  gMapHeader @ 0x02036DFC
    +0x00 -> struct MapLayout* (ROM)
        +0x00 s32 width
        +0x04 s32 height
        +0x0C const u16 *map      (width*height metatiles, row-major)
  map u16: metatileId = bits 0-9, collision = bits 10-11, elevation = 12-15.
  Walkable <=> collision == 0. Verified live: the player's blocked direction (UP)
  matched collision==1 while the walkable directions matched collision==0.

Player map coords come from gObjectEvents[0] minus the +7 object bias (see
firered_state_reader). GRASS/WARP/NPC need metatile-behavior + object-event reads
and land in later F2 sub-steps; v1 is WALKABLE/WALL, which is what pathing needs.

Pure-ish: only needs an emulator with read_u16/read_u32, so it is mock-testable.
"""
from __future__ import annotations

from enum import IntEnum

import numpy as np

from pokeai.emulator.firered_state_reader import (
    GOBJECT_EVENTS, OBJ_COORD_BIAS, OBJ_CUR_X_OFF, OBJ_CUR_Y_OFF,
)

GMAPHEADER = 0x02036DFC
_MAPLAYOUT_PTR_OFF = 0x00      # in gMapHeader
_WIDTH_OFF = 0x00             # in MapLayout
_HEIGHT_OFF = 0x04
_MAP_OFF = 0x0C
_PRIM_TILESET_OFF = 0x10      # in MapLayout -> struct Tileset* (ROM)
_SEC_TILESET_OFF = 0x14

# FRLG struct Tileset: +0x14 = const u32 *metatileAttributes. (+0x10 is the
# tileset CALLBACK — a Thumb code pointer, hence odd — verified live 2026-07-03
# on Route 1 after first reading +0x10 and getting 0x8070169.)
_TS_ATTRS_OFF = 0x14

METATILE_ID_MASK = 0x03FF
COLLISION_SHIFT = 10
COLLISION_MASK = 0x3
NUM_PRIMARY_METATILES = 0x280

# Metatile BEHAVIOR = attribute u32 low bits (verified live: tall grass reads
# attr 0x01000202 -> behavior 0x02 = MB_TALL_GRASS; upper bits are terrain/
# encounter flags). Jump ledges are one-way hops; v1 treats them as UNWALKABLE
# so the pather routes around to the gap instead of bumping/desyncing.
BEHAVIOR_MASK = 0x1FF
MB_TALL_GRASS = 0x02
MB_JUMP_EAST, MB_JUMP_WEST, MB_JUMP_NORTH, MB_JUMP_SOUTH = 0x38, 0x39, 0x3A, 0x3B
LEDGE_BEHAVIORS = frozenset({MB_JUMP_EAST, MB_JUMP_WEST, MB_JUMP_NORTH, MB_JUMP_SOUTH})
# A jump ledge is one-way: you HOP it only by pressing INTO it from the tile on
# its near side, landing 2 tiles away. This maps the behavior to that direction.
LEDGE_DIR = {MB_JUMP_EAST: "right", MB_JUMP_WEST: "left",
             MB_JUMP_NORTH: "up", MB_JUMP_SOUTH: "down"}

# gObjectEvents[16] — NPCs/objects the static collision grid does NOT include.
# Each is 0x24 bytes; bit0 of byte 0 = active; currentCoords at +0x10/+0x12
# (object space, so subtract the +7 bias for map coords). Slot 0 is the player.
OBJECT_EVENT_SIZE = 0x24
OBJECT_EVENT_COUNT = 16
OBJ_ACTIVE_BIT = 0x01


class TileClass(IntEnum):
    """Semantic class of a tile (values compatible with the Red screen_reader)."""

    UNKNOWN = 0
    WALKABLE = 1
    WALL = 2
    GRASS = 3
    NPC = 4
    PLAYER = 5
    WARP = 6
    WATER = 7
    LEDGE = 8


class FireRedVision:
    """Live map-grid reader: walkability + a player-centered semantic window."""

    def __init__(self, emulator):
        self.emu = emulator
        # metatile-attribute cache: (attr_table_ptr, metatile_id) -> behavior.
        # Attributes live in ROM, so entries are valid for the whole session.
        self._behavior_cache: dict[tuple[int, int], int] = {}
        self._attr_tables_for: tuple[int, tuple[int, int]] | None = None
        self._nav_grid_for: tuple[int, dict] | None = None

    def layout(self) -> tuple[int, int, int]:
        """(width, height, map_ptr) for the current map."""
        ml = self.emu.read_u32(GMAPHEADER + _MAPLAYOUT_PTR_OFF)
        w = self.emu.read_u32(ml + _WIDTH_OFF)
        h = self.emu.read_u32(ml + _HEIGHT_OFF)
        m = self.emu.read_u32(ml + _MAP_OFF)
        return w, h, m

    # --- metatile behaviors (grass / ledges) ---

    def attr_tables(self) -> tuple[int, int]:
        """(primary, secondary) metatileAttributes pointers for the current map,
        cached per map-layout pointer."""
        ml = self.emu.read_u32(GMAPHEADER + _MAPLAYOUT_PTR_OFF)
        if self._attr_tables_for and self._attr_tables_for[0] == ml:
            return self._attr_tables_for[1]
        prim = self.emu.read_u32(ml + _PRIM_TILESET_OFF)
        sec = self.emu.read_u32(ml + _SEC_TILESET_OFF)
        tables = (self.emu.read_u32(prim + _TS_ATTRS_OFF) if prim else 0,
                  self.emu.read_u32(sec + _TS_ATTRS_OFF) if sec else 0)
        self._attr_tables_for = (ml, tables)
        return tables

    def behavior_of_block(self, block: int) -> int:
        """Metatile behavior byte for a raw map u16 (0 if unresolvable)."""
        mid = block & METATILE_ID_MASK
        pattr, sattr = self.attr_tables()
        table, idx = (pattr, mid) if mid < NUM_PRIMARY_METATILES else (
            sattr, mid - NUM_PRIMARY_METATILES)
        if not table:
            return 0
        key = (table, idx)
        if key not in self._behavior_cache:
            self._behavior_cache[key] = self.emu.read_u32(table + 4 * idx) & BEHAVIOR_MASK
        return self._behavior_cache[key]

    def behavior_at(self, x: int, y: int, layout=None) -> int | None:
        b = self.block_at(x, y, layout)
        return None if b is None else self.behavior_of_block(b)

    def player_xy(self) -> tuple[int, int]:
        x = self.emu.read_u16(GOBJECT_EVENTS + OBJ_CUR_X_OFF) - OBJ_COORD_BIAS
        y = self.emu.read_u16(GOBJECT_EVENTS + OBJ_CUR_Y_OFF) - OBJ_COORD_BIAS
        return x, y

    def object_tiles(self, include_player: bool = False) -> set[tuple[int, int]]:
        """Map coords occupied by active object events (NPCs/objects), which the
        static collision grid omits. The pather must avoid these or it desyncs
        trying to walk through an NPC. Excludes the player (slot 0) by default."""
        out: set[tuple[int, int]] = set()
        for i in range(OBJECT_EVENT_COUNT):
            if i == 0 and not include_player:
                continue  # slot 0 is the player
            addr = GOBJECT_EVENTS + i * OBJECT_EVENT_SIZE
            if not (self.emu.read_byte(addr) & OBJ_ACTIVE_BIT):
                continue
            x = self.emu.read_u16(addr + OBJ_CUR_X_OFF) - OBJ_COORD_BIAS
            y = self.emu.read_u16(addr + OBJ_CUR_Y_OFF) - OBJ_COORD_BIAS
            out.add((x, y))
        return out

    def block_at(self, x: int, y: int, layout: tuple[int, int, int] | None = None) -> int | None:
        w, h, m = layout or self.layout()
        if not (0 <= x < w and 0 <= y < h):
            return None  # off-map
        return self.emu.read_u16(m + 2 * (y * w + x))

    def collision_at(self, x: int, y: int, layout=None) -> int | None:
        b = self.block_at(x, y, layout)
        return None if b is None else (b >> COLLISION_SHIFT) & COLLISION_MASK

    def walkable(self, x: int, y: int, layout=None) -> bool:
        """Collision-free AND not a one-way jump ledge (v1: pather avoids ledges
        entirely and routes to the gap; directional hops are a later upgrade)."""
        b = self.block_at(x, y, layout)
        if b is None or ((b >> COLLISION_SHIFT) & COLLISION_MASK) != 0:
            return False
        try:
            return self.behavior_of_block(b) not in LEDGE_BEHAVIORS
        except Exception:
            return True   # mock/legacy emulators without attribute tables

    def tile_class(self, x: int, y: int, layout=None) -> TileClass:
        b = self.block_at(x, y, layout)
        if b is None:
            return TileClass.UNKNOWN
        try:
            beh = self.behavior_of_block(b)
        except Exception:
            beh = 0
        if ((b >> COLLISION_SHIFT) & COLLISION_MASK) != 0:
            # FRLG jump ledges are COLLISION-BLOCKED tiles with a jump behavior
            # (verified live: Route 1 ledge = block 0x0497, coll 1, behavior
            # 0x3B MB_JUMP_SOUTH). Pressing INTO one along its direction hops
            # it; BFS just routes around, but the class matters for the UI and
            # future hop-down shortcuts.
            return TileClass.LEDGE if beh in LEDGE_BEHAVIORS else TileClass.WALL
        if beh == MB_TALL_GRASS:
            return TileClass.GRASS
        return TileClass.WALKABLE

    def map_blocks(self, layout=None) -> list[int]:
        """The whole map's u16 blocks in ~8 bulk socket reads (row-major)."""
        w, h, m = layout or self.layout()
        raw = bytearray()
        total = w * h * 2
        for off in range(0, total, 0x100):
            end = min(off + 0x100, total)
            raw += bytes(self.emu.read_range(m + off, m + end))
        return [int.from_bytes(raw[i:i + 2], "little") for i in range(0, total, 2)]

    def nav_grid(self, use_cache: bool = True) -> dict:
        """Bulk navigation grid for the CURRENT map: {'w','h','walk','grass',
        'ledge'} where walk/grass/ledge are sets of (x,y). One map sweep plus a
        cached attribute lookup per unique metatile, instead of two socket
        round-trips per BFS-visited tile.

        CACHED per map-layout pointer: the metatile grid is STATIC within a map,
        and a full sweep costs ~10s of socket reads, so recomputing it every
        call (BFS, minimap tick) is wasteful. The cache invalidates naturally
        when the map-layout pointer changes (map transition)."""
        ml = self.emu.read_u32(GMAPHEADER + _MAPLAYOUT_PTR_OFF)
        if use_cache and self._nav_grid_for and self._nav_grid_for[0] == ml:
            return self._nav_grid_for[1]
        w, h, m = layout = self.layout()
        blocks = self.map_blocks(layout)
        walk, grass, ledge = set(), set(), set()
        ledge_dir: dict[tuple[int, int], str] = {}   # (x,y) -> hop direction
        for i, blk in enumerate(blocks):
            x, y = i % w, i // w
            try:
                beh = self.behavior_of_block(blk)
            except Exception:
                beh = 0
            if ((blk >> COLLISION_SHIFT) & COLLISION_MASK) != 0:
                if beh in LEDGE_BEHAVIORS:
                    ledge.add((x, y))   # blocked for BFS; hoppable along its dir
                    ledge_dir[(x, y)] = LEDGE_DIR[beh]
                continue
            walk.add((x, y))
            if beh == MB_TALL_GRASS:
                grass.add((x, y))
        grid = {"w": w, "h": h, "walk": walk, "grass": grass, "ledge": ledge,
                "ledge_dir": ledge_dir}
        self._nav_grid_for = (ml, grid)
        return grid

    def local_grid(self, radius: int = 5) -> np.ndarray:
        """(2r+1)x(2r+1) TileClass grid in MAP coords centered on the player.

        Authoritative: a cell marked WALL is never walked into by the pather. The
        player sits at the centre as PLAYER. Off-map cells read UNKNOWN.
        """
        layout = self.layout()
        px, py = self.player_xy()
        n = 2 * radius + 1
        grid = np.full((n, n), int(TileClass.UNKNOWN), dtype=np.int8)
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                grid[dy + radius, dx + radius] = int(self.tile_class(px + dx, py + dy, layout))
        grid[radius, radius] = int(TileClass.PLAYER)
        return grid

    def walkable_neighbors(self, x: int | None = None, y: int | None = None) -> dict[str, bool]:
        """Which of the 4 directions are walkable from (x,y) (default: player)."""
        layout = self.layout()
        if x is None or y is None:
            x, y = self.player_xy()
        return {
            "up": self.walkable(x, y - 1, layout),
            "down": self.walkable(x, y + 1, layout),
            "left": self.walkable(x - 1, y, layout),
            "right": self.walkable(x + 1, y, layout),
        }
