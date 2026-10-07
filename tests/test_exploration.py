"""Tests for the exploration layer: tile/perception observation, curiosity,
anti-looping, and the skills profile.

All mock-emulator based — no ROM, no torch required.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from pokeai.config import Config, RewardWeights
from pokeai.emulator.screen_reader import TileClass
from pokeai.emulator.state_reader import GameState
from pokeai.env.pokemon_red_env import (
    BATTLE_DIM,
    NOVELTY_DIM,
    OBS_DIM,
    PERCEPTION_DIM,
    TILE_DIM,
    PokemonRedEnv,
)
from pokeai.env.reward_engine import RewardEngine
from pokeai.evaluation.aggregate import aggregate, build_skills_profile
from pokeai.training.loop import run as run_training

from tests.mock_emulator import MockEmulator, encode_state

_TILE_NORM = float(max(int(c) for c in TileClass))


def _state(**kwargs) -> GameState:
    defaults = dict(
        party_count=1,
        party_total_hp=20,
        party_total_max_hp=20,
        party_total_level=5,
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


def _make_config(tmp_path: Path, **overrides) -> Config:
    tmp_path.mkdir(parents=True, exist_ok=True)
    rom = tmp_path / "rom.gb"
    rom.write_bytes(b"\x00")
    state = tmp_path / "init.gb_state"
    state.write_bytes(b"\x00")
    base = {
        "emulator": {
            "rom_path": str(rom),
            "init_state_path": str(state),
            "render": False,
            "sound": False,
            "emulation_speed": 0,
        },
        "environment": {"max_steps": 10, "frame_skip": 1, "observation_mode": "ram"},
        "agent": {"type": "random", "seed": 1},
        "logging": {
            "run_id": "test_2a",
            "output_dir": str(tmp_path / "runs"),
            "episodes": 3,
        },
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and key in base:
            base[key].update(value)
        else:
            base[key] = value
    return Config.model_validate(base)


# --- 2A-1: Tile-grid observation ---


def test_ram_obs_dim_unchanged(tmp_path):
    config = _make_config(tmp_path)
    emu = MockEmulator([encode_state()])
    env = PokemonRedEnv(config, emulator=emu)
    obs, _ = env.reset()
    assert obs.shape == (OBS_DIM + BATTLE_DIM,)
    env.close()


def test_ram_tiles_obs_includes_semantic_grid(tmp_path):
    """The tile block now encodes *what each tile is* (walkable/wall/...),
    normalized, not a raw binary collision mask."""
    config = _make_config(
        tmp_path, environment={"max_steps": 10, "frame_skip": 1, "observation_mode": "ram+tiles"}
    )
    grid = np.zeros((18, 20), dtype=np.uint32)
    grid[5, :] = 1  # one walkable row; the rest are walls
    emu = MockEmulator([encode_state()], collision_grid=grid)
    env = PokemonRedEnv(config, emulator=emu)
    obs, _ = env.reset()
    assert obs.shape == (OBS_DIM + TILE_DIM + NOVELTY_DIM + PERCEPTION_DIM + BATTLE_DIM,)
    tiles = obs[OBS_DIM : OBS_DIM + TILE_DIM].reshape(18, 20)
    walkable = int(TileClass.WALKABLE) / _TILE_NORM
    wall = int(TileClass.WALL) / _TILE_NORM
    assert np.allclose(tiles[5], walkable)   # the walkable row
    assert np.allclose(tiles[0], wall)       # a wall row
    env.close()


def test_ram_tiles_obs_marks_player_center(tmp_path):
    """With no collision data, tiles are UNKNOWN except the player center."""
    config = _make_config(
        tmp_path, environment={"max_steps": 10, "frame_skip": 1, "observation_mode": "ram+tiles"}
    )
    emu = MockEmulator([encode_state()])  # no collision grid
    env = PokemonRedEnv(config, emulator=emu)
    obs, _ = env.reset()
    assert obs.shape == (OBS_DIM + TILE_DIM + NOVELTY_DIM + PERCEPTION_DIM + BATTLE_DIM,)
    tiles = obs[OBS_DIM : OBS_DIM + TILE_DIM].reshape(18, 20)
    player = int(TileClass.PLAYER) / _TILE_NORM
    assert np.allclose(tiles[8, 8:10], player)  # player occupies the center block
    assert tiles[0].sum() == 0                  # unknown elsewhere
    env.close()


def test_novelty_features_in_obs(tmp_path):
    """The last NOVELTY_DIM values are novelty of here + 4 neighbors:
    1.0 everywhere at episode start except the current position (visited once)."""
    config = _make_config(
        tmp_path, environment={"max_steps": 10, "frame_skip": 1, "observation_mode": "ram+tiles"}
    )
    emu = MockEmulator([encode_state(x_pos=5, y_pos=5)])
    env = PokemonRedEnv(config, emulator=emu)
    obs, _ = env.reset()
    novelty = obs[OBS_DIM + TILE_DIM : OBS_DIM + TILE_DIM + NOVELTY_DIM]
    assert novelty.shape == (NOVELTY_DIM,)
    # Current position was just recorded once -> novelty < 1; neighbors unvisited -> 1.0
    assert novelty[0] < 1.0
    assert all(n == 1.0 for n in novelty[1:])
    env.close()


def test_obs_space_matches_obs_dim_helper(tmp_path):
    """Env observation space and the shared obs_dim_for() agree, for both modes.

    Regression: build_agent once recomputed obs_dim with a stale formula and
    disagreed with the env (377 vs 391), crashing the normalizer at train time.
    """
    from pokeai.env.pokemon_red_env import obs_dim_for

    for mode in ("ram", "ram+tiles"):
        config = _make_config(tmp_path, environment={"observation_mode": mode})
        env = PokemonRedEnv(config, emulator=MockEmulator([encode_state()]))
        assert env.observation_space.shape[0] == obs_dim_for(mode)
        env.close()


# --- 2A-2: Curiosity reward (capability 5.1) ---


def test_curiosity_rewards_novel_positions():
    weights = RewardWeights(curiosity=1.0)
    engine = RewardEngine(weights)
    engine.compute(_state(x_pos=5))  # seed

    # First visit to a new position: full novelty bonus
    b1 = engine.compute(_state(x_pos=6), action=6)
    assert b1.curiosity == pytest.approx(1.0)  # never visited -> novelty 1.0

    # Returning to an already-visited position: reduced bonus
    b2 = engine.compute(_state(x_pos=5), action=5)
    assert 0 < b2.curiosity < 1.0

    # Re-revisiting drops further
    engine.compute(_state(x_pos=6), action=6)
    b3 = engine.compute(_state(x_pos=5), action=5)
    assert b3.curiosity < b2.curiosity


def test_curiosity_persists_across_episodes():
    """Capability 5.1: visit counts persist across episodes within a run."""
    weights = RewardWeights(curiosity=1.0)
    engine = RewardEngine(weights)

    # Episode 1: visit (0,6,5)
    engine.compute(_state(x_pos=5))
    engine.compute(_state(x_pos=6), action=6)

    # Episode 2: the same position should be less novel now
    engine.reset_episode()
    engine.compute(_state(x_pos=5))
    b = engine.compute(_state(x_pos=6), action=6)
    assert b.curiosity < 1.0  # remembered from episode 1


def test_curiosity_disabled_by_default():
    engine = RewardEngine(RewardWeights())  # curiosity defaults to 0
    engine.compute(_state())
    b = engine.compute(_state(x_pos=6), action=6)
    assert b.curiosity == 0.0


# --- 2A-3: Anti-loop adaptability (capability 5.2) ---


def test_stuck_penalty_after_repeated_action_no_movement():
    weights = RewardWeights(stuck_penalty=1.0, stuck_threshold=3)
    engine = RewardEngine(weights)
    engine.compute(_state())  # seed

    # Same action, same position, repeated
    penalties = []
    for _ in range(5):
        b = engine.compute(_state(), action=3)  # never moves
        penalties.append(b.stuck)

    # First two repeats: no penalty yet (threshold 3)
    assert penalties[0] == 0.0
    assert penalties[1] == 0.0
    # At/after threshold: penalty applies
    assert penalties[2] == pytest.approx(-1.0)
    assert penalties[4] == pytest.approx(-1.0)


def test_stuck_resets_when_moving():
    weights = RewardWeights(stuck_penalty=1.0, stuck_threshold=3)
    engine = RewardEngine(weights)
    engine.compute(_state())

    for _ in range(3):
        engine.compute(_state(), action=3)
    assert engine.steps_stuck >= 3

    # Moving clears the counter
    b = engine.compute(_state(x_pos=6), action=3)
    assert b.stuck == 0.0
    assert engine.steps_stuck == 0


def test_stuck_not_counted_in_battle():
    weights = RewardWeights(stuck_penalty=1.0, stuck_threshold=3)
    engine = RewardEngine(weights)
    engine.compute(_state())

    # Stationary but in battle: no stuck penalty
    for _ in range(5):
        b = engine.compute(_state(battle_type=1), action=1)
        assert b.stuck == 0.0


def test_repeat_action_rate_metric():
    engine = RewardEngine(RewardWeights())
    engine.compute(_state())
    # 4 steps: 2 repeats-without-moving, 2 with movement
    engine.compute(_state(), action=3)          # not a repeat (first action)
    engine.compute(_state(), action=3)          # repeat, no move
    engine.compute(_state(x_pos=6), action=3)   # moved
    engine.compute(_state(x_pos=7), action=6)   # moved, different action
    assert engine.repeat_action_rate == pytest.approx(1 / 4)


# --- 5.3 Adversity proxy ---


def test_low_hp_recovery_tracked():
    engine = RewardEngine(RewardWeights())
    engine.compute(_state(party_total_hp=20, party_total_max_hp=20))
    # Drop to critical
    engine.compute(_state(party_total_hp=4, party_total_max_hp=20), action=1)
    assert not engine.recovered_from_low_hp
    # Recover above 50%
    engine.compute(_state(party_total_hp=12, party_total_max_hp=20), action=1)
    assert engine.recovered_from_low_hp


# --- Skills profile ---


def test_skills_profile_structure():
    records = [
        {
            "unique_tiles_visited": tiles,
            "repeat_action_rate": rate,
            "blackout_occurred": blackout,
            "cumulative_reward": reward,
            "badges_earned": 0,
        }
        for tiles, rate, blackout, reward in [
            (10, 0.5, True, -40.0),
            (12, 0.45, True, -38.0),
            (30, 0.3, False, 5.0),
            (45, 0.2, False, 12.0),
        ]
    ]
    profile = build_skills_profile(records)

    assert profile["exploration"]["trend"] == "rising"
    assert profile["exploration"]["verdict"] == "improving"
    assert profile["anti_looping"]["trend"] == "falling"
    assert profile["anti_looping"]["verdict"] == "improving"
    assert profile["survival"]["verdict"] == "improving"  # blackouts falling
    assert profile["progress"]["verdict"] == "improving"  # reward rising


def _profile_records(rewards, tiles, repeats, blackouts=None, badges=None):
    n = len(rewards)
    blackouts = blackouts if blackouts is not None else [False] * n
    badges = badges if badges is not None else [0] * n
    return [
        {
            "cumulative_reward": rewards[i],
            "unique_tiles_visited": tiles[i],
            "repeat_action_rate": repeats[i],
            "blackout_occurred": blackouts[i],
            "badges_earned": badges[i],
        }
        for i in range(n)
    ]


def test_benign_taper_reads_steady_not_regressing():
    """A mild epsilon-decay taper (like the fixed DQN run) must NOT be flagged
    as regressing/collapsed — the failure the old half-mean trend metric had."""
    rewards = [20, 18, 19, 17, 16, 16, 15, 16, 15, 16, 14, 15]   # +18.5 -> +15
    tiles = [180, 175, 185, 170, 165, 160, 170, 162, 158, 160, 155, 161]  # 178 -> 159
    repeats = [0.10, 0.11, 0.09, 0.12, 0.13, 0.14, 0.12, 0.15, 0.14, 0.16, 0.15, 0.15]
    profile = build_skills_profile(_profile_records(rewards, tiles, repeats))
    assert profile["progress"]["verdict"] == "steady"
    assert profile["exploration"]["verdict"] == "steady"
    assert profile["anti_looping"]["verdict"] == "steady"
    assert all(p["verdict"] != "collapsed" for p in profile.values())


def test_collapse_reads_collapsed():
    """The death-spiral (like the baseline run): reward sign-flips, exploration
    craters, perseveration sets in. Each must be flagged 'collapsed'."""
    rewards = [22, 20, 24, 18, 10, 5, -5, -15, -25, -30, -28, -26]   # +21 -> -27
    tiles = [210, 230, 200, 250, 120, 90, 70, 60, 40, 35, 30, 28]    # 222 -> 33 (peak 250)
    repeats = [0.10, 0.12, 0.09, 0.11, 0.20, 0.30, 0.40, 0.50, 0.65, 0.70, 0.72, 0.68]
    profile = build_skills_profile(_profile_records(rewards, tiles, repeats))
    assert profile["progress"]["verdict"] == "collapsed"      # reward sign-flip
    assert profile["exploration"]["verdict"] == "collapsed"   # tiles cratered vs peak
    assert profile["anti_looping"]["verdict"] == "collapsed"  # perseveration


def test_report_lists_collapsed_skills(tmp_path):
    run_dir = tmp_path / "collapse_run"
    run_dir.mkdir(parents=True)
    rewards = [22, 20, 24, 18, 10, 5, -5, -15, -25, -30, -28, -26]
    tiles = [210, 230, 200, 250, 120, 90, 70, 60, 40, 35, 30, 28]
    repeats = [0.10, 0.12, 0.09, 0.11, 0.20, 0.30, 0.40, 0.50, 0.65, 0.70, 0.72, 0.68]
    recs = _profile_records(rewards, tiles, repeats)
    (run_dir / "episodes.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    report = aggregate(run_dir)
    assert report["collapsed_skills"] == [
        "anti_looping",
        "exploration",
        "progress",
    ]


def test_full_run_writes_skills_profile(tmp_path):
    config = _make_config(tmp_path)
    snapshots = [
        encode_state(current_map=0, party_levels=[5], party_hp=[20], party_max_hp=[20]),
        encode_state(current_map=1, party_levels=[5], party_hp=[20], party_max_hp=[20]),
    ]
    emu = MockEmulator(snapshots)
    run_dir = run_training(config, emulator=emu)

    profile_path = run_dir / "skills_profile.json"
    assert profile_path.exists()
    profile = json.loads(profile_path.read_text())
    assert "exploration" in profile
    assert "anti_looping" in profile
    assert "per_episode" in profile["exploration"]

    # eval_report has the 2A gate metric
    report = json.loads((run_dir / "eval_report.json").read_text())
    assert "episodes_left_starting_map" in report
    assert "blackout_rate" in report


def test_capability_metrics_in_episode_log(tmp_path):
    config = _make_config(tmp_path)
    emu = MockEmulator([encode_state()])
    run_dir = run_training(config, emulator=emu)

    lines = [ln for ln in (run_dir / "episodes.jsonl").read_text().splitlines() if ln.strip()]
    rec = json.loads(lines[0])
    for field in (
        "unique_tiles_visited",
        "repeat_action_rate",
        "total_steps_stuck",
        "curiosity_reward_total",
        "recovered_from_low_hp",
    ):
        assert field in rec, f"missing capability field: {field}"


# --- Aggregate still works with old-format records (backward compat) ---


def test_aggregate_handles_missing_capability_fields(tmp_path):
    run_dir = tmp_path / "old_run"
    run_dir.mkdir(parents=True)
    old_record = {
        "run_id": "old",
        "agent_name": "random",
        "config_hash": "abc",
        "episode_index": 0,
        "steps_taken": 100,
        "badges_earned": 0,
        "events_triggered": 0,
        "unique_maps_visited": 2,
        "total_party_level": 0,
        "blackout_occurred": True,
        "terminated_reason": "BLACKOUT",
        "cumulative_reward": -45.0,
        "wall_clock_seconds": 10.0,
    }
    (run_dir / "episodes.jsonl").write_text(json.dumps(old_record) + "\n")
    report = aggregate(run_dir)  # must not raise
    assert report["episode_count"] == 1
