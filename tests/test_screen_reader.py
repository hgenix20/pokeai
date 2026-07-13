"""Tests for the screen perception layer (text decode + semantic tiles).

Uses the mock emulator, which writes text into the wTileMap RAM mirror the
same way the game does, so the real decoding logic is exercised without a ROM.
"""
from __future__ import annotations

import numpy as np

from pokeai.emulator.screen_reader import ScreenContext, ScreenReader, TileClass
from pokeai.emulator.screen_reader import MENU_CURSOR
from tests.mock_emulator import MockEmulator, encode_state


def _reader(**state_kw) -> ScreenReader:
    return ScreenReader(MockEmulator([encode_state(**state_kw)]))


class TestTextDecode:
    def test_reads_battle_message(self):
        sr = _reader(screen_text=["", "", "Wild RATTATA", "appeared!"])
        view = sr.view(in_battle=True)
        assert "Wild" in view.text and "RATTATA" in view.text and "appeared" in view.text
        assert view.context == ScreenContext.BATTLE

    def test_free_roam_when_no_text(self):
        sr = _reader()  # blank screen
        view = sr.view(in_battle=False)
        assert view.context == ScreenContext.FREE_ROAM
        assert not view.has_text

    def test_dialogue_detected_from_bottom_box(self):
        rows = [""] * 14 + ["Hello there!", "Welcome!"]
        sr = _reader(screen_text=rows)
        view = sr.view(in_battle=False)
        assert view.context == ScreenContext.DIALOGUE
        assert "Hello" in view.dialogue


class TestMenuCursor:
    def test_reads_menu_cursor_option(self):
        # The ▶ cursor (MENU_CURSOR) sits on the POKEMON row.
        rows = ["", ">POKEMON", " ITEM", " SAVE"]
        sr = ScreenReader(MockEmulator([encode_state(screen_text=rows)]))
        # Replace the '>' we wrote with the real cursor code so detection fires.
        from pokeai.emulator.screen_reader import ADDR_TILEMAP, TILEMAP_COLS
        sr.emu.snapshots[0][ADDR_TILEMAP + 1 * TILEMAP_COLS] = MENU_CURSOR
        view = sr.view(in_battle=False)
        assert view.context == ScreenContext.MENU
        assert view.cursor_row == 1
        assert "POKEMON" in view.cursor_option

    def test_yes_no_prompt(self):
        rows = [""] * 12 + ["Are you sure?", ">YES", " NO"]
        sr = ScreenReader(MockEmulator([encode_state(screen_text=rows)]))
        from pokeai.emulator.screen_reader import ADDR_TILEMAP, TILEMAP_COLS
        sr.emu.snapshots[0][ADDR_TILEMAP + 13 * TILEMAP_COLS] = MENU_CURSOR
        view = sr.view(in_battle=False)
        assert view.asks_yes_no


class TestSemanticTiles:
    def test_walkable_and_wall(self):
        grid = np.zeros((18, 20), dtype=np.uint32)
        grid[5, :] = 1  # walkable row
        sr = ScreenReader(MockEmulator([encode_state()], collision_grid=grid))
        sem = sr.semantic_tiles()
        assert sem[5, 0] == int(TileClass.WALKABLE)
        assert sem[0, 0] == int(TileClass.WALL)
        # Player always marked at the center block
        assert sem[8, 8] == int(TileClass.PLAYER)

    def test_grass_detected(self):
        grid = np.ones((18, 20), dtype=np.uint32)  # all walkable
        # One grass tile id (0x52) placed in the tilemap at (3, 4).
        sr = ScreenReader(MockEmulator([encode_state(grass_tile=0x52)], collision_grid=grid))
        from pokeai.emulator.screen_reader import ADDR_TILEMAP, TILEMAP_COLS
        sr.emu.snapshots[0][ADDR_TILEMAP + 3 * TILEMAP_COLS + 4] = 0x52
        sem = sr.semantic_tiles()
        assert sem[3, 4] == int(TileClass.GRASS)
        assert sr.grass_nearby()

    def test_player_sprite_not_marked_as_npc(self):
        # A sprite at the player's own block must NOT become an NPC tile.
        grid = np.ones((18, 20), dtype=np.uint32)
        sprites = [(72, 60, 1)]  # tile col 9, row 7 = the player's head
        emu = MockEmulator([encode_state()], collision_grid=grid)
        emu._sprites = sprites
        sr = ScreenReader(emu)
        sem = sr.semantic_tiles()
        assert int(sem[7, 9]) != int(TileClass.NPC)
