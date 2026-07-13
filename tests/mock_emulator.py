"""Mock emulator + RAM encoder for testing without PyBoy or a ROM.

`encode_state` writes a desired GameState into a flat memory dict using the
same addresses the real StateReader reads from. The MockEmulator then serves
those bytes, so the real StateReader parsing logic (BCD, popcount, party
iteration) is exercised — only PyBoy itself is replaced.
"""
from __future__ import annotations

from pokeai.emulator import state_reader as SR


def encode_state(
    *,
    party_count: int = 1,
    party_hp: list[int] | None = None,       # current HP per slot
    party_max_hp: list[int] | None = None,   # max HP per slot
    party_levels: list[int] | None = None,   # level per slot
    party_species: list[int] | None = None,  # internal species ID per slot
    party_types: list[tuple[int, int]] | None = None,  # (type1, type2) per slot
    party_dvs: list[tuple[int, int]] | None = None,    # raw DV byte pair per slot
    party_moves: list[tuple[int, int, int, int]] | None = None,  # move IDs per slot
    party_pp: list[tuple[int, int, int, int]] | None = None,     # PP per slot
    money: int = 0,
    current_map: int = 0,
    y_pos: int = 0,
    x_pos: int = 0,
    badge_byte: int = 0x00,                  # raw badge bitfield
    event_bytes: list[int] | None = None,    # raw event flag bytes
    battle_type: int = 0,
    menu_cursor: int = 0,
    active_slot: int = 0,
    enemy_species: int = 0,
    enemy_hp: int = 0,
    enemy_max_hp: int = 0,
    enemy_level: int = 0,
    enemy_types: tuple[int, int] = (0, 0),
    enemy_status: int = 0,
    # Battle menu state (BattleMenus / BattleBrain driver)
    text_box_id: int = 1,
    top_menu_y: int = 0,
    top_menu_x: int = 0,
    cursor_item: int = 0,
    selected_move_id: int = 0,
    list_scroll_offset: int = 0,            # wListScrollOffset (bag/list menus)
    bag_items: list[tuple[int, int]] | None = None,  # (item_id, qty) pairs
    # Screen perception (ScreenReader)
    screen_text: list[str] | None = None,  # up to 18 rows of on-screen text
    grass_tile: int = 0,                    # wGrassTile id (0 = none this map)
) -> dict[int, int]:
    """Build a flat {addr: byte} dict representing one RAM snapshot."""
    mem: dict[int, int] = {}
    party_hp = party_hp or [20]
    party_max_hp = party_max_hp or [20]
    party_levels = party_levels or [5]
    party_species = party_species or []
    party_types = party_types or []
    party_dvs = party_dvs or []
    event_bytes = event_bytes or []

    mem[SR.ADDR_PARTY_COUNT] = party_count

    for i in range(min(party_count, 6)):
        base = SR.ADDR_PARTY_DATA_START + i * SR.PARTY_SLOT_SIZE
        hp = party_hp[i] if i < len(party_hp) else 0
        max_hp = party_max_hp[i] if i < len(party_max_hp) else 0
        lvl = party_levels[i] if i < len(party_levels) else 0
        mem[base + SR.PARTY_SLOT_OFFSET_HP] = (hp >> 8) & 0xFF
        mem[base + SR.PARTY_SLOT_OFFSET_HP + 1] = hp & 0xFF
        mem[base + SR.PARTY_SLOT_OFFSET_MAX_HP] = (max_hp >> 8) & 0xFF
        mem[base + SR.PARTY_SLOT_OFFSET_MAX_HP + 1] = max_hp & 0xFF
        mem[base + SR.PARTY_SLOT_OFFSET_LEVEL] = lvl & 0xFF
        if i < len(party_species):
            mem[base + SR.PARTY_SLOT_OFFSET_SPECIES] = party_species[i] & 0xFF
        if i < len(party_types):
            mem[base + SR.PARTY_SLOT_OFFSET_TYPE1] = party_types[i][0] & 0xFF
            mem[base + SR.PARTY_SLOT_OFFSET_TYPE2] = party_types[i][1] & 0xFF
        if i < len(party_dvs):
            mem[base + SR.PARTY_SLOT_OFFSET_DVS] = party_dvs[i][0] & 0xFF
            mem[base + SR.PARTY_SLOT_OFFSET_DVS + 1] = party_dvs[i][1] & 0xFF
        if party_moves and i < len(party_moves):
            for m in range(4):
                mem[base + SR.PARTY_SLOT_OFFSET_MOVES + m] = party_moves[i][m] & 0xFF
        if party_pp and i < len(party_pp):
            for m in range(4):
                mem[base + SR.PARTY_SLOT_OFFSET_PP + m] = party_pp[i][m] & 0xFF

    # Money as 3-byte BCD
    money = max(0, min(money, 999999))
    digits = f"{money:06d}"
    for j in range(3):
        hi = int(digits[j * 2])
        lo = int(digits[j * 2 + 1])
        mem[SR.ADDR_MONEY_START + j] = (hi << 4) | lo

    mem[SR.ADDR_CURRENT_MAP] = current_map
    mem[SR.ADDR_Y_POS] = y_pos
    mem[SR.ADDR_X_POS] = x_pos
    mem[SR.ADDR_BADGE_FLAGS] = badge_byte
    for k, b in enumerate(event_bytes):
        mem[SR.ADDR_EVENT_FLAGS_START + k] = b
    mem[SR.ADDR_BATTLE_TYPE] = battle_type  # now wIsInBattle (0/1/2)
    mem[SR.ADDR_MENU_CURSOR] = menu_cursor

    # Battle perception (wEnemyMon + active party slot)
    mem[SR.ADDR_PLAYER_MON_NUMBER] = active_slot & 0xFF
    mem[SR.ADDR_ENEMY_SPECIES] = enemy_species & 0xFF
    mem[SR.ADDR_ENEMY_HP] = (enemy_hp >> 8) & 0xFF
    mem[SR.ADDR_ENEMY_HP + 1] = enemy_hp & 0xFF
    mem[SR.ADDR_ENEMY_MAX_HP] = (enemy_max_hp >> 8) & 0xFF
    mem[SR.ADDR_ENEMY_MAX_HP + 1] = enemy_max_hp & 0xFF
    mem[SR.ADDR_ENEMY_LEVEL] = enemy_level & 0xFF
    mem[SR.ADDR_ENEMY_TYPE1] = enemy_types[0] & 0xFF
    mem[SR.ADDR_ENEMY_TYPE2] = enemy_types[1] & 0xFF
    mem[SR.ADDR_ENEMY_STATUS] = enemy_status & 0xFF

    # Battle menus (verified signatures; see state_reader address comments)
    mem[SR.ADDR_TEXT_BOX_ID] = text_box_id & 0xFF
    mem[SR.ADDR_TOP_MENU_ITEM_Y] = top_menu_y & 0xFF
    mem[SR.ADDR_TOP_MENU_ITEM_X] = top_menu_x & 0xFF
    mem[SR.ADDR_CURRENT_MENU_ITEM] = cursor_item & 0xFF
    mem[SR.ADDR_PLAYER_SELECTED_MOVE] = selected_move_id & 0xFF
    mem[SR.ADDR_LIST_SCROLL_OFFSET] = list_scroll_offset & 0xFF

    # Bag inventory: count byte, then (item_id, qty) pairs, then a terminator.
    if bag_items is not None:
        mem[SR.ADDR_NUM_BAG_ITEMS] = len(bag_items) & 0xFF
        for i, (item_id, qty) in enumerate(bag_items):
            mem[SR.ADDR_BAG_ITEMS + i * 2] = item_id & 0xFF
            mem[SR.ADDR_BAG_ITEMS + i * 2 + 1] = qty & 0xFF
        mem[SR.ADDR_BAG_ITEMS + len(bag_items) * 2] = SR.BAG_TERMINATOR

    # Screen perception: write text rows into wTileMap as Gen 1 charmap codes.
    from pokeai.emulator import screen_reader as _SCR

    mem[_SCR.ADDR_GRASS_TILE] = grass_tile & 0xFF
    if screen_text is not None:
        rev = {v: k for k, v in _SCR._CHARMAP.items()}  # char -> code
        for row, line in enumerate(screen_text[: _SCR.TILEMAP_ROWS]):
            base = _SCR.ADDR_TILEMAP + row * _SCR.TILEMAP_COLS
            for col in range(_SCR.TILEMAP_COLS):
                ch = line[col] if col < len(line) else " "
                mem[base + col] = rev.get(ch, _SCR.SPACE)
    return mem


class MockEmulator:
    """Serves scripted RAM snapshots. Advances one snapshot per `tick`.

    Implements the subset of EmulatorWrapper used downstream:
    load_state, save_state, press_button, tick, read_byte, read_range, close.
    """

    def __init__(
        self,
        snapshots: list[dict[int, int]],
        collision_grid=None,  # optional 18x20 walkability grid for tile-obs tests
    ):
        assert snapshots, "Need at least one snapshot"
        self.snapshots = snapshots
        self._idx = 0
        self.closed = False
        self.button_log: list[str] = []
        self._collision_grid = collision_grid

    # -- state mgmt --
    def load_state(self, state_path) -> None:
        self._idx = 0

    def save_state(self, state_path) -> None:
        pass

    # -- input/advance --
    def press_button(self, button: str) -> None:
        self.button_log.append(button)

    def press_button_held(self, button: str, frames: int) -> None:
        self.button_log.append(button)
        self.tick(frames)

    def press_button_pulse(self, button: str, frames: int, hold: int = 8) -> None:
        self.button_log.append(button)
        self.tick(frames)

    def tick(self, frames: int = 1) -> None:
        # Advance to next snapshot, clamping at the last one
        if self._idx < len(self.snapshots) - 1:
            self._idx += 1

    def set_speed(self, speed: int) -> None:
        self.speed = speed

    # -- memory --
    def _mem(self) -> dict[int, int]:
        return self.snapshots[self._idx]

    def read_byte(self, addr: int) -> int:
        return self._mem().get(addr, 0)

    def read_range(self, start: int, end: int) -> list[int]:
        # Mirror PyBoy: a zero-/negative-length slice is rejected, not empty.
        if start >= end:
            raise ValueError("Start address has to come before end address")
        m = self._mem()
        return [m.get(a, 0) for a in range(start, end)]

    # -- diagnostic / dashboard accessors (parity with EmulatorWrapper) --
    def screen_rgb(self):
        import numpy as np

        return np.zeros((144, 160, 3), dtype=np.uint8)

    def game_area(self):
        return None

    def game_area_collision(self):
        if self._collision_grid is not None:
            import numpy as np

            return np.asarray(self._collision_grid, dtype=np.uint32)
        return None

    def visible_sprites(self) -> list[tuple[int, int, int]]:
        return getattr(self, "_sprites", [])

    def close(self) -> None:
        self.closed = True
