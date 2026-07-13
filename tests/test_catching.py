"""Tests for catching: bag reading, ball selection, the BattleBrain throw-a-ball
state machine, and the Catcher agent's decision to weaken-then-catch."""
from __future__ import annotations

from pokeai.agents import build_agent
from pokeai.agents.battle_brain import BattleBrain
from pokeai.agents.brain_agents import CatcherAgent, PlannerAgent
from pokeai.config import Config
from pokeai.emulator.state_reader import (
    ITEM_GREAT_BALL,
    ITEM_POKE_BALL,
    StateReader,
)
from pokeai.env.action_controller import Action
from pokeai.env.pokemon_red_env import PokemonRedEnv
from pokeai.knowledge import type_chart as tc
from tests.mock_emulator import MockEmulator, encode_state

POTION = 0x14  # any non-ball item


def _battle(**over):
    """A wild battle: our Charmander vs an Oddish, with a ball in the bag."""
    base = dict(
        party_count=1,
        party_hp=[18],
        party_max_hp=[20],
        party_levels=[10],
        party_species=[0xB0],
        party_types=[(tc.FIRE, tc.FIRE)],
        party_moves=[(0x34, 0x0A, 0, 0)],
        party_pp=[(25, 35, 0, 0)],
        battle_type=1,
        enemy_species=0xB9,
        enemy_hp=20,
        enemy_max_hp=20,
        enemy_level=8,
        enemy_types=(tc.GRASS, tc.POISON),
        bag_items=[(ITEM_POKE_BALL, 5)],
    )
    base.update(over)
    return encode_state(**base)


def _brain(snap):
    brain = BattleBrain(StateReader(MockEmulator([snap])))
    brain.want_catch = True
    return brain


# --- bag + ball selection ---


def test_read_bag_and_best_ball():
    reader = StateReader(MockEmulator([_battle(bag_items=[(POTION, 3), (ITEM_POKE_BALL, 5)])]))
    assert reader.read_bag() == [(POTION, 3), (ITEM_POKE_BALL, 5)]
    assert reader.best_ball() == (ITEM_POKE_BALL, 1)  # ball at bag slot 1


def test_best_ball_prefers_cheapest():
    reader = StateReader(MockEmulator([_battle(bag_items=[(ITEM_GREAT_BALL, 2), (ITEM_POKE_BALL, 5)])]))
    # Spend the plain Poké Ball first; hoard the Great Ball.
    assert reader.best_ball() == (ITEM_POKE_BALL, 1)


def test_best_ball_none_when_no_balls():
    reader = StateReader(MockEmulator([_battle(bag_items=[(POTION, 3)])]))
    assert reader.best_ball() is None


def test_read_bag_empty_does_not_query_zero_length_range():
    """Regression: at game start the bag is empty (count 0). read_bag must not
    ask the emulator for a zero-length range — real PyBoy rejects start==end."""
    reader = StateReader(MockEmulator([encode_state(party_count=1)]))  # no bag set -> count 0
    assert reader.read_bag() == []
    assert reader.best_ball() is None
    assert StateReader(MockEmulator([encode_state()])).list_selection_index() == 0


# --- BattleBrain catch state machine ---


def test_catch_moves_to_item_column():
    # Action menu, cursor on the right column (PkMn/RUN) — slide left to FIGHT/ITEM.
    brain = _brain(_battle(text_box_id=11, top_menu_y=14, top_menu_x=15, cursor_item=0))
    assert brain.decide() == int(Action.LEFT)


def test_catch_opens_item_menu():
    # Left column on FIGHT (cursor 0): step DOWN to ITEM, the next call opens it.
    brain = _brain(_battle(text_box_id=11, top_menu_y=14, top_menu_x=9, cursor_item=0))
    assert brain.decide() == int(Action.DOWN)
    brain2 = _brain(_battle(text_box_id=11, top_menu_y=14, top_menu_x=9, cursor_item=1))
    assert brain2.decide() == int(Action.A)
    assert brain2._catch_phase == "bag"


def test_catch_navigates_bag_to_the_ball():
    # Ball sits at bag index 1; cursor starts at 0 -> move DOWN toward it.
    brain = _brain(_battle(bag_items=[(POTION, 3), (ITEM_POKE_BALL, 5)],
                           list_scroll_offset=0, cursor_item=0))
    brain._catch_phase = "bag"
    assert brain.decide() == int(Action.DOWN)


def test_catch_throws_ball_when_on_it():
    # Cursor is on the ball (index 0) -> select it to throw.
    brain = _brain(_battle(bag_items=[(ITEM_POKE_BALL, 5)], list_scroll_offset=0, cursor_item=0))
    brain._catch_phase = "bag"
    assert brain.decide() == int(Action.A)
    assert brain._catch_phase == "thrown"
    assert brain._catch_attempts == 1


def test_no_catch_in_trainer_battle():
    brain = _brain(_battle(battle_type=2, text_box_id=11, top_menu_y=14, top_menu_x=9, cursor_item=0))
    assert brain.decide() == int(Action.A)   # just fights
    assert brain._catch_phase is None


def test_no_catch_without_a_ball():
    brain = _brain(_battle(bag_items=[(POTION, 3)], text_box_id=11,
                           top_menu_y=14, top_menu_x=9, cursor_item=0))
    assert brain.decide() == int(Action.A)   # no ball -> fight
    assert brain._catch_phase is None


# --- Catcher agent ---


def _config(tmp_path, agent_type="catcher") -> Config:
    rom = tmp_path / "rom.gb"
    state = tmp_path / "init.state"
    rom.write_bytes(b"\x00")
    state.write_bytes(b"\x00")
    return Config.model_validate(
        {
            "emulator": {"rom_path": str(rom), "init_state_path": str(state)},
            "environment": {"max_steps": 50, "observation_mode": "ram+tiles"},
            "agent": {"type": agent_type, "seed": 7},
            "logging": {"episodes": 1, "output_dir": str(tmp_path / "runs")},
        }
    )


def test_factory_builds_catcher(tmp_path):
    agent = build_agent(_config(tmp_path))
    assert agent.name == "catcher"
    assert "Catching" in agent.capabilities


def test_catcher_throws_at_weakened_new_species(tmp_path):
    config = _config(tmp_path)
    env = PokemonRedEnv(config, emulator=MockEmulator([_battle(enemy_hp=3, enemy_max_hp=20)]))
    agent = CatcherAgent(seed=7)
    agent.attach_env(env)
    env.reset()
    state = env.state_reader.read()
    agent._configure_battle(state)
    assert agent.brain.want_catch is True


def test_catcher_weakens_healthy_enemy_before_catching(tmp_path):
    config = _config(tmp_path)
    env = PokemonRedEnv(config, emulator=MockEmulator([_battle(enemy_hp=20, enemy_max_hp=20)]))
    agent = CatcherAgent(seed=7)
    agent.attach_env(env)
    env.reset()
    state = env.state_reader.read()
    agent._configure_battle(state)
    assert agent.brain.want_catch is False  # fight first, catch once it's weak


def test_catcher_skips_already_caught_species(tmp_path):
    config = _config(tmp_path)
    env = PokemonRedEnv(config, emulator=MockEmulator([_battle(enemy_hp=3, enemy_max_hp=20)]))
    agent = CatcherAgent(seed=7)
    agent.attach_env(env)
    env.reset()
    agent._caught.add(0xB9)  # already have an Oddish
    state = env.state_reader.read()
    agent._configure_battle(state)
    assert agent.brain.want_catch is False


def test_auto_catch_makes_any_brain_catch(tmp_path):
    """With the dashboard's auto-catch on, even the Planner throws a ball at a
    weakened new species; off, it just fights."""
    config = _config(tmp_path, agent_type="planner")
    env = PokemonRedEnv(config, emulator=MockEmulator([_battle(enemy_hp=3, enemy_max_hp=20)]))
    agent = PlannerAgent(seed=7)
    agent.attach_env(env)
    env.reset()
    state = env.state_reader.read()

    agent.auto_catch = False
    agent._configure_battle(state)
    assert agent.brain.want_catch is False

    agent.auto_catch = True
    agent._configure_battle(state)
    assert agent.brain.want_catch is True


def test_catcher_hunts_grass_when_healthy(tmp_path):
    config = _config(tmp_path)
    open_grid = [[1] * 20 for _ in range(18)]
    snap = encode_state(x_pos=5, y_pos=5, party_count=1, party_levels=[5],
                        party_hp=[20], party_max_hp=[20], grass_tile=0x52)
    from pokeai.emulator.screen_reader import ADDR_TILEMAP, TILEMAP_COLS
    for c in (8, 9):  # grass on the tile faced going UP
        snap[ADDR_TILEMAP + 7 * TILEMAP_COLS + c] = 0x52
    env = PokemonRedEnv(config, emulator=MockEmulator([snap], collision_grid=open_grid))
    agent = CatcherAgent(seed=7)
    agent.attach_env(env)
    obs, _ = env.reset()
    assert agent.act(obs) == int(Action.UP)
    assert "catch" in agent.thought.lower()
