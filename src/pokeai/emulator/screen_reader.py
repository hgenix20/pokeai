"""Screen perception: read what is actually on screen, like a human does.

Pokémon Red renders the visible screen into a RAM mirror, `wTileMap`
(0xC3A0, 20 cols x 18 rows), holding one character/tile code per cell. During
text and menus these codes are the Gen 1 *character map*, so decoding them
gives the literal text the player reads — dialogue, signs, menu options, battle
messages — plus the position of the menu cursor (the ▶ arrow, code 0xED).

This is the difference between an agent that "presses buttons blindly" and one
that can tell a wall from grass, knows a person is talking to it, and can read
which menu item it is pointing at.

Verified live against the ROM:
  - 0xC3A0 wTileMap decodes "Wild RATTATA appeared!" mid-battle.
  - 0xD535 wGrassTile = the tile id that means tall grass in the current map.
  - 0xED is the on-screen menu cursor arrow.

Pure-ish: only needs an EmulatorWrapper-like object with read_byte/read_range
and game_area_collision/visible_sprites, so it is testable with the mock.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

import numpy as np

# --- RAM addresses (pokered) ---
ADDR_TILEMAP = 0xC3A0          # wTileMap: 20x18 on-screen character/tile codes
TILEMAP_COLS, TILEMAP_ROWS = 20, 18
ADDR_GRASS_TILE = 0xD535       # wGrassTile: tile id meaning tall grass this map
ADDR_NUM_WARPS = 0xD3AE        # wNumberOfWarps on the current map
ADDR_CUR_TILESET = 0xD367      # wCurMapTileset

# Gen 1 character map (subset that appears on screen). Codes not listed are
# graphics (map tiles, box art, sprites) and decode to "" in text context.
SPACE = 0x7F
MENU_CURSOR = 0xED             # ▶ selection arrow

_CHARMAP: dict[int, str] = {SPACE: " "}
for _i in range(26):
    _CHARMAP[0x80 + _i] = chr(ord("A") + _i)   # A-Z
for _i in range(26):
    _CHARMAP[0xA0 + _i] = chr(ord("a") + _i)   # a-z
for _i in range(10):
    _CHARMAP[0xF6 + _i] = chr(ord("0") + _i)   # 0-9
_CHARMAP.update({
    0x9A: "(", 0x9B: ")", 0x9C: ":", 0x9D: ";", 0x9E: "[", 0x9F: "]",
    0xBA: "e", 0xBB: "'d", 0xBC: "'l", 0xBD: "'s", 0xBE: "'t", 0xBF: "'v",
    0xE0: "'", 0xE1: "PK", 0xE2: "MN", 0xE3: "-", 0xE4: "'r", 0xE5: "'m",
    0xE6: "?", 0xE7: "!", 0xE8: ".", 0xEF: "M", 0xF1: "x", 0xF2: ".",
    0xF3: "/", 0xF4: ",", 0xF5: "F", 0xF0: "$",
    MENU_CURSOR: ">",
})

# Box-border tile codes (dialogue / menu frames) — used to detect a frame, not
# rendered as text.
_BORDER = {0x79, 0x7A, 0x7B, 0x7C, 0x7D, 0x7E}


class TileClass(IntEnum):
    """Semantic class of a visible tile — what kind of thing it is."""

    UNKNOWN = 0
    WALKABLE = 1
    WALL = 2
    GRASS = 3      # wild-encounter tiles
    NPC = 4        # a person/object sprite (talk to it)
    PLAYER = 5     # the player's own tile (screen center)


class ScreenContext(IntEnum):
    """What kind of screen the agent is looking at right now."""

    FREE_ROAM = 0   # walking around, no text box
    DIALOGUE = 1    # a message is being shown (press A to continue)
    MENU = 2        # a selectable menu/list is open (a ▶ cursor is visible)
    BATTLE = 3      # in a battle


@dataclass(frozen=True)
class ScreenView:
    """A snapshot of what is on screen, decoded to human-readable form."""

    lines: tuple[str, ...]          # 18 decoded text rows (graphics blanked)
    context: ScreenContext
    text: str                       # all readable words on screen, joined
    dialogue: str                   # text inside the active box (bottom region)
    menu_options: tuple[str, ...]   # readable menu lines (right/bottom box)
    cursor_row: int                 # tilemap row of the ▶ cursor, or -1
    cursor_option: str              # the menu line the cursor points at, or ""

    @property
    def has_text(self) -> bool:
        return bool(self.text.strip())

    @property
    def asks_yes_no(self) -> bool:
        opts = " ".join(self.menu_options).upper()
        return "YES" in opts and "NO" in opts


def _decode_row(codes: list[int]) -> str:
    return "".join(_CHARMAP.get(c, "") if c not in _BORDER else "" for c in codes)


class ScreenReader:
    """Reads + interprets the on-screen tile/character buffer."""

    def __init__(self, emulator):
        self.emu = emulator

    # --- raw decode ---

    def _tilemap(self) -> list[int]:
        return self.emu.read_range(ADDR_TILEMAP, ADDR_TILEMAP + TILEMAP_COLS * TILEMAP_ROWS)

    def text_lines(self) -> list[str]:
        """18 rows of decoded text (graphics tiles render as spaces)."""
        buf = self._tilemap()
        out = []
        for r in range(TILEMAP_ROWS):
            row = buf[r * TILEMAP_COLS:(r + 1) * TILEMAP_COLS]
            out.append("".join(_CHARMAP.get(c, " ") if c not in _BORDER else " " for c in row))
        return out

    def view(self, in_battle: bool = False) -> ScreenView:
        """Decode the screen and classify what kind of screen it is."""
        buf = self._tilemap()
        rows = [buf[r * TILEMAP_COLS:(r + 1) * TILEMAP_COLS] for r in range(TILEMAP_ROWS)]
        lines = tuple(_decode_row(r).rstrip() for r in rows)

        # Find the menu cursor (▶) if present.
        cursor_row = -1
        for r, codes in enumerate(rows):
            if MENU_CURSOR in codes:
                cursor_row = r
                break

        # All readable words on screen.
        words = [w for line in lines for w in line.split() if any(ch.isalnum() for ch in w)]
        text = " ".join(words)

        # Dialogue text: readable letters in the bottom message box (rows 12-17).
        dialogue = " ".join(
            w for line in lines[12:] for w in line.split() if any(ch.isalnum() for ch in w)
        )

        # Menu options: non-empty readable lines (used when a cursor is visible).
        menu_options = tuple(line.strip() for line in lines if line.strip())
        cursor_option = ""
        if cursor_row >= 0:
            cursor_option = lines[cursor_row].replace(">", "").strip()

        # Classify the screen.
        if in_battle:
            context = ScreenContext.BATTLE
        elif cursor_row >= 0:
            context = ScreenContext.MENU
        elif dialogue:
            context = ScreenContext.DIALOGUE
        else:
            context = ScreenContext.FREE_ROAM

        return ScreenView(
            lines=lines,
            context=context,
            text=text,
            dialogue=dialogue,
            menu_options=menu_options,
            cursor_row=cursor_row,
            cursor_option=cursor_option,
        )

    # --- semantic tile map ---

    def semantic_tiles(self) -> np.ndarray:
        """18x20 grid of TileClass codes: what each visible tile *is*.

        Built from the walkability collision grid (walkable vs wall), the
        per-map grass tile, on-screen sprites (NPCs/objects), and the player
        at the fixed screen center.
        """
        grid = np.full((TILEMAP_ROWS, TILEMAP_COLS), int(TileClass.UNKNOWN), dtype=np.int8)

        collision = None
        if hasattr(self.emu, "game_area_collision"):
            collision = self.emu.game_area_collision()
        if collision is not None:
            coll = np.asarray(collision)
            for r in range(min(TILEMAP_ROWS, coll.shape[0])):
                for c in range(min(TILEMAP_COLS, coll.shape[1])):
                    grid[r, c] = int(TileClass.WALKABLE if coll[r][c] else TileClass.WALL)

        # Grass: on-screen tile id equals the map's grass tile.
        grass_tile = self.emu.read_byte(ADDR_GRASS_TILE)
        if grass_tile:
            buf = self._tilemap()
            for r in range(TILEMAP_ROWS):
                for c in range(TILEMAP_COLS):
                    if buf[r * TILEMAP_COLS + c] == grass_tile:
                        grid[r, c] = int(TileClass.GRASS)

        # NPCs / objects from on-screen sprites (pixel -> tile coords). The
        # player's own character is drawn at the fixed screen-center block, so
        # skip any sprite tile there — otherwise the agent "sees" itself as a
        # person standing in front of it.
        if hasattr(self.emu, "visible_sprites"):
            try:
                for sx, sy, _tid in self.emu.visible_sprites():
                    c, r = sx // 8, sy // 8
                    if c in (8, 9) and r in (7, 8, 9, 10):
                        continue  # the player's own sprite
                    if 0 <= r < TILEMAP_ROWS and 0 <= c < TILEMAP_COLS:
                        grid[r, c] = int(TileClass.NPC)
            except Exception:
                pass

        # Player occupies the fixed center block (rows 8-9, cols 8-9).
        for r in (8, 9):
            for c in (8, 9):
                grid[r, c] = int(TileClass.PLAYER)
        return grid

    def grass_nearby(self) -> bool:
        """True if a tall-grass tile is visible (training opportunity)."""
        grass_tile = self.emu.read_byte(ADDR_GRASS_TILE)
        if not grass_tile:
            return False
        return grass_tile in self._tilemap()
