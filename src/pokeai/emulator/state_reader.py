"""RAM-based state reader for Pokémon Red.

Addresses verified against the Pokémon Red/Blue RAM map (Data Crystal).
Each Pokémon party slot is 44 bytes. Offsets within the slot:
  +0x00: Species
  +0x01: HP (current, 2 bytes big-endian)
  +0x03: Level (combat-displayed level at +0x21 also valid)
  +0x04: Status condition
  +0x22: Max HP (2 bytes big-endian)
  +0x21: Level (when in party)
"""
from __future__ import annotations

from dataclasses import dataclass

from pokeai.emulator.pyboy_wrapper import EmulatorWrapper

# --- RAM addresses (Pokémon Red, US/EU) ---
ADDR_PARTY_COUNT = 0xD163
ADDR_PARTY_DATA_START = 0xD16B  # 44 bytes per slot, 6 slots = 264 bytes
ADDR_PARTY_DATA_END = 0xD273
ADDR_MONEY_START = 0xD347  # 3 bytes, BCD
ADDR_CURRENT_MAP = 0xD35E
ADDR_Y_POS = 0xD361
ADDR_X_POS = 0xD362
ADDR_BADGE_FLAGS = 0xD356
ADDR_EVENT_FLAGS_START = 0xD747
ADDR_EVENT_FLAGS_END = 0xD7F7  # exclusive (176 bytes)
# Battle detection: wIsInBattle. Verified live — the previously-used 0xCFC4 read
# 0 during a real wild battle (unreliable). 0 = not in battle, 1 = wild, 2 = trainer.
ADDR_IS_IN_BATTLE = 0xD057
ADDR_BATTLE_TYPE = ADDR_IS_IN_BATTLE  # GameState.battle_type now carries wIsInBattle
ADDR_MENU_CURSOR = 0xCC26
ADDR_PLAYER_MON_NUMBER = 0xCC2F  # wPlayerMonNumber: active party slot during battle

# Battle menu navigation (verified live via scripts/probe_battle_ram.py):
# wTextBoxID == 11 whenever a battle menu is awaiting input (it returns to 1
# during text/animations, while the wTopMenuItem*/wCurrentMenuItem cells go
# stale — so wTextBoxID is the "menu open NOW" signal).
#   Action menu (FIGHT/PkMn/ITEM/RUN): top_y=14, top_x=9 (left col: FIGHT top,
#     ITEM bottom) or top_x=15 (right col: PkMn top, RUN bottom); LEFT/RIGHT
#     switch columns, cursor_item 0=top 1=bottom.
#   Move menu: top_y=12, top_x=5; wPlayerSelectedMove live-tracks the move ID
#     under the cursor (verified flipping 0x0A Scratch <-> 0x2D Growl).
ADDR_TEXT_BOX_ID = 0xD125
ADDR_TOP_MENU_ITEM_Y = 0xCC24
ADDR_TOP_MENU_ITEM_X = 0xCC25
ADDR_CURRENT_MENU_ITEM = 0xCC26
ADDR_MAX_MENU_ITEM = 0xCC28
ADDR_PLAYER_SELECTED_MOVE = 0xCCDC
# wListScrollOffset: index of the top visible row of a scrolling list (the bag).
# The item the cursor points at = scroll_offset + wCurrentMenuItem. Standard
# pokered address; confirm with scripts/probe_battle_ram.py if catch nav misses.
ADDR_LIST_SCROLL_OFFSET = 0xCC36

# Bag inventory (pokered): a count byte then (item_id, quantity) pairs ending in
# a 0xFF terminator, up to 20 items.
ADDR_NUM_BAG_ITEMS = 0xD31D
ADDR_BAG_ITEMS = 0xD31E
BAG_TERMINATOR = 0xFF
MAX_BAG_ITEMS = 20

# Poké Ball family item IDs (the catch tools).
ITEM_MASTER_BALL = 0x01
ITEM_ULTRA_BALL = 0x02
ITEM_GREAT_BALL = 0x03
ITEM_POKE_BALL = 0x04
# Which ball to spend when catching the everyday stuff: cheapest first, hoard
# the Master Ball (only used if it's literally all we have).
BALL_PREFERENCE = (ITEM_POKE_BALL, ITEM_GREAT_BALL, ITEM_ULTRA_BALL, ITEM_MASTER_BALL)

# HP-restoring item IDs (Gen 1). Used to know whether we *can* heal from the bag.
ITEM_FULL_RESTORE = 0x10
ITEM_MAX_POTION = 0x11
ITEM_HYPER_POTION = 0x12
ITEM_SUPER_POTION = 0x13
ITEM_POTION = 0x14
# Spend the cheapest sufficient heal first; save Full Restore / Max Potion.
HP_HEAL_PREFERENCE = (
    ITEM_POTION, ITEM_SUPER_POTION, ITEM_HYPER_POTION, ITEM_MAX_POTION, ITEM_FULL_RESTORE,
)

# Enemy active battle Pokémon (wEnemyMon @ 0xCFE5), verified live against a wild
# battle. wBattleMon (player) species/HP are unreliable mid-battle, so own-mon
# stats are taken from the party lead at the active slot instead.
ADDR_ENEMY_SPECIES = 0xCFE5
ADDR_ENEMY_HP = 0xCFE6       # 2 bytes, big-endian
ADDR_ENEMY_STATUS = 0xCFE9
ADDR_ENEMY_TYPE1 = 0xCFEA
ADDR_ENEMY_TYPE2 = 0xCFEB
ADDR_ENEMY_LEVEL = 0xCFF3
ADDR_ENEMY_MAX_HP = 0xCFF4   # 2 bytes, big-endian

# Party slot layout
PARTY_SLOT_SIZE = 44
PARTY_SLOT_OFFSET_SPECIES = 0x00
PARTY_SLOT_OFFSET_HP = 0x01  # 2 bytes
PARTY_SLOT_OFFSET_STATUS = 0x04
PARTY_SLOT_OFFSET_TYPE1 = 0x05
PARTY_SLOT_OFFSET_TYPE2 = 0x06
PARTY_SLOT_OFFSET_MOVES = 0x08  # 4 bytes, one move ID each
PARTY_SLOT_OFFSET_DVS = 0x1B  # 2 bytes: Atk/Def nibbles, Spd/Spc nibbles
PARTY_SLOT_OFFSET_PP = 0x1D  # 4 bytes
PARTY_SLOT_OFFSET_LEVEL = 0x21
PARTY_SLOT_OFFSET_MAX_HP = 0x22  # 2 bytes
PARTY_SLOT_OFFSET_ATTACK = 0x24  # 2 bytes
PARTY_SLOT_OFFSET_DEFENSE = 0x26  # 2 bytes
PARTY_SLOT_OFFSET_SPEED = 0x28  # 2 bytes
PARTY_SLOT_OFFSET_SPECIAL = 0x2A  # 2 bytes


def _popcount(byte: int) -> int:
    return bin(byte).count("1")


def _bcd_to_int(bcd_bytes: list[int]) -> int:
    """Convert 3-byte BCD to int (e.g. [0x01, 0x23, 0x45] -> 12345)."""
    result = 0
    for b in bcd_bytes:
        result = result * 100 + ((b >> 4) * 10) + (b & 0x0F)
    return result


@dataclass(frozen=True)
class PartyMon:
    """Detailed view of one party slot (used by the diagnostic dashboard)."""

    slot: int
    species_id: int
    level: int
    hp: int
    max_hp: int
    status: int
    type1: int
    type2: int
    moves: tuple[int, int, int, int]
    pp: tuple[int, int, int, int]
    # DVs ("genome"): Gen 1's hidden per-stat genetic values, 0-15 each
    dv_attack: int
    dv_defense: int
    dv_speed: int
    dv_special: int
    attack: int
    defense: int
    speed: int
    special: int

    @property
    def dv_hp(self) -> int:
        """HP DV is derived from the least-significant bit of the other four DVs."""
        return (
            ((self.dv_attack & 1) << 3)
            | ((self.dv_defense & 1) << 2)
            | ((self.dv_speed & 1) << 1)
            | (self.dv_special & 1)
        )


@dataclass(frozen=True)
class GameState:
    """Snapshot of the 12 RAM-derived state fields."""

    party_count: int
    party_total_hp: int          # sum of current HP across party
    party_total_max_hp: int      # sum of max HP across party
    party_total_level: int       # sum of levels across party
    money: int
    current_map: int
    y_pos: int
    x_pos: int
    badge_count: int             # popcount of badge flags byte
    event_flags_set: int         # popcount across all event flag bytes
    battle_type: int
    menu_cursor: int
    party_fainted_count: int = 0  # occupied slots at 0 HP (faint-penalty signal)

    @property
    def all_party_fainted(self) -> bool:
        return self.party_count > 0 and self.party_total_hp == 0


@dataclass(frozen=True)
class BattleState:
    """Battle-perception snapshot — vision during fights.

    `in_battle`: 0 not in battle, 1 wild, 2 trainer.
    Own-mon stats come from the party lead at the active slot (reliable
    mid-battle); enemy stats come from wEnemyMon and are zeroed when not in
    battle. HP fractions are in [0, 1].
    """

    in_battle: int
    own_hp_frac: float
    own_level: int
    own_type1: int
    own_type2: int
    own_status: int
    enemy_species: int
    enemy_hp_frac: float
    enemy_level: int
    enemy_type1: int
    enemy_type2: int
    enemy_status: int


@dataclass(frozen=True)
class BattleMenus:
    """Snapshot of the battle menu state (for the BattleBrain driver).

    `menu_open` is True when a battle menu is awaiting input right now.
    The action/move-menu properties decode which one (signatures verified
    live; see address comments above).
    """

    text_box_id: int
    top_y: int
    top_x: int
    cursor_item: int
    max_item: int
    selected_move_id: int

    @property
    def menu_open(self) -> bool:
        return self.text_box_id == 11

    @property
    def action_menu_open(self) -> bool:
        return self.menu_open and self.top_y == 14 and self.top_x in (9, 15)

    @property
    def move_menu_open(self) -> bool:
        return self.menu_open and self.top_y == 12 and self.top_x == 5


class StateReader:
    """Reads the 12-field RAM state from the emulator."""

    def __init__(self, emulator: EmulatorWrapper):
        self.emu = emulator

    def read(self) -> GameState:
        party_count = self.emu.read_byte(ADDR_PARTY_COUNT)
        party_data = self.emu.read_range(ADDR_PARTY_DATA_START, ADDR_PARTY_DATA_END)

        total_hp = 0
        total_max_hp = 0
        total_level = 0
        fainted = 0
        # Only iterate over actual party slots (party_count, capped at 6)
        slots = min(party_count, 6)
        for i in range(slots):
            base = i * PARTY_SLOT_SIZE
            hp_hi = party_data[base + PARTY_SLOT_OFFSET_HP]
            hp_lo = party_data[base + PARTY_SLOT_OFFSET_HP + 1]
            hp = (hp_hi << 8) | hp_lo
            total_hp += hp

            max_hi = party_data[base + PARTY_SLOT_OFFSET_MAX_HP]
            max_lo = party_data[base + PARTY_SLOT_OFFSET_MAX_HP + 1]
            max_hp = (max_hi << 8) | max_lo
            total_max_hp += max_hp

            total_level += party_data[base + PARTY_SLOT_OFFSET_LEVEL]
            if max_hp > 0 and hp == 0:
                fainted += 1

        money_bytes = self.emu.read_range(ADDR_MONEY_START, ADDR_MONEY_START + 3)
        money = _bcd_to_int(money_bytes)

        badge_flags = self.emu.read_byte(ADDR_BADGE_FLAGS)
        badge_count = _popcount(badge_flags)

        event_bytes = self.emu.read_range(ADDR_EVENT_FLAGS_START, ADDR_EVENT_FLAGS_END)
        event_flags_set = sum(_popcount(b) for b in event_bytes)

        return GameState(
            party_count=party_count,
            party_total_hp=total_hp,
            party_total_max_hp=total_max_hp,
            party_total_level=total_level,
            money=money,
            current_map=self.emu.read_byte(ADDR_CURRENT_MAP),
            y_pos=self.emu.read_byte(ADDR_Y_POS),
            x_pos=self.emu.read_byte(ADDR_X_POS),
            badge_count=badge_count,
            event_flags_set=event_flags_set,
            battle_type=self.emu.read_byte(ADDR_BATTLE_TYPE),
            menu_cursor=self.emu.read_byte(ADDR_MENU_CURSOR),
            party_fainted_count=fainted,
        )

    def read_battle(self) -> BattleState:
        """Read battle perception: in-battle flag + own (party lead) + enemy mon.

        Enemy fields are zeroed when not in battle (wEnemyMon holds stale data
        outside of battle); the in_battle flag disambiguates a real zero.
        """
        in_battle = self.emu.read_byte(ADDR_IS_IN_BATTLE)

        # Own active mon: the party slot the game is currently battling with.
        active = self.emu.read_byte(ADDR_PLAYER_MON_NUMBER)
        party = self.read_party_details()
        if party:
            lead = party[active] if active < len(party) else party[0]
            own_hp_frac = lead.hp / lead.max_hp if lead.max_hp > 0 else 0.0
            own_level, own_type1, own_type2, own_status = (
                lead.level, lead.type1, lead.type2, lead.status
            )
        else:
            own_hp_frac = 0.0
            own_level = own_type1 = own_type2 = own_status = 0

        if in_battle:
            e_hp = (self.emu.read_byte(ADDR_ENEMY_HP) << 8) | self.emu.read_byte(
                ADDR_ENEMY_HP + 1
            )
            e_max = (self.emu.read_byte(ADDR_ENEMY_MAX_HP) << 8) | self.emu.read_byte(
                ADDR_ENEMY_MAX_HP + 1
            )
            enemy_hp_frac = e_hp / e_max if e_max > 0 else 0.0
            enemy_species = self.emu.read_byte(ADDR_ENEMY_SPECIES)
            enemy_level = self.emu.read_byte(ADDR_ENEMY_LEVEL)
            enemy_type1 = self.emu.read_byte(ADDR_ENEMY_TYPE1)
            enemy_type2 = self.emu.read_byte(ADDR_ENEMY_TYPE2)
            enemy_status = self.emu.read_byte(ADDR_ENEMY_STATUS)
        else:
            enemy_hp_frac = 0.0
            enemy_species = enemy_level = enemy_type1 = enemy_type2 = enemy_status = 0

        return BattleState(
            in_battle=in_battle,
            own_hp_frac=own_hp_frac,
            own_level=own_level,
            own_type1=own_type1,
            own_type2=own_type2,
            own_status=own_status,
            enemy_species=enemy_species,
            enemy_hp_frac=enemy_hp_frac,
            enemy_level=enemy_level,
            enemy_type1=enemy_type1,
            enemy_type2=enemy_type2,
            enemy_status=enemy_status,
        )

    def read_battle_menus(self) -> BattleMenus:
        """Read the battle menu snapshot (cheap: 6 byte reads)."""
        return BattleMenus(
            text_box_id=self.emu.read_byte(ADDR_TEXT_BOX_ID),
            top_y=self.emu.read_byte(ADDR_TOP_MENU_ITEM_Y),
            top_x=self.emu.read_byte(ADDR_TOP_MENU_ITEM_X),
            cursor_item=self.emu.read_byte(ADDR_CURRENT_MENU_ITEM),
            max_item=self.emu.read_byte(ADDR_MAX_MENU_ITEM),
            selected_move_id=self.emu.read_byte(ADDR_PLAYER_SELECTED_MOVE),
        )

    def read_bag(self) -> list[tuple[int, int]]:
        """The bag as a list of (item_id, quantity), in slot order."""
        count = min(self.emu.read_byte(ADDR_NUM_BAG_ITEMS), MAX_BAG_ITEMS)
        if count <= 0:  # empty bag: don't ask the emulator for a zero-length range
            return []
        data = self.emu.read_range(ADDR_BAG_ITEMS, ADDR_BAG_ITEMS + count * 2)
        items: list[tuple[int, int]] = []
        for i in range(count):
            item_id = data[i * 2]
            if item_id == BAG_TERMINATOR:
                break
            items.append((item_id, data[i * 2 + 1]))
        return items

    def best_ball(self) -> tuple[int, int] | None:
        """The ball to throw and its 0-based bag slot index, by BALL_PREFERENCE
        (cheapest usable first). None if the bag holds no balls."""
        bag = self.read_bag()
        for ball_id in BALL_PREFERENCE:
            for idx, (item_id, qty) in enumerate(bag):
                if item_id == ball_id and qty > 0:
                    return ball_id, idx
        return None

    def best_heal_item(self) -> tuple[int, int] | None:
        """The HP-restoring item to use and its 0-based bag slot, cheapest first.
        None if the bag holds no healing items."""
        bag = self.read_bag()
        for item_id in HP_HEAL_PREFERENCE:
            for idx, (bag_id, qty) in enumerate(bag):
                if bag_id == item_id and qty > 0:
                    return item_id, idx
        return None

    def count_heal_items(self) -> int:
        """How many HP-restoring items are in the bag (total quantity)."""
        heals = set(HP_HEAL_PREFERENCE)
        return sum(qty for item_id, qty in self.read_bag() if item_id in heals)

    def list_selection_index(self) -> int:
        """Which list row is highlighted (e.g. which bag item): the scroll offset
        plus the on-screen cursor position."""
        return self.emu.read_byte(ADDR_LIST_SCROLL_OFFSET) + self.emu.read_byte(
            ADDR_CURRENT_MENU_ITEM
        )

    def read_party_details(self) -> list[PartyMon]:
        """Read per-Pokemon detail for each occupied party slot."""

        def u16(data: list[int], offset: int) -> int:
            return (data[offset] << 8) | data[offset + 1]

        party_count = self.emu.read_byte(ADDR_PARTY_COUNT)
        party_data = self.emu.read_range(ADDR_PARTY_DATA_START, ADDR_PARTY_DATA_END)

        mons: list[PartyMon] = []
        for i in range(min(party_count, 6)):
            base = i * PARTY_SLOT_SIZE
            dv_byte1 = party_data[base + PARTY_SLOT_OFFSET_DVS]
            dv_byte2 = party_data[base + PARTY_SLOT_OFFSET_DVS + 1]
            mons.append(
                PartyMon(
                    slot=i,
                    species_id=party_data[base + PARTY_SLOT_OFFSET_SPECIES],
                    level=party_data[base + PARTY_SLOT_OFFSET_LEVEL],
                    hp=u16(party_data, base + PARTY_SLOT_OFFSET_HP),
                    max_hp=u16(party_data, base + PARTY_SLOT_OFFSET_MAX_HP),
                    status=party_data[base + PARTY_SLOT_OFFSET_STATUS],
                    type1=party_data[base + PARTY_SLOT_OFFSET_TYPE1],
                    type2=party_data[base + PARTY_SLOT_OFFSET_TYPE2],
                    moves=tuple(
                        party_data[base + PARTY_SLOT_OFFSET_MOVES + m] for m in range(4)
                    ),
                    pp=tuple(party_data[base + PARTY_SLOT_OFFSET_PP + m] for m in range(4)),
                    dv_attack=(dv_byte1 >> 4) & 0x0F,
                    dv_defense=dv_byte1 & 0x0F,
                    dv_speed=(dv_byte2 >> 4) & 0x0F,
                    dv_special=dv_byte2 & 0x0F,
                    attack=u16(party_data, base + PARTY_SLOT_OFFSET_ATTACK),
                    defense=u16(party_data, base + PARTY_SLOT_OFFSET_DEFENSE),
                    speed=u16(party_data, base + PARTY_SLOT_OFFSET_SPEED),
                    special=u16(party_data, base + PARTY_SLOT_OFFSET_SPECIAL),
                )
            )
        return mons
