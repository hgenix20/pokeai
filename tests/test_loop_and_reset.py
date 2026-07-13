"""Tests for oscillation-loop breakout (Strategist) and the periodic full reset.

These cover the two failure modes the long stream hit: the agent ping-ponging
between a couple of tiles (which the frozen-position check never catches), and
the run-level curiosity map slowly flattening with no way to start fresh.
"""
from __future__ import annotations

from types import SimpleNamespace

from pokeai.agents.strategist_agent import (
    BREAKOUT_STEPS,
    LOOP_UNIQUE,
    LOOP_WINDOW,
    StrategistAgent,
)
from pokeai.config import Config
from pokeai.env.action_controller import Action
from pokeai.env.pokemon_red_env import PokemonRedEnv
from pokeai.knowledge.visit_memory import VisitMemory
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


# --- Loop breakout ---------------------------------------------------------

def test_oscillation_triggers_breakout(tmp_path):
    """Position keeps changing (A<->B) but covers only two tiles — the agent
    must notice the loop and commit to a breakout heading."""
    config = _config(tmp_path)
    open_grid = [[1] * 20 for _ in range(18)]
    env = PokemonRedEnv(config, emulator=MockEmulator([encode_state()], collision_grid=open_grid))
    agent = StrategistAgent(seed=7)
    agent.attach_env(env)
    env.reset()

    # Drive the overworld decision directly with positions that ping-pong over
    # two tiles, more than a full loop window's worth.
    thoughts = []
    for i in range(LOOP_WINDOW + 2):
        pos_x = 5 + (i % 2)  # alternates 5,6,5,6,...  -> only 2 unique tiles
        state = SimpleNamespace(current_map=0, x_pos=pos_x, y_pos=5)
        agent._act_overworld(state)
        thoughts.append(agent.thought)

    assert LOOP_UNIQUE >= 2  # sanity: two tiles must count as a loop
    assert any("Breaking out" in t for t in thoughts), thoughts[-4:]


def test_breakout_commits_for_several_steps(tmp_path):
    """Once breakout fires it should hold the escape heading for a budget of
    steps rather than re-deciding every frame."""
    config = _config(tmp_path)
    open_grid = [[1] * 20 for _ in range(18)]
    env = PokemonRedEnv(config, emulator=MockEmulator([encode_state()], collision_grid=open_grid))
    agent = StrategistAgent(seed=7)
    agent.attach_env(env)
    env.reset()

    for i in range(LOOP_WINDOW):
        state = SimpleNamespace(current_map=0, x_pos=5 + (i % 2), y_pos=5)
        agent._act_overworld(state)

    # Breakout should now be armed with a positive budget.
    assert agent._breakout is not None
    assert 0 < agent._breakout_left <= BREAKOUT_STEPS


# --- Full reset ------------------------------------------------------------

def test_visit_memory_reset_run_clears_everything():
    vm = VisitMemory()
    vm.record(0, 1, 1)
    vm.record(2, 3, 4)
    assert vm.unique_positions_run == 2
    vm.reset_run()
    assert vm.unique_positions_run == 0
    assert vm.maps_seen_run == set()
    assert vm.novelty(0, 1, 1) == 1.0  # forgotten -> fully novel again


def test_env_full_reset_wipes_curiosity(tmp_path):
    config = _config(tmp_path)
    env = PokemonRedEnv(config, emulator=MockEmulator([encode_state()]))
    env.reset()
    vm = env.reward_engine.visit_memory
    for _ in range(5):
        vm.record(0, 9, 9)
    assert vm.visit_count(0, 9, 9) == 5
    env.full_reset()
    assert vm.visit_count(0, 9, 9) == 0
