"""Integration tests: full StateReader -> RewardEngine -> Env -> loop -> logger
-> aggregator chain, using a mock emulator (no PyBoy, no ROM).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pokeai.config import Config
from pokeai.env.pokemon_red_env import BATTLE_DIM, OBS_DIM, PokemonRedEnv
from pokeai.training.loop import run as run_training

from tests.mock_emulator import MockEmulator, encode_state


def _make_config(tmp_path: Path, agent_type: str = "random", episodes: int = 3,
                 badge_weight: float = 100.0) -> Config:
    """Build a validated Config with dummy ROM/state files that exist."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    rom = tmp_path / "rom.gb"
    rom.write_bytes(b"\x00")
    state = tmp_path / "init.gb_state"
    state.write_bytes(b"\x00")
    return Config.model_validate(
        {
            "emulator": {
                "rom_path": str(rom),
                "init_state_path": str(state),
                "render": False,
                "sound": False,
                "emulation_speed": 0,
            },
            "environment": {"max_steps": 10, "frame_skip": 1, "observation_mode": "ram"},
            "agent": {"type": agent_type, "seed": 1},
            "reward": {
                "weights": {
                    "badge": badge_weight,
                    "event": 1.0,
                    "map": 0.5,
                    "level": 0.1,
                    "blackout": 50.0,
                }
            },
            "logging": {
                "run_id": "test_run",
                "output_dir": str(tmp_path / "runs"),
                "episodes": episodes,
            },
        }
    )


def _progression_snapshots() -> list[dict[int, int]]:
    """Scripted episode: explore new map, earn a badge, then black out."""
    return [
        # t0: start, map 0, 1 badge bit unset
        encode_state(current_map=0, party_levels=[5], party_hp=[20], party_max_hp=[20]),
        # t1: move to map 1 (map reward)
        encode_state(current_map=1, party_levels=[5], party_hp=[18], party_max_hp=[20]),
        # t2: earn a badge (badge reward), level up
        encode_state(current_map=1, badge_byte=0x01, party_levels=[6],
                     party_hp=[15], party_max_hp=[20]),
        # t3: blackout (all HP 0) -> terminates
        encode_state(current_map=1, badge_byte=0x01, party_levels=[6],
                     party_hp=[0], party_max_hp=[20]),
    ]


def test_env_step_and_reward_signals(tmp_path):
    config = _make_config(tmp_path)
    emu = MockEmulator(_progression_snapshots())
    env = PokemonRedEnv(config, emulator=emu)

    obs, info = env.reset()
    assert obs.shape == (OBS_DIM + BATTLE_DIM,)
    assert info["badge_count"] == 0

    # Step to map 1 -> map reward 0.5
    obs, reward, term, trunc, info = env.step(3)  # UP
    assert reward == pytest.approx(0.5)
    assert info["unique_maps_visited"] == 2
    assert not term

    # Step to badge + level -> badge 100 + level 0.1
    obs, reward, term, trunc, info = env.step(1)  # A
    assert reward == pytest.approx(100.0 + 0.1)
    assert info["badge_count"] == 1

    # Step to blackout -> -50 and terminated
    obs, reward, term, trunc, info = env.step(1)
    assert reward == pytest.approx(-50.0)
    assert term is True
    assert info["blackout_occurred"] is True
    env.close()
    assert emu.closed


def test_full_run_writes_jsonl_and_report(tmp_path):
    config = _make_config(tmp_path, agent_type="random", episodes=3)
    # Fresh mock per run; loop calls reset() which resets snapshot index
    emu = MockEmulator(_progression_snapshots())
    run_dir = run_training(config, emulator=emu)

    episodes_path = run_dir / "episodes.jsonl"
    assert episodes_path.exists()
    lines = [ln for ln in episodes_path.read_text().splitlines() if ln.strip()]
    assert len(lines) == 3  # AC2 analog

    # Each line parses and has required fields
    for line in lines:
        rec = json.loads(line)
        assert rec["run_id"] == "test_run"
        assert rec["agent_name"] == "random"
        assert "cumulative_reward" in rec
        assert rec["terminated_reason"] in {"BLACKOUT", "MAX_STEPS", "ALL_BADGES"}

    # eval_report.json auto-generated
    report_path = run_dir / "eval_report.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text())
    assert report["episode_count"] == 3
    assert "cumulative_reward" in report["numeric_summary"]


def test_blackout_terminates_episode(tmp_path):
    config = _make_config(tmp_path, episodes=1)
    emu = MockEmulator(_progression_snapshots())
    run_dir = run_training(config, emulator=emu)
    rec = json.loads((run_dir / "episodes.jsonl").read_text().splitlines()[0])
    # Episode should end via blackout before hitting max_steps (10)
    assert rec["terminated_reason"] == "BLACKOUT"
    assert rec["blackout_occurred"] is True
    assert rec["steps_taken"] < config.environment.max_steps


def test_agent_swap_no_code_change(tmp_path):
    """AC5 analog: same code path, different agent via config only."""
    cfg_random = _make_config(tmp_path / "a", agent_type="random", episodes=1)
    cfg_heur = _make_config(tmp_path / "b", agent_type="heuristic", episodes=1)

    run_random = run_training(
        cfg_random, emulator=MockEmulator(_progression_snapshots())
    )
    run_heur = run_training(
        cfg_heur, emulator=MockEmulator(_progression_snapshots())
    )

    meta_r = json.loads((run_random / "run.json").read_text())
    meta_h = json.loads((run_heur / "run.json").read_text())
    assert meta_r["agent_name"] == "random"
    assert meta_h["agent_name"] == "heuristic"


def test_config_hash_differs_by_reward_weight(tmp_path):
    """AC6 analog: differing reward weights -> differing config hash."""
    cfg_a = _make_config(tmp_path / "a", badge_weight=100.0, episodes=1)
    cfg_b = _make_config(tmp_path / "b", badge_weight=50.0, episodes=1)

    run_a = run_training(cfg_a, emulator=MockEmulator(_progression_snapshots()))
    run_b = run_training(cfg_b, emulator=MockEmulator(_progression_snapshots()))

    hash_a = json.loads((run_a / "run.json").read_text())["config_hash"]
    hash_b = json.loads((run_b / "run.json").read_text())["config_hash"]
    assert hash_a != hash_b


def test_state_reader_parses_bcd_money_and_multi_party(tmp_path):
    """Exercise StateReader parsing via mock: BCD money, multi-slot party."""
    config = _make_config(tmp_path)
    snap = encode_state(
        party_count=2,
        party_hp=[20, 10],
        party_max_hp=[25, 15],
        party_levels=[7, 9],
        money=12345,
        badge_byte=0b00000011,  # 2 badges
        event_bytes=[0xFF, 0x0F],  # 8 + 4 = 12 event bits
    )
    emu = MockEmulator([snap])
    env = PokemonRedEnv(config, emulator=emu)
    state = env.state_reader.read()
    assert state.party_count == 2
    assert state.party_total_hp == 30
    assert state.party_total_max_hp == 40
    assert state.party_total_level == 16
    assert state.money == 12345
    assert state.badge_count == 2
    assert state.event_flags_set == 12
    env.close()
