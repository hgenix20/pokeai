"""Tests that don't require PyBoy or a ROM (pure logic only)."""
from __future__ import annotations

import numpy as np

from pokeai.config import RewardWeights
from pokeai.emulator.state_reader import GameState
from pokeai.env.reward_engine import RewardEngine
from pokeai.utils.hashing import hash_config


def _make_state(**overrides) -> GameState:
    base = dict(
        party_count=1,
        party_total_hp=20,
        party_total_max_hp=20,
        party_total_level=5,
        money=3000,
        current_map=0,
        y_pos=4,
        x_pos=6,
        badge_count=0,
        event_flags_set=0,
        battle_type=0,
        menu_cursor=0,
    )
    base.update(overrides)
    return GameState(**base)


def test_reward_first_step_zero():
    eng = RewardEngine(RewardWeights())
    r = eng.compute(_make_state())
    assert r.total == 0.0


def test_reward_badge_delta():
    eng = RewardEngine(RewardWeights())
    eng.compute(_make_state(badge_count=0))
    r = eng.compute(_make_state(badge_count=1))
    assert r.badge == 100.0
    assert r.total == 100.0


def test_reward_event_delta():
    eng = RewardEngine(RewardWeights())
    eng.compute(_make_state(event_flags_set=10))
    r = eng.compute(_make_state(event_flags_set=12))
    assert r.event == 2.0


def test_reward_new_map():
    eng = RewardEngine(RewardWeights())
    eng.compute(_make_state(current_map=0))
    r = eng.compute(_make_state(current_map=1))
    assert r.map == 0.5
    # Revisiting yields no map reward
    r2 = eng.compute(_make_state(current_map=0))
    assert r2.map == 0.0


def test_reward_blackout_once():
    eng = RewardEngine(RewardWeights())
    eng.compute(_make_state(party_count=1, party_total_hp=20))
    r = eng.compute(_make_state(party_count=1, party_total_hp=0))
    assert r.blackout == -50.0
    # Should not fire twice
    r2 = eng.compute(_make_state(party_count=1, party_total_hp=0))
    assert r2.blackout == 0.0


def test_reward_no_negative_deltas():
    # Losing levels shouldn't produce negative level reward
    eng = RewardEngine(RewardWeights())
    eng.compute(_make_state(party_total_level=20))
    r = eng.compute(_make_state(party_total_level=10))
    assert r.level == 0.0


def test_config_hash_stable():
    c1 = {"a": 1, "b": {"x": 2, "y": 3}}
    c2 = {"b": {"y": 3, "x": 2}, "a": 1}
    assert hash_config(c1) == hash_config(c2)


def test_config_hash_changes_on_value_change():
    c1 = {"reward": {"badge": 100.0}}
    c2 = {"reward": {"badge": 50.0}}
    assert hash_config(c1) != hash_config(c2)


def test_action_space_size():
    from pokeai.env.action_controller import ACTION_SPACE_SIZE
    assert ACTION_SPACE_SIZE == 7


def test_random_agent_returns_valid_action():
    from pokeai.agents.random_agent import RandomAgent
    from pokeai.env.action_controller import ACTION_SPACE_SIZE

    agent = RandomAgent(seed=0)
    obs = np.zeros(12, dtype=np.float32)
    for _ in range(100):
        a = agent.act(obs)
        assert 0 <= a < ACTION_SPACE_SIZE
