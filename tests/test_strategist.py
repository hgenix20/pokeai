"""Tests for the Strategist hybrid agent (battle routing + frontier walking)."""
from __future__ import annotations

import numpy as np

from pokeai.agents.strategist_agent import StrategistAgent
from pokeai.config import Config
from pokeai.env.action_controller import Action
from pokeai.env.pokemon_red_env import PokemonRedEnv, obs_dim_for
from pokeai.knowledge import type_chart as tc
from tests.mock_emulator import MockEmulator, encode_state

DIRECTIONS = {int(Action.UP), int(Action.DOWN), int(Action.LEFT), int(Action.RIGHT)}


def _config(tmp_path) -> Config:
    rom = tmp_path / "rom.gb"
    state = tmp_path / "init.state"
    rom.write_bytes(b"\x00")
    state.write_bytes(b"\x00")
    return Config.model_validate(
        {
            "emulator": {"rom_path": str(rom), "init_state_path": str(state)},
            "environment": {"max_steps": 50, "observation_mode": "ram+tiles"},
            "agent": {"type": "strategist", "seed": 7},
            "logging": {"episodes": 1, "output_dir": str(tmp_path / "runs")},
        }
    )


def _overworld_snapshot(x=5, y=5, **over):
    return encode_state(x_pos=x, y_pos=y, **over)


def _battle_snapshot():
    return encode_state(
        battle_type=1,
        party_species=[0xB0],
        party_types=[(tc.FIRE, tc.FIRE)],
        party_moves=[(0x34, 0x0A, 0, 0)],  # Ember, Scratch
        party_pp=[(25, 35, 0, 0)],
        enemy_species=0xB9,
        enemy_hp=20,
        enemy_max_hp=20,
        enemy_types=(tc.GRASS, tc.POISON),
        text_box_id=1,
    )


def _env_with(snapshots, config, collision=None):
    emu = MockEmulator(snapshots, collision_grid=collision)
    return PokemonRedEnv(config, emulator=emu)


def test_overworld_picks_a_direction(tmp_path):
    config = _config(tmp_path)
    open_grid = [[1] * 20 for _ in range(18)]
    env = _env_with([_overworld_snapshot()] * 10, config, collision=open_grid)
    agent = StrategistAgent(seed=7)
    agent.attach_env(env)
    obs, _ = env.reset()
    action = agent.act(obs)
    assert action in DIRECTIONS
    assert "Exploring" in agent.thought


def test_overworld_prefers_novel_ground(tmp_path):
    config = _config(tmp_path)
    open_grid = [[1] * 20 for _ in range(18)]
    env = _env_with([_overworld_snapshot()] * 10, config, collision=open_grid)
    agent = StrategistAgent(seed=7)
    agent.attach_env(env)
    obs, _ = env.reset()
    # Make every neighbor except east heavily visited.
    vm = env.reward_engine.visit_memory
    for _ in range(60):
        vm.record(0, 5, 4)   # north (x, y-1)
        vm.record(0, 5, 6)   # south
        vm.record(0, 4, 5)   # west
    assert agent.act(obs) == int(Action.RIGHT)


def test_battle_routes_to_brain(tmp_path):
    config = _config(tmp_path)
    env = _env_with([_battle_snapshot()] * 10, config)
    agent = StrategistAgent(seed=7)
    agent.attach_env(env)
    obs, _ = env.reset()
    action = agent.act(obs)
    # No menu open in the snapshot -> the brain advances text with A.
    assert action == int(Action.A)
    assert "Oddish" in agent.thought or "battle" in agent.thought.lower()


def test_rescue_cycle_when_stuck(tmp_path):
    config = _config(tmp_path)
    blocked = [[0] * 20 for _ in range(18)]
    env = _env_with([_overworld_snapshot()] * 64, config, collision=blocked)
    agent = StrategistAgent(seed=7)
    agent.attach_env(env)
    obs, _ = env.reset()
    actions = [agent.act(obs) for _ in range(12)]  # position never changes
    # The rescue cycle must include an interaction press (A or B).
    assert any(a in (int(Action.A), int(Action.B)) for a in actions)


def test_blind_fallback_without_env(tmp_path):
    config = _config(tmp_path)
    agent = StrategistAgent(seed=7)
    obs = np.zeros(obs_dim_for(config.environment.observation_mode), dtype=np.float32)
    assert agent.act(obs) in DIRECTIONS


def test_reads_and_advances_dialogue(tmp_path):
    """When a message box is on screen, the agent reads it and presses A."""
    config = _config(tmp_path)
    rows = [""] * 14 + ["PROF.OAK: Hello!", "Take this."]
    env = _env_with([_overworld_snapshot(screen_text=rows)] * 4, config)
    agent = StrategistAgent(seed=7)
    agent.attach_env(env)
    obs, _ = env.reset()
    action = agent.act(obs)
    assert action == int(Action.A)
    assert agent.thought.startswith("Reading:")


def test_closes_overworld_menu(tmp_path):
    """An open menu (cursor visible) is read and backed out of with B."""
    config = _config(tmp_path)
    rows = ["", ">POKEMON", " ITEM", " SAVE"]
    env = _env_with([_overworld_snapshot(screen_text=rows)] * 4, config)
    agent = StrategistAgent(seed=7)
    agent.attach_env(env)
    obs, _ = env.reset()
    action = agent.act(obs)
    assert action == int(Action.B)
    assert "Menu" in agent.thought


def test_narrates_walking_through_grass(tmp_path):
    """When the forward heading faces grass, the agent says so (so viewers
    see it's about to trigger a wild battle)."""
    config = _config(tmp_path)
    open_grid = [[1] * 20 for _ in range(18)]
    snap = _overworld_snapshot(grass_tile=0x52)
    env = _env_with([snap] * 4, config, collision=open_grid)
    # Plant grass on the tile the player faces going UP (row 7, cols 8-9).
    from pokeai.emulator.screen_reader import ADDR_TILEMAP, TILEMAP_COLS
    for c in (8, 9):
        snap[ADDR_TILEMAP + 7 * TILEMAP_COLS + c] = 0x52
    agent = StrategistAgent(seed=7)
    agent.attach_env(env)
    obs, _ = env.reset()
    # Make every direction except UP heavily visited so the heading is UP.
    vm = env.reward_engine.visit_memory
    for _ in range(80):
        vm.record(0, 5, 6)   # south
        vm.record(0, 4, 5)   # west
        vm.record(0, 6, 5)   # east
    action = agent.act(obs)
    assert action == int(Action.UP)
    assert "grass" in agent.thought.lower()
