"""Tests for reward engine v2: battle shaping, healing, faints, level cap."""
from __future__ import annotations

from pokeai.config import RewardWeights
from pokeai.emulator.state_reader import BattleState, GameState
from pokeai.env.reward_engine import RewardEngine


def _state(**over) -> GameState:
    base = dict(
        party_count=1,
        party_total_hp=20,
        party_total_max_hp=20,
        party_total_level=5,
        money=0,
        current_map=0,
        y_pos=5,
        x_pos=5,
        badge_count=0,
        event_flags_set=0,
        battle_type=0,
        menu_cursor=0,
        party_fainted_count=0,
    )
    base.update(over)
    return GameState(**base)


def _battle(in_battle=1, own=1.0, enemy=1.0) -> BattleState:
    return BattleState(
        in_battle=in_battle,
        own_hp_frac=own,
        own_level=5,
        own_type1=0,
        own_type2=0,
        own_status=0,
        enemy_species=0xA5,
        enemy_hp_frac=enemy,
        enemy_level=3,
        enemy_type1=0,
        enemy_type2=0,
        enemy_status=0,
    )


def _engine(**weights) -> RewardEngine:
    return RewardEngine(RewardWeights(**weights))


class TestBattleShaping:
    def test_damage_reward(self):
        eng = _engine(battle_damage=10.0)
        eng.compute(_state(battle_type=1), battle=_battle(enemy=1.0))
        b = eng.compute(_state(battle_type=1), action=1, battle=_battle(enemy=0.5))
        assert abs(b.battle_damage - 5.0) < 1e-6

    def test_no_damage_reward_on_enemy_swap(self):
        # Trainer swap: enemy HP goes 0 -> 1.0; must not count as damage.
        eng = _engine(battle_damage=10.0, battle_win=0.0)
        eng.compute(_state(battle_type=2), battle=_battle(in_battle=2, enemy=0.0))
        b = eng.compute(_state(battle_type=2), action=1, battle=_battle(in_battle=2, enemy=1.0))
        assert b.battle_damage == 0.0

    def test_win_bonus_on_ko_end(self):
        eng = _engine(battle_win=10.0)
        eng.compute(_state(battle_type=1), battle=_battle(enemy=0.0))
        b = eng.compute(_state(), action=1, battle=_battle(in_battle=0, enemy=0.0))
        assert b.battle_win == 10.0
        assert eng.battles_won == 1

    def test_no_win_bonus_on_flee(self):
        eng = _engine(battle_win=10.0)
        eng.compute(_state(battle_type=1), battle=_battle(enemy=0.8))
        b = eng.compute(_state(), action=1, battle=_battle(in_battle=0, enemy=0.8))
        assert b.battle_win == 0.0
        assert eng.battles_won == 0

    def test_trainer_swap_pays_per_ko(self):
        eng = _engine(battle_win=10.0)
        eng.compute(_state(battle_type=2), battle=_battle(in_battle=2, enemy=0.0))
        b = eng.compute(
            _state(battle_type=2), action=1, battle=_battle(in_battle=2, enemy=1.0)
        )
        assert b.battle_win == 10.0
        assert eng.battles_won == 1


class TestFaintAndHeal:
    def test_faint_penalty(self):
        eng = _engine(faint_penalty=10.0)
        eng.compute(_state(party_count=2, party_total_hp=40, party_total_max_hp=40))
        b = eng.compute(
            _state(
                party_count=2,
                party_total_hp=20,
                party_total_max_hp=40,
                party_fainted_count=1,
            ),
            action=1,
        )
        assert b.faint == -10.0

    def test_heal_reward(self):
        eng = _engine(heal=10.0)
        eng.compute(_state(party_total_hp=10))
        b = eng.compute(_state(party_total_hp=20), action=1)
        assert abs(b.heal - 5.0) < 1e-6  # +0.5 of the bar * 10

    def test_no_heal_reward_after_blackout_respawn(self):
        eng = _engine(heal=10.0)
        eng.compute(_state(party_total_hp=20))
        eng.compute(_state(party_total_hp=0, party_fainted_count=1), action=1)
        b = eng.compute(_state(party_total_hp=20), action=1)  # respawn full heal
        assert b.heal == 0.0


class TestLevelCap:
    def test_level_reward_stops_at_cap(self):
        eng = _engine(level=1.0, level_cap=10)
        eng.compute(_state(party_total_level=8))
        b = eng.compute(_state(party_total_level=12), action=1)
        assert b.level == 2.0  # 8 -> 10 pays, 10 -> 12 doesn't
        b2 = eng.compute(_state(party_total_level=15), action=1)
        assert b2.level == 0.0

    def test_uncapped_by_default(self):
        eng = _engine(level=1.0)
        eng.compute(_state(party_total_level=8))
        b = eng.compute(_state(party_total_level=12), action=1)
        assert b.level == 4.0
