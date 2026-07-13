"""ROM-free unit tests for FireRedStateReader's pure parsing.

A tiny sparse-memory mock serves scripted EWRAM/IWRAM through the SAME reader
the live emulator uses, so the Gen-3 obfuscation logic (money XOR, party PV
decrypt/unscramble, totals, badges, position, map) is verified deterministically
on Windows without mGBA. Mirrors the Red build's mock-emulator discipline.
"""
from __future__ import annotations

from pokeai.emulator import firered_state_reader as fsr
from pokeai.emulator.firered_state_reader import FireRedStateReader

SB1 = 0x02025000
SB2 = 0x02026000


class MockGBA:
    """Sparse byte memory with the EmulatorWrapper read surface."""

    def __init__(self):
        self.mem: dict[int, int] = {}

    # writes
    def w8(self, addr: int, v: int):
        self.mem[addr] = v & 0xFF

    def w16(self, addr: int, v: int):
        self.w8(addr, v); self.w8(addr + 1, v >> 8)

    def w32(self, addr: int, v: int):
        self.w16(addr, v & 0xFFFF); self.w16(addr + 2, v >> 16)

    def wbytes(self, addr: int, data: bytes):
        for i, b in enumerate(data):
            self.mem[addr + i] = b

    # reads (the wrapper surface)
    def read_byte(self, addr: int) -> int:
        return self.mem.get(addr, 0)

    def read_u16(self, addr: int) -> int:
        return self.read_byte(addr) | (self.read_byte(addr + 1) << 8)

    def read_u32(self, addr: int) -> int:
        return self.read_u16(addr) | (self.read_u16(addr + 2) << 16)

    def read_range(self, start: int, end: int) -> list[int]:
        return [self.mem.get(a, 0) for a in range(start, end)]


def _encode_slot_data(pid: int, otid: int, growth: bytes, attacks: bytes,
                      evs: bytes, misc: bytes) -> bytes:
    """Inverse of FireRedStateReader.decrypt_slot_data: scramble G/A/E/M into the
    PID%24 storage order, then XOR each 32-bit word with PID^OTID."""
    key = pid ^ otid
    order = fsr._SUBSTRUCT_ORDER[pid % 24]
    plain = {"G": growth, "A": attacks, "E": evs, "M": misc}
    dec = bytearray(48)
    for s in range(4):
        dec[s * 12:s * 12 + 12] = plain[order[s]]
    raw = bytearray(48)
    for w in range(12):
        word = int.from_bytes(dec[w * 4:w * 4 + 4], "little") ^ key
        raw[w * 4:w * 4 + 4] = word.to_bytes(4, "little")
    return bytes(raw)


def _build() -> MockGBA:
    m = MockGBA()
    # SaveBlock pointers (relocating in real HW; fixed here).
    m.w32(fsr.GSAVEBLOCK1_PTR, SB1)
    m.w32(fsr.GSAVEBLOCK2_PTR, SB2)
    # Money 3000 = raw ^ key.
    key = 0xDEADBEEF
    m.w32(SB2 + fsr.SB2_SECURITY_KEY_OFF, key)
    m.w32(SB1 + fsr.SB1_MONEY_OFF, 3000 ^ key)
    # Map (group=4, num=1).
    m.w8(SB1 + fsr.SB1_MAP_GROUP_OFF, 4)
    m.w8(SB1 + fsr.SB1_MAP_NUM_OFF, 1)
    # Badges: 3 bits set in the badge byte (inside the flags region).
    badge_byte = SB1 + fsr.SB1_FLAGS_OFF + (fsr.BADGE_FLAG_FIRST // 8)
    m.w8(badge_byte, 0b00000111)
    # Position: object coords (13,15) -> map (6,8).
    m.w16(fsr.GOBJECT_EVENTS + fsr.OBJ_CUR_X_OFF, 13)
    m.w16(fsr.GOBJECT_EVENTS + fsr.OBJ_CUR_Y_OFF, 15)
    # Party: 2 members, with battle-stats (unencrypted) level/HP.
    m.w8(fsr.GPLAYER_PARTY_COUNT, 2)
    for i, (lvl, hp, mx) in enumerate([(5, 19, 20), (7, 22, 24)]):
        base = fsr.GPLAYER_PARTY + i * fsr.SLOT_SIZE
        m.w8(base + fsr.SLOT_LEVEL_OFF, lvl)
        m.w16(base + fsr.SLOT_CURHP_OFF, hp)
        m.w16(base + fsr.SLOT_MAXHP_OFF, mx)
    return m


def test_money_xor_decode():
    assert FireRedStateReader(_build()).read_money() == 3000


def test_current_map_group_num():
    assert FireRedStateReader(_build()).read_current_map() == (4 << 8) | 1


def test_position_minus_object_bias():
    assert FireRedStateReader(_build()).read_position() == (6, 8)


def test_badges_popcount():
    assert FireRedStateReader(_build()).read_badges() == 3


def test_party_totals_from_unencrypted_region():
    r = FireRedStateReader(_build())
    s = r.read()
    assert s.party_count == 2
    assert s.party_total_level == 12
    assert s.party_total_hp == 41
    assert s.party_total_max_hp == 44
    assert not s.all_party_fainted


def test_all_party_fainted():
    m = _build()
    # zero both HP fields
    for i in range(2):
        m.w16(fsr.GPLAYER_PARTY + i * fsr.SLOT_SIZE + fsr.SLOT_CURHP_OFF, 0)
    s = FireRedStateReader(m).read()
    assert s.all_party_fainted


def test_pv_decrypt_reads_species():
    # PID%24 = 6 -> a non-identity substructure order ("AGEM").
    pid, otid, species = 6, 0x1234_5678, 1  # species 1
    m = _build()
    base = fsr.GPLAYER_PARTY  # slot 0
    m.w32(base + fsr.SLOT_PID_OFF, pid)
    m.w32(base + fsr.SLOT_OTID_OFF, otid)
    growth = species.to_bytes(2, "little") + bytes(10)
    data = _encode_slot_data(pid, otid, growth, b"A" * 12, b"E" * 12, b"M" * 12)
    m.wbytes(base + fsr.SLOT_DATA_OFF, data)
    r = FireRedStateReader(m)
    assert r.read_species(0) == species
    # the unscrambled block is G|A|E|M ordered
    dec = r.decrypt_slot_data(0)
    assert dec[12:24] == b"A" * 12 and dec[24:36] == b"E" * 12
