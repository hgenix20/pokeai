"""Battle-perception tests: StateReader.read_battle + env battle_to_obs.

Addresses were verified against a live wild battle (Charmander vs Rattata on
Route 1); see the verified map in state_reader. These tests pin the parsing
logic and the normalization/gating in the observation block.
"""
from __future__ import annotations

from pokeai.emulator.state_reader import StateReader
from pokeai.env.pokemon_red_env import BATTLE_DIM, battle_to_obs

from tests.mock_emulator import MockEmulator, encode_state

# Gen-1 internal ids used below
CHARMANDER, RATTATA = 0xB0, 0xA5
FIRE, NORMAL = 0x14, 0x00


def _battle_mem(**overrides):
    """Charmander L5 (Fire) vs Rattata L3 (Normal) at half enemy HP."""
    base = dict(
        party_count=1,
        party_species=[CHARMANDER],
        party_levels=[5],
        party_hp=[20],
        party_max_hp=[20],
        party_types=[(FIRE, FIRE)],
        battle_type=1,  # wIsInBattle = wild
        active_slot=0,
        enemy_species=RATTATA,
        enemy_hp=7,
        enemy_max_hp=14,
        enemy_level=3,
        enemy_types=(NORMAL, NORMAL),
    )
    base.update(overrides)
    return encode_state(**base)


def test_read_battle_in_wild_battle():
    b = StateReader(MockEmulator([_battle_mem()])).read_battle()
    assert b.in_battle == 1
    assert b.own_hp_frac == 1.0
    assert b.own_level == 5
    assert b.own_type1 == FIRE
    assert b.enemy_species == RATTATA
    assert b.enemy_hp_frac == 0.5
    assert b.enemy_level == 3
    assert b.enemy_type1 == NORMAL


def test_enemy_fields_zeroed_out_of_battle():
    # Stale wEnemyMon present but not in battle -> enemy fields must read 0.
    b = StateReader(MockEmulator([_battle_mem(battle_type=0)])).read_battle()
    assert b.in_battle == 0
    assert b.enemy_hp_frac == 0.0
    assert b.enemy_species == 0
    assert b.enemy_level == 0
    # Own mon is always perceivable from the party lead.
    assert b.own_hp_frac == 1.0
    assert b.own_level == 5


def test_active_slot_selects_correct_own_mon():
    # Lead fainted, second mon (Squirtle-ish) is active in battle.
    mem = _battle_mem(
        party_count=2,
        party_species=[CHARMANDER, 0xB1],
        party_levels=[5, 7],
        party_hp=[0, 14],
        party_max_hp=[20, 20],
        party_types=[(FIRE, FIRE), (0x15, 0x15)],
        active_slot=1,
    )
    b = StateReader(MockEmulator([mem])).read_battle()
    assert b.own_level == 7
    assert b.own_hp_frac == 0.7
    assert b.own_type1 == 0x15  # Water


def test_battle_to_obs_shape_and_values():
    b = StateReader(MockEmulator([_battle_mem()])).read_battle()
    v = battle_to_obs(b)
    assert v.shape == (BATTLE_DIM,)
    assert v[0] == 1.0   # in_battle
    assert v[1] == 0.0   # not a trainer battle
    assert v[2] == 1.0   # own hp frac
    assert v[7] == 0.5   # enemy hp frac
    assert v[12] == 0.5  # hp advantage = own(1.0) - enemy(0.5)


def test_battle_to_obs_gated_out_of_battle():
    b = StateReader(MockEmulator([_battle_mem(battle_type=0)])).read_battle()
    v = battle_to_obs(b)
    assert v[0] == 0.0   # in_battle flag
    assert v[7] == 0.0   # enemy hp frac
    assert v[12] == 0.0  # advantage gated to 0 outside battle
