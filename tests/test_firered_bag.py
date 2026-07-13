"""ROM-free unit tests for FireRedStateReader's bag + party-detail APIs.

Reuses the MockGBA sparse-memory mock from test_firered_state_reader (scripted
EWRAM served through the REAL reader, including the SaveBlock pointer
indirection), so the security-key XOR on bag quantities, the key-item
unencrypted-qty fallback, the Attacks-substructure decrypt, and the per-mon
party details are all verified deterministically on Windows without mGBA.
"""
from __future__ import annotations

import struct

from pokeai.emulator import firered_state_reader as fsr
from pokeai.emulator.firered_state_reader import FireRedStateReader
from tests.test_firered_state_reader import MockGBA, _encode_slot_data

SB1 = 0x02025000
SB2 = 0x02026000
KEY = 0xDEADBEEF          # security key; low 16 bits (0xBEEF) encrypt bag qty
KEY16 = KEY & 0xFFFF


def _build(items=(), key_items_raw=(), balls=()) -> MockGBA:
    """Mock with SaveBlock pointers + security key + scripted bag pockets.

    `items` / `balls` entries are (item_id, qty) stored ENCRYPTED (qty ^ key16),
    the way the game stores them. `key_items_raw` entries are stored with the
    RAW quantity (FRLG leaves key-item quantities unencrypted at 1).
    """
    m = MockGBA()
    m.w32(fsr.GSAVEBLOCK1_PTR, SB1)
    m.w32(fsr.GSAVEBLOCK2_PTR, SB2)
    m.w32(SB2 + fsr.SB2_SECURITY_KEY_OFF, KEY)
    for pocket, entries, encrypt in (("items", items, True),
                                     ("key_items", key_items_raw, False),
                                     ("balls", balls, True)):
        off, _size = fsr.SB1_BAG_POCKETS[pocket]
        for i, (item, qty) in enumerate(entries):
            m.w16(SB1 + off + i * 4, item)
            m.w16(SB1 + off + i * 4 + 2, (qty ^ KEY16) if encrypt else qty)
    return m


# --- read_bag_pocket ---


def test_balls_pocket_decodes_with_nonzero_key():
    r = FireRedStateReader(_build(balls=[(fsr.ITEM_POKE_BALL, 5)]))
    assert r.read_bag_pocket("balls") == [(fsr.ITEM_POKE_BALL, 5)]


def test_items_pocket_two_items_skips_empty_slots():
    r = FireRedStateReader(_build(items=[(fsr.ITEM_POTION, 3),
                                         (fsr.ITEM_SUPER_POTION, 2)]))
    assert r.read_bag_pocket("items") == [(fsr.ITEM_POTION, 3),
                                          (fsr.ITEM_SUPER_POTION, 2)]
    assert r.read_bag_pocket("balls") == []      # untouched pocket stays empty


def test_key_item_unencrypted_qty_falls_back_to_raw():
    # Raw qty 1 XOR 0xBEEF decodes to 0xBEEE (> 999), so the reader must fall
    # back to the raw u16 — the FRLG unencrypted key-item convention.
    assert (1 ^ KEY16) > 999
    r = FireRedStateReader(_build(key_items_raw=[(fsr.ITEM_OAKS_PARCEL, 1)]))
    assert r.read_bag_pocket("key_items") == [(fsr.ITEM_OAKS_PARCEL, 1)]


# --- counting helpers ---


def test_count_item_sums_across_pockets():
    r = FireRedStateReader(_build(items=[(fsr.ITEM_POKE_BALL, 2),
                                         (fsr.ITEM_POTION, 3)],
                                  balls=[(fsr.ITEM_POKE_BALL, 5)]))
    assert r.count_item(fsr.ITEM_POKE_BALL) == 7   # items + balls pockets
    assert r.count_item(fsr.ITEM_POTION) == 3
    assert r.count_item(fsr.ITEM_MASTER_BALL) == 0


def test_ball_count_totals_the_balls_pocket():
    r = FireRedStateReader(_build(balls=[(fsr.ITEM_POKE_BALL, 5),
                                         (fsr.ITEM_GREAT_BALL, 3)]))
    assert r.ball_count() == 8


def test_count_heal_items_ignores_non_heals():
    r = FireRedStateReader(_build(items=[(fsr.ITEM_POTION, 3),
                                         (fsr.ITEM_SUPER_POTION, 2),
                                         (14, 4)]))   # Antidote: not a heal
    assert r.count_heal_items() == 5


# --- moves via the real PID/OTID decrypt + substructure unscramble ---


def test_read_moves_round_trip_through_encryption():
    pid, otid = 13, 0x8765_4321          # pid % 24 = 13 -> "EGMA" scramble
    m = _build()
    base = fsr.GPLAYER_PARTY             # slot 0
    m.w32(base + fsr.SLOT_PID_OFF, pid)
    m.w32(base + fsr.SLOT_OTID_OFF, otid)
    growth = (16).to_bytes(2, "little") + bytes(10)          # species 16
    attacks = struct.pack("<4H", 33, 39, 0, 0) + bytes([35, 30, 0, 0])
    data = _encode_slot_data(pid, otid, growth, attacks, b"E" * 12, b"M" * 12)
    m.wbytes(base + fsr.SLOT_DATA_OFF, data)
    r = FireRedStateReader(m)
    assert r.read_moves(0) == [(33, 35), (39, 30), (0, 0), (0, 0)]
    assert r.read_species(0) == 16       # same block decodes the species too


# --- per-mon details / fainted count ---


def test_read_party_details_and_fainted_count():
    m = _build()
    m.w8(fsr.GPLAYER_PARTY_COUNT, 3)
    for i, (lvl, hp, mx) in enumerate([(5, 19, 20), (7, 0, 24), (9, 30, 30)]):
        base = fsr.GPLAYER_PARTY + i * fsr.SLOT_SIZE
        m.w8(base + fsr.SLOT_LEVEL_OFF, lvl)
        m.w16(base + fsr.SLOT_CURHP_OFF, hp)
        m.w16(base + fsr.SLOT_MAXHP_OFF, mx)
    r = FireRedStateReader(m)
    assert r.read_party_details() == [
        {"level": 5, "hp": 19, "max_hp": 20},
        {"level": 7, "hp": 0, "max_hp": 24},
        {"level": 9, "hp": 30, "max_hp": 30},
    ]
    assert r.party_fainted_count() == 1


def test_party_fainted_count_zero_when_empty():
    assert FireRedStateReader(_build()).party_fainted_count() == 0
