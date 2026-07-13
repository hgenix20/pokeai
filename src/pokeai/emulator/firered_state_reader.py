"""FireRed (GBA, Gen 3) RAM -> typed state.

The GBA counterpart of `state_reader.StateReader`. It keeps the SAME dataclass
SHAPE as the Red build's `GameState` so the env, reward, dashboard, and brains
stay source-compatible (docs/FIRERED_REDESIGN.md §5.1). Only the addresses and
the Gen-3 obfuscation handling are new.

Reads through an EmulatorWrapper-like object (read_byte/read_range/read_u16/u32),
so the pure parsing is unit-testable with a mock that serves scripted EWRAM.

Verification status (see the probe findings in the design doc, 2026-06-16):
  * money + the SaveBlock pointer indirection ........... VERIFIED live (=3000).
  * party level/HP (unencrypted battle-stats region) .... high-confidence, std
    Gen-3 layout; verified once a starter exists (next F1 step).
  * party_count / party base / badges / x,y / map ....... CANDIDATE addresses,
    pending a known in-world state to confirm.
  * species/moves via PV-decrypt ........................ implemented faithfully
    (standard algorithm); used by the HUD/battle later, verified with a starter.
"""
from __future__ import annotations

from dataclasses import dataclass

# --- pointers (IWRAM) — VERIFIED ---
GSAVEBLOCK1_PTR = 0x03005008  # u32 -> SaveBlock1 (relocates every frame!)
GSAVEBLOCK2_PTR = 0x0300500C  # u32 -> SaveBlock2

# --- SaveBlock offsets — money VERIFIED, others candidate ---
SB1_MONEY_OFF = 0x0290        # u32, money ^ securityKey         [VERIFIED]
SB2_SECURITY_KEY_OFF = 0x0F20  # u32                              [VERIFIED]
SB1_MAP_GROUP_OFF = 0x04      # u8  WarpData.location.mapGroup    [CANDIDATE]
SB1_MAP_NUM_OFF = 0x05        # u8  WarpData.location.mapNum      [CANDIDATE]
SB1_FLAGS_OFF = 0x0EE0        # flags region base                [CANDIDATE]

# Live overworld position lives in gObjectEvents[0] (the player) — a FIXED EWRAM
# global. The SaveBlock pos is only the saved/warp position (it lags walking).
# Object coords = map coords + 7. VERIFIED live: walking DOWN moved this y 13->15
# (map 6->8) and an independent diff-scan flagged gObjectEvents+0x12; x (+0x10)
# follows by the Coords16 {s16 x, s16 y} layout.
GOBJECT_EVENTS = 0x02036E38
OBJ_CUR_X_OFF = 0x10
OBJ_CUR_Y_OFF = 0x12
OBJ_COORD_BIAS = 7
# Badge system flags FLAG_BADGE01..08 = 0x820..0x827 (8 consecutive bits).
BADGE_FLAG_FIRST = 0x820
# A bounded slice of the flags region used as an event-progress proxy (popcount).
EVENT_FLAGS_BYTES = 0x12C

# --- bag pockets (SaveBlock1) — entry = [u16 itemId][u16 qty ^ key16] ---
# Items pocket start discovered empirically 2026-07-03 (probe_bag/viridian_heal_parcel);
# Key Items verified live via Oak's Parcel (id 349) at +0x3B8 (part2_parcel).
# Pocket sizes follow the pokefirered SaveBlock1 layout and are mutually
# consistent with the two verified starts: (0x3B8-0x310)/4 = 42 item slots,
# (0x430-0x3B8)/4 = 30 key-item slots.
SB1_BAG_POCKETS = {
    "items": (0x0310, 42),
    "key_items": (0x03B8, 30),
    "balls": (0x0430, 13),
    "tm_case": (0x0464, 58),
    "berries": (0x054C, 43),
}
# Gen-3 item ids we rely on (FRLG). POKE_BALL qty verified live (deliver_oak).
ITEM_MASTER_BALL = 1
ITEM_ULTRA_BALL = 2
ITEM_GREAT_BALL = 3
ITEM_POKE_BALL = 4
ITEM_POTION = 13
ITEM_FULL_RESTORE = 19
ITEM_MAX_POTION = 20
ITEM_HYPER_POTION = 21
ITEM_SUPER_POTION = 22
ITEM_OAKS_PARCEL = 349
ITEM_TOWN_MAP = 361     # discovered live 2026-07-05 (Daisy, rival's house (4,2))
ITEM_TEACHY_TV = 366    # discovered live 2026-07-05 (old man, Viridian north path)
HEAL_ITEM_IDS = (ITEM_POTION, ITEM_SUPER_POTION, ITEM_HYPER_POTION,
                 ITEM_MAX_POTION, ITEM_FULL_RESTORE)
BALL_ITEM_IDS = (ITEM_POKE_BALL, ITEM_GREAT_BALL, ITEM_ULTRA_BALL,
                 ITEM_MASTER_BALL)

# --- party (fixed EWRAM globals) — CANDIDATE ---
GPLAYER_PARTY_COUNT = 0x02024029  # u8
GPLAYER_PARTY = 0x02024284        # 6 x 100-byte slots
SLOT_SIZE = 100
# Unencrypted battle-stats region offsets within a slot — std Gen-3 layout.
SLOT_LEVEL_OFF = 0x54   # u8
SLOT_CURHP_OFF = 0x56   # u16
SLOT_MAXHP_OFF = 0x58   # u16
# Encrypted-data plumbing (for species/moves).
SLOT_PID_OFF = 0x00
SLOT_OTID_OFF = 0x04
SLOT_DATA_OFF = 0x20    # 48 bytes = 4 x 12-byte substructures
# Substructure permutation by PID % 24: index of Growth/Attacks/EVs/Misc.
_SUBSTRUCT_ORDER = [
    "GAEM", "GAME", "GEAM", "GEMA", "GMAE", "GMEA",
    "AGEM", "AGME", "AEGM", "AEMG", "AMGE", "AMEG",
    "EGAM", "EGMA", "EAGM", "EAMG", "EMGA", "EMAG",
    "MGAE", "MGEA", "MAGE", "MAEG", "MEGA", "MEAG",
]


# Gen-3 natures, indexed by PID % 25 (Route 22 quest priorities need this).
NATURES = (
    "Hardy", "Lonely", "Brave", "Adamant", "Naughty",
    "Bold", "Docile", "Relaxed", "Impish", "Lax",
    "Timid", "Hasty", "Serious", "Jolly", "Naive",
    "Modest", "Mild", "Quiet", "Bashful", "Rash",
    "Calm", "Gentle", "Sassy", "Careful", "Quirky",
)


def _popcount_bytes(data: list[int] | bytes) -> int:
    return sum(bin(b).count("1") for b in data)


@dataclass(frozen=True)
class GameState:
    """Canonical snapshot — same shape as the Red build's GameState."""

    party_count: int
    party_total_hp: int
    party_total_max_hp: int
    party_total_level: int
    money: int
    current_map: int
    x_pos: int
    y_pos: int
    badge_count: int
    event_flags_set: int
    battle_type: int
    menu_cursor: int

    @property
    def all_party_fainted(self) -> bool:
        return self.party_count > 0 and self.party_total_hp == 0


class FireRedStateReader:
    """Reads + decodes FireRed EWRAM into a GameState."""

    def __init__(self, emulator):
        self.emu = emulator

    # --- pointer indirection (save blocks relocate every frame) ---

    def _sb1(self) -> int:
        return self.emu.read_u32(GSAVEBLOCK1_PTR)

    def _sb2(self) -> int:
        return self.emu.read_u32(GSAVEBLOCK2_PTR)

    # --- fields ---

    def read_money(self) -> int:
        sb1, sb2 = self._sb1(), self._sb2()
        key = self.emu.read_u32(sb2 + SB2_SECURITY_KEY_OFF)
        return self.emu.read_u32(sb1 + SB1_MONEY_OFF) ^ key

    def read_badges(self) -> int:
        sb1 = self._sb1()
        byte_off = SB1_FLAGS_OFF + (BADGE_FLAG_FIRST // 8)
        return bin(self.emu.read_byte(sb1 + byte_off)).count("1")

    def read_event_flags_set(self) -> int:
        sb1 = self._sb1()
        flags = self.emu.read_range(sb1 + SB1_FLAGS_OFF,
                                    sb1 + SB1_FLAGS_OFF + EVENT_FLAGS_BYTES)
        return _popcount_bytes(flags)

    def read_current_map(self) -> int:
        """(mapGroup << 8) | mapNum from SaveBlock1.location. Stable (4,1) in the
        starting bedroom; CANDIDATE pending a verified map transition."""
        sb1 = self._sb1()
        grp = self.emu.read_byte(sb1 + SB1_MAP_GROUP_OFF)
        num = self.emu.read_byte(sb1 + SB1_MAP_NUM_OFF)
        return (grp << 8) | num

    def read_position(self) -> tuple[int, int]:
        """Live (x, y) map coords from gObjectEvents[0], minus the +7 object bias.
        VERIFIED for y (and x by struct symmetry)."""
        x = self.emu.read_u16(GOBJECT_EVENTS + OBJ_CUR_X_OFF) - OBJ_COORD_BIAS
        y = self.emu.read_u16(GOBJECT_EVENTS + OBJ_CUR_Y_OFF) - OBJ_COORD_BIAS
        return x, y

    def _party_totals(self) -> tuple[int, int, int, int]:
        """(count, total_hp, total_max_hp, total_level) from the UNENCRYPTED
        battle-stats region — no PV-decryption needed."""
        count = min(self.emu.read_byte(GPLAYER_PARTY_COUNT), 6)
        thp = tmax = tlvl = 0
        for i in range(count):
            base = GPLAYER_PARTY + i * SLOT_SIZE
            tlvl += self.emu.read_byte(base + SLOT_LEVEL_OFF)
            thp += self.emu.read_u16(base + SLOT_CURHP_OFF)
            tmax += self.emu.read_u16(base + SLOT_MAXHP_OFF)
        return count, thp, tmax, tlvl

    def read(self) -> GameState:
        count, thp, tmax, tlvl = self._party_totals()
        x, y = self.read_position()
        return GameState(
            party_count=count,
            party_total_hp=thp,
            party_total_max_hp=tmax,
            party_total_level=tlvl,
            money=self.read_money(),
            current_map=self.read_current_map(),
            x_pos=x,
            y_pos=y,
            badge_count=self.read_badges(),
            event_flags_set=self.read_event_flags_set(),
            battle_type=0,                      # TODO(F1): in-battle flag
            menu_cursor=0,                      # TODO(F1): menu cursor
        )

    # --- species/moves via Gen-3 substructure decryption (for HUD/battle) ---

    def decrypt_slot_data(self, slot_index: int) -> bytes:
        """Return the 48-byte decrypted+unscrambled data block of a party slot,
        ordered as Growth|Attacks|EVs|Misc (each 12 bytes). Used to read species
        and moves; level/HP do NOT need this."""
        return self.decrypt_slot_data_at(GPLAYER_PARTY + slot_index * SLOT_SIZE)

    def read_species_at(self, base: int) -> int:
        """Species id of the 100-byte mon struct at `base` (works for
        gEnemyParty slots too - same layout/encryption)."""
        return int.from_bytes(self.decrypt_slot_data_at(base)[0:2], "little")

    def decrypt_slot_data_at(self, base: int) -> bytes:
        """decrypt_slot_data for an arbitrary struct base (player OR enemy)."""
        pid = self.emu.read_u32(base + SLOT_PID_OFF)
        otid = self.emu.read_u32(base + SLOT_OTID_OFF)
        key = pid ^ otid
        raw = bytes(self.emu.read_range(base + SLOT_DATA_OFF, base + SLOT_DATA_OFF + 48))
        # Decrypt: XOR each 32-bit word with the key.
        dec = bytearray(48)
        for w in range(12):
            word = int.from_bytes(raw[w * 4:w * 4 + 4], "little") ^ key
            dec[w * 4:w * 4 + 4] = word.to_bytes(4, "little")
        # Unscramble the four 12-byte substructures into G|A|E|M order.
        order = _SUBSTRUCT_ORDER[pid % 24]
        pos = {"G": order.index("G"), "A": order.index("A"),
               "E": order.index("E"), "M": order.index("M")}
        out = bytearray(48)
        for i, which in enumerate("GAEM"):
            src = pos[which] * 12
            out[i * 12:i * 12 + 12] = dec[src:src + 12]
        return bytes(out)

    def read_species(self, slot_index: int) -> int:
        """Species id (Growth substructure, first u16)."""
        return int.from_bytes(self.decrypt_slot_data(slot_index)[0:2], "little")

    def read_nature(self, slot_index: int) -> str:
        """Nature from the personality value: PID % 25 (no decryption needed)."""
        pid = self.emu.read_u32(GPLAYER_PARTY + slot_index * SLOT_SIZE
                                + SLOT_PID_OFF)
        return NATURES[pid % 25]

    def read_flag(self, flag_id: int) -> bool:
        """One event/system flag by id from the SaveBlock1 flags region (e.g.
        badges 0x820-0x827, FLAG_SYS_POKEDEX_GET 0x829)."""
        sb1 = self._sb1()
        byte = self.emu.read_byte(sb1 + SB1_FLAGS_OFF + flag_id // 8)
        return bool(byte & (1 << (flag_id % 8)))

    def read_moves(self, slot_index: int) -> list[tuple[int, int]]:
        """[(move_id, pp)] x4 from the Attacks substructure (bytes 12-23 of the
        decrypted block: 4 x u16 move ids then 4 x u8 PP). Empty move slots are
        id 0."""
        data = self.decrypt_slot_data(slot_index)
        return [(int.from_bytes(data[12 + i * 2:14 + i * 2], "little"),
                 data[20 + i]) for i in range(4)]

    # --- per-mon party details (unencrypted battle-stats region) ---

    def read_party_details(self) -> list[dict]:
        """[{level, hp, max_hp}] for each occupied slot. No decryption needed;
        this is the source for fainted-count / half-party-low brain facts."""
        count = min(self.emu.read_byte(GPLAYER_PARTY_COUNT), 6)
        out = []
        for i in range(count):
            base = GPLAYER_PARTY + i * SLOT_SIZE
            out.append({
                "level": self.emu.read_byte(base + SLOT_LEVEL_OFF),
                "hp": self.emu.read_u16(base + SLOT_CURHP_OFF),
                "max_hp": self.emu.read_u16(base + SLOT_MAXHP_OFF),
            })
        return out

    def party_fainted_count(self) -> int:
        """Occupied slots with max_hp > 0 and hp == 0 (mirrors the Red reader)."""
        return sum(1 for m in self.read_party_details()
                   if m["max_hp"] > 0 and m["hp"] == 0)

    # --- bag (SaveBlock1 pockets; quantities XOR the low 16 security-key bits) ---

    def _key16(self) -> int:
        return self.emu.read_u32(self._sb2() + SB2_SECURITY_KEY_OFF) & 0xFFFF

    def read_bag_pocket(self, pocket: str) -> list[tuple[int, int]]:
        """[(item_id, qty)] for the occupied slots of a pocket. Key-item
        quantities are stored unencrypted at qty 1 in FRLG, but we XOR-decode
        every pocket the same way and clamp: a decoded qty > 999 means the raw
        value was NOT encrypted (key items), so fall back to the raw u16."""
        off, size = SB1_BAG_POCKETS[pocket]
        sb1, key16 = self._sb1(), self._key16()
        raw = self.emu.read_range(sb1 + off, sb1 + off + size * 4)
        out = []
        for i in range(size):
            item = raw[i * 4] | (raw[i * 4 + 1] << 8)
            if item == 0:
                continue
            q = (raw[i * 4 + 2] | (raw[i * 4 + 3] << 8)) ^ key16
            if q > 999:
                q = raw[i * 4 + 2] | (raw[i * 4 + 3] << 8)
            out.append((item, q))
        return out

    def count_item(self, item_id: int) -> int:
        """Total quantity of an item across the items + balls + key_items pockets."""
        total = 0
        for pocket in ("items", "balls", "key_items"):
            for item, qty in self.read_bag_pocket(pocket):
                if item == item_id:
                    total += qty
        return total

    def ball_count(self) -> int:
        """Total Poke Balls of any kind in the balls pocket."""
        return sum(qty for item, qty in self.read_bag_pocket("balls"))

    def count_heal_items(self) -> int:
        """Total HP-restoring items in the items pocket."""
        return sum(qty for item, qty in self.read_bag_pocket("items")
                   if item in HEAL_ITEM_IDS)
