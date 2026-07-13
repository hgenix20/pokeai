"""Tests for the dashboard's cognition views: ThoughtTracker (event narration),
VisitMemory (spatial memory / 2A-2 curiosity foundation), and agent thoughts.

All pure logic — no pygame, no emulator.
"""
from __future__ import annotations

import numpy as np

from pokeai.agents.heuristic_agent import HeuristicAgent
from pokeai.agents.random_agent import RandomAgent
from pokeai.emulator.state_reader import GameState
from pokeai.env.pokemon_red_env import OBS_FIELDS
from pokeai.knowledge.visit_memory import VisitMemory
from pokeai.ui.thoughts import ThoughtTracker


def _state(**kwargs) -> GameState:
    defaults = dict(
        party_count=0,
        party_total_hp=0,
        party_total_max_hp=0,
        party_total_level=0,
        money=3000,
        current_map=0,
        y_pos=5,
        x_pos=5,
        badge_count=0,
        event_flags_set=0,
        battle_type=0,
        menu_cursor=0,
    )
    defaults.update(kwargs)
    return GameState(**defaults)


def _texts(tracker: ThoughtTracker) -> list[str]:
    return [t.text.lower() for t in tracker.thoughts]


# --- ThoughtTracker ---


def test_thoughts_first_observation():
    tracker = ThoughtTracker()
    tracker.observe(0, _state(current_map=0))
    assert any("pallet town" in t for t in _texts(tracker))


def test_thoughts_new_map():
    tracker = ThoughtTracker()
    tracker.observe(0, _state(current_map=0))
    tracker.observe(1, _state(current_map=0x0C, x_pos=6))
    assert any("route 1" in t for t in _texts(tracker))


def test_thoughts_stuck_detection_and_recovery():
    tracker = ThoughtTracker()
    tracker.observe(0, _state())
    for step in range(1, 12):
        tracker.observe(step, _state())  # never moves
    assert tracker.steps_stuck >= ThoughtTracker.STUCK_THRESHOLD
    assert any("stuck" in t for t in _texts(tracker))

    # Moving again clears the counter and narrates recovery
    tracker.observe(12, _state(x_pos=6))
    assert tracker.steps_stuck == 0
    assert any("moving again" in t for t in _texts(tracker))


def test_thoughts_stuck_not_counted_in_battle():
    tracker = ThoughtTracker()
    tracker.observe(0, _state())
    for step in range(1, 12):
        tracker.observe(step, _state(battle_type=1))  # stationary but in battle
    assert tracker.steps_stuck == 0
    assert not any("stuck" in t for t in _texts(tracker))


def test_thoughts_battle_transitions():
    tracker = ThoughtTracker()
    tracker.observe(0, _state())
    tracker.observe(1, _state(battle_type=1))
    tracker.observe(2, _state(battle_type=0))
    texts = _texts(tracker)
    assert any("battle started" in t for t in texts)
    assert any("battle is over" in t for t in texts)


def test_thoughts_got_pokemon():
    tracker = ThoughtTracker()
    tracker.observe(0, _state(party_count=0), [])
    tracker.observe(
        1,
        _state(party_count=1, party_total_hp=19, party_total_max_hp=19),
        [0xB0],  # Charmander
    )
    assert any("charmander" in t for t in _texts(tracker))


def test_thoughts_blackout_reported_once():
    tracker = ThoughtTracker()
    tracker.observe(0, _state(party_count=1, party_total_hp=10, party_total_max_hp=20))
    tracker.observe(1, _state(party_count=1, party_total_hp=0, party_total_max_hp=20))
    tracker.observe(2, _state(party_count=1, party_total_hp=0, party_total_max_hp=20))
    blackout_thoughts = [t for t in _texts(tracker) if "black" in t]
    assert len(blackout_thoughts) == 1


def test_thoughts_badge_earned():
    tracker = ThoughtTracker()
    tracker.observe(0, _state(badge_count=0))
    tracker.observe(1, _state(badge_count=1, x_pos=6))
    assert any("badge" in t for t in _texts(tracker))


def test_thoughts_reset_episode():
    tracker = ThoughtTracker()
    tracker.observe(0, _state())
    tracker.observe(1, _state(current_map=1, x_pos=6))
    assert len(tracker.thoughts) > 0
    tracker.reset_episode()
    assert len(tracker.thoughts) == 0
    assert tracker.steps_stuck == 0


def test_agent_thoughts_in_log():
    tracker = ThoughtTracker()
    tracker.add_agent_thought(5, "Trying UP")
    assert tracker.thoughts[0].kind == "agent"
    assert tracker.thoughts[0].step == 5
    # Empty thoughts are not logged
    tracker.add_agent_thought(6, "")
    assert len(tracker.thoughts) == 1


# --- VisitMemory ---


def test_visit_memory_counts():
    mem = VisitMemory()
    mem.record(0, 5, 5)
    mem.record(0, 5, 5)
    mem.record(0, 6, 5)
    assert mem.visit_count(0, 5, 5) == 2
    assert mem.visit_count(0, 6, 5) == 1
    assert mem.unique_positions_run == 2
    assert mem.maps_seen_run == {0}
    assert mem.total_steps_run == 3


def test_visit_memory_episode_reset_keeps_run_memory():
    mem = VisitMemory()
    mem.record(0, 5, 5)
    mem.record(1, 2, 2)
    mem.reset_episode()
    assert mem.unique_positions_episode == 0
    assert len(mem.maps_seen_episode) == 0
    # Run-level memory persists (this is what "learning across episodes" shows)
    assert mem.unique_positions_run == 2
    assert mem.maps_seen_run == {0, 1}


def test_visit_memory_novelty_decreases_with_visits():
    mem = VisitMemory()
    assert mem.novelty(0, 1, 1) == 1.0  # never visited
    mem.record(0, 1, 1)
    first = mem.novelty(0, 1, 1)
    for _ in range(10):
        mem.record(0, 1, 1)
    later = mem.novelty(0, 1, 1)
    assert later < first < 1.0


def test_visit_memory_top_visited():
    mem = VisitMemory()
    for _ in range(5):
        mem.record(0, 1, 1)
    mem.record(0, 2, 2)
    top = mem.top_visited(1)
    assert top[0] == ((0, 1, 1), 5)


# --- Agent thoughts ---


def test_random_agent_produces_thought():
    agent = RandomAgent(seed=1)
    obs = np.zeros(len(OBS_FIELDS), dtype=np.float32)
    agent.act(obs)
    assert agent.thought
    assert "random" in agent.thought.lower()


def test_heuristic_agent_thought_reflects_mode():
    agent = HeuristicAgent(seed=1)
    obs = np.zeros(len(OBS_FIELDS), dtype=np.float32)

    agent.act(obs)
    assert "exploring" in agent.thought.lower()

    obs_battle = obs.copy()
    obs_battle[OBS_FIELDS.index("battle_type")] = 1
    agent.act(obs_battle)
    assert "battle" in agent.thought.lower()
