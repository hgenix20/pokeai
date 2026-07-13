"""Tests for the dashboard's milestone / goal tracker (pure logic, no pygame)."""
from __future__ import annotations

from pokeai.emulator.state_reader import GameState
from pokeai.ui.goals import GoalTracker


def gs(**over) -> GameState:
    """GameState with sensible defaults; override only the fields a test cares about."""
    base = dict(
        party_count=0,
        party_total_hp=20,
        party_total_max_hp=20,
        party_total_level=5,
        money=0,
        current_map=0x00,
        y_pos=0,
        x_pos=0,
        badge_count=0,
        event_flags_set=0,
        battle_type=0,
        menu_cursor=0,
    )
    base.update(over)
    return GameState(**base)


def test_starts_with_no_goals_done():
    t = GoalTracker()
    assert t.completed == 0
    assert t.total == 12
    assert t.current_goal() == "Get your first Pokémon"


def test_getting_starter_unlocks_first_goal():
    t = GoalTracker()
    t.observe(gs(party_count=0))
    assert t.completed == 0
    t.observe(gs(party_count=1))
    assert t.completed == 1
    assert t.current_goal() == "Set out on Route 1"
    assert t.recent_unlock() == "Get your first Pokémon"


def test_map_milestones_unlock_by_visiting():
    t = GoalTracker()
    t.observe(gs(party_count=1, current_map=0x0C))  # Route 1
    t.observe(gs(party_count=1, current_map=0x01))  # Viridian City
    labels = {g.label for g in t.goals if g.done}
    assert "Set out on Route 1" in labels
    assert "Reach Viridian City" in labels


def test_badges_unlock_badge_goals():
    t = GoalTracker()
    t.observe(gs(party_count=1, badge_count=1, current_map=0x02))  # Pewter + Boulder
    labels = {g.label for g in t.goals if g.done}
    assert "Reach Pewter City" in labels
    assert "Win the Boulder Badge" in labels


def test_team_level_milestone():
    t = GoalTracker()
    t.observe(gs(party_count=1, party_total_level=9))
    assert all(g.label != "Train your team to Lv10+" or not g.done for g in t.goals)
    t.observe(gs(party_count=1, party_total_level=12))
    assert any(g.label == "Train your team to Lv10+" and g.done for g in t.goals)


def test_goals_are_sticky_after_leaving_a_map():
    t = GoalTracker()
    t.observe(gs(party_count=1, current_map=0x01))  # Viridian
    t.observe(gs(party_count=1, current_map=0x00))  # back to Pallet
    assert any(g.label == "Reach Viridian City" and g.done for g in t.goals)


def test_reset_run_clears_progress():
    t = GoalTracker()
    t.observe(gs(party_count=1, badge_count=2, current_map=0x03))
    assert t.completed > 0
    t.reset_run()
    assert t.completed == 0
    assert t.maps_seen == set()
    assert t.recent_unlock() is None
