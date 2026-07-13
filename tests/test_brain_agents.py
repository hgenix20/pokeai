"""Tests for the three GameSense-based brains (planner / tactician / learner)."""
from __future__ import annotations

import numpy as np
import pytest

from pokeai.agents import build_agent
from pokeai.agents.brain_agents import (
    BattleTacticianAgent,
    LearnerAgent,
    PlannerAgent,
)
from pokeai.config import Config
from pokeai.env.action_controller import Action
from pokeai.env.pokemon_red_env import PokemonRedEnv, obs_dim_for
from pokeai.knowledge import type_chart as tc
from tests.mock_emulator import MockEmulator, encode_state

DIRECTIONS = {int(Action.UP), int(Action.DOWN), int(Action.LEFT), int(Action.RIGHT)}
BRAINS = [PlannerAgent, BattleTacticianAgent, LearnerAgent]


def _config(tmp_path, agent_type="planner") -> Config:
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


def _env_with(snapshots, config, collision=None):
    return PokemonRedEnv(config, emulator=MockEmulator(snapshots, collision_grid=collision))


def _overworld(x=5, y=5, **over):
    return encode_state(x_pos=x, y_pos=y, party_count=1, party_levels=[5], **over)


@pytest.mark.parametrize("agent_type", ["planner", "tactician", "learner"])
def test_factory_builds_each_brain(tmp_path, agent_type):
    agent = build_agent(_config(tmp_path, agent_type))
    assert agent.name == agent_type
    assert agent.capabilities  # has a capability profile for the dashboard


@pytest.mark.parametrize("Brain", BRAINS)
def test_overworld_returns_a_move(tmp_path, Brain):
    config = _config(tmp_path)
    open_grid = [[1] * 20 for _ in range(18)]
    env = _env_with([_overworld()] * 8, config, collision=open_grid)
    agent = Brain(seed=7)
    agent.attach_env(env)
    obs, _ = env.reset()
    action = agent.act(obs)
    assert action in DIRECTIONS | {int(Action.A), int(Action.B)}
    assert agent.goal_text          # goal is set for the dashboard
    assert agent.thought


@pytest.mark.parametrize("Brain", BRAINS)
def test_battle_routes_to_brain(tmp_path, Brain):
    config = _config(tmp_path)
    snap = encode_state(
        battle_type=1, party_count=1, party_species=[0xB0], party_types=[(tc.FIRE, tc.FIRE)],
        party_moves=[(0x34, 0x0A, 0, 0)], party_pp=[(25, 35, 0, 0)],
        enemy_species=0xB9, enemy_hp=20, enemy_max_hp=20, enemy_types=(tc.GRASS, tc.POISON),
    )
    env = _env_with([snap] * 6, config)
    agent = Brain(seed=7)
    agent.attach_env(env)
    obs, _ = env.reset()
    action = agent.act(obs)
    assert action in DIRECTIONS | {int(Action.A), int(Action.B)}
    assert agent.active_capability == "Battling"


def test_intro_presses_a(tmp_path):
    """At the title/intro (no party, origin position) the brain presses A."""
    config = _config(tmp_path)
    env = _env_with([encode_state(party_count=0, current_map=0, x_pos=0, y_pos=0)] * 4, config)
    agent = PlannerAgent(seed=7)
    agent.attach_env(env)
    obs, _ = env.reset()
    assert agent.act(obs) == int(Action.A)


def test_tactician_steps_into_grass(tmp_path):
    """When healthy and facing grass, the Tactician steps in to find a battle."""
    config = _config(tmp_path)
    open_grid = [[1] * 20 for _ in range(18)]
    snap = _overworld(grass_tile=0x52, party_hp=[20], party_max_hp=[20])
    # Plant grass on the tile faced going UP (row 7, cols 8-9).
    from pokeai.emulator.screen_reader import ADDR_TILEMAP, TILEMAP_COLS
    for c in (8, 9):
        snap[ADDR_TILEMAP + 7 * TILEMAP_COLS + c] = 0x52
    env = _env_with([snap] * 4, config, collision=open_grid)
    agent = BattleTacticianAgent(seed=7)
    agent.attach_env(env)
    obs, _ = env.reset()
    assert agent.act(obs) == int(Action.UP)
    assert "grass" in agent.thought.lower()


def test_blind_without_env(tmp_path):
    config = _config(tmp_path)
    agent = LearnerAgent(seed=7)
    obs = np.zeros(obs_dim_for(config.environment.observation_mode), dtype=np.float32)
    assert agent.act(obs) in DIRECTIONS


def test_naming_screen_picks_a_preset(tmp_path):
    """On the name-entry preset menu the brain moves off NEW NAME and confirms
    a preset, instead of dropping into the unfinishable letter keyboard."""
    config = _config(tmp_path)
    # Preset menu with the cursor on NEW NAME -> should press DOWN.
    rows = ["", ">NEW NAME", " RED", " ASH", " JACK"]
    from pokeai.emulator.screen_reader import ADDR_TILEMAP, MENU_CURSOR, TILEMAP_COLS
    snap = encode_state(party_count=0, screen_text=rows)
    snap[ADDR_TILEMAP + 1 * TILEMAP_COLS] = MENU_CURSOR
    env = _env_with([snap] * 4, config)
    agent = PlannerAgent(seed=7)
    agent.attach_env(env)
    obs, _ = env.reset()
    assert agent.act(obs) == int(Action.DOWN)

    # Cursor on a preset -> should confirm with A.
    rows2 = ["", " NEW NAME", ">RED", " ASH", " JACK"]
    snap2 = encode_state(party_count=0, screen_text=rows2)
    snap2[ADDR_TILEMAP + 2 * TILEMAP_COLS] = MENU_CURSOR
    env2 = _env_with([snap2] * 4, config)
    agent2 = PlannerAgent(seed=7)
    agent2.attach_env(env2)
    obs2, _ = env2.reset()
    assert agent2.act(obs2) == int(Action.A)


def test_adjacent_npc_triggers_interaction(tmp_path):
    """Facing a person/object pre-starter queues a face-then-A interaction (how
    it talks to NPCs and grabs the starter from Oak's table)."""
    config = _config(tmp_path)
    open_grid = [[1] * 20 for _ in range(18)]
    emu = MockEmulator([encode_state(party_count=0, x_pos=5, y_pos=5)] * 6,
                       collision_grid=open_grid)
    # Sprite at tile col 7, row 8 = the tile faced going LEFT (outside the
    # player's own-sprite exclusion block, so it reads as an NPC).
    emu._sprites = [(56, 64, 1)]
    env = PokemonRedEnv(config, emulator=emu)
    agent = PlannerAgent(seed=7)
    agent.attach_env(env)
    obs, _ = env.reset()
    assert agent.act(obs) == int(Action.LEFT)  # step toward the object to face it
    assert agent.act(obs) == int(Action.A)     # then interact


def test_learner_records_lessons(tmp_path):
    config = _config(tmp_path)
    open_grid = [[1] * 20 for _ in range(18)]
    env = _env_with([_overworld()] * 30, config, collision=open_grid)
    agent = LearnerAgent(seed=7)
    agent.attach_env(env)
    obs, _ = env.reset()
    for _ in range(30):
        agent.act(obs)
    # The learner accumulates plain-language lessons for the dashboard.
    assert isinstance(agent.lessons, list)
