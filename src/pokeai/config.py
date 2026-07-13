"""Configuration models with pydantic validation.

All Phase 1 settings flow through this module. Invalid configs fail at load time.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator


class EmulatorConfig(BaseModel):
    rom_path: Path = Field(..., description="Path to pokemon_red.gb ROM")
    init_state_path: Path = Field(..., description="Path to initial save state")
    # Optional title-screen state. When set together with
    # environment.title_reset_every, the agent occasionally starts from the very
    # beginning (title screen) and must play the intro itself. None = never.
    title_state_path: Path | None = Field(
        None, description="Path to a title-screen save state (built by make_title_state.py)"
    )
    render: bool = False
    sound: bool = False
    emulation_speed: int = Field(0, description="0 = unlimited")

    @field_validator("rom_path", "init_state_path")
    @classmethod
    def _path_must_exist(cls, v: Path) -> Path:
        if not v.exists():
            raise ValueError(f"Path does not exist: {v}")
        return v

    @field_validator("title_state_path")
    @classmethod
    def _optional_path_must_exist(cls, v: Path | None) -> Path | None:
        if v is not None and not v.exists():
            raise ValueError(f"Path does not exist: {v}")
        return v


class EnvironmentConfig(BaseModel):
    max_steps: int = Field(2048, gt=0)
    frame_skip: int = Field(24, gt=0)
    # "ram" = 12 RAM fields; "ram+tiles" adds the semantic tile grid + screen perception
    observation_mode: Literal["ram", "ram+tiles"] = "ram"
    # Every episode reloads init_state, but the run-level visit memory (curiosity
    # map) persists and slowly flattens, which can settle the agent into a rut.
    # Every N episodes, do a *complete* reset: wipe that accumulated memory so
    # exploration starts genuinely fresh. 0 = never (memory persists all run).
    full_reset_every: int = Field(0, ge=0)
    # Every N episodes, start from the title screen instead of the usual
    # checkpoint, so the agent plays the intro (press START, NEW GAME, name,
    # pick a starter) itself. Requires emulator.title_state_path. 0 = never.
    title_reset_every: int = Field(0, ge=0)


class AgentConfig(BaseModel):
    # strategist = the original hybrid expert; planner/tactician/learner/catcher/
    # adventurer = the GameSense-based brains (adventurer adds the roots-driven
    # Needs/Goal arbiter). (The old dqn/ppo learners were retired.)
    type: Literal[
        "random", "heuristic", "strategist",
        "planner", "tactician", "learner", "catcher", "adventurer",
    ]
    seed: int = 42


class RewardWeights(BaseModel):
    badge: float = 100.0
    event: float = 1.0
    map: float = 0.5
    level: float = 0.1
    blackout: float = 50.0
    # Curiosity: intrinsic novelty bonus = weight * 1/sqrt(visit_count).
    # Visit counts persist across episodes within a run. 0 = disabled.
    curiosity: float = 0.0
    # Anti-looping: penalty when the same action repeats with no
    # position change for `stuck_threshold` steps. 0 = disabled.
    stuck_penalty: float = 0.0
    stuck_threshold: int = Field(8, gt=0)
    # --- Battle shaping (reward v2; all default 0 = disabled / back-compat) ---
    # Reward per fraction of enemy max HP dealt while in battle (so dealing a
    # full HP bar of damage = 1.0 * weight). Makes attacking learnable.
    battle_damage: float = 0.0
    # Bonus when a battle ends with the enemy mon at 0 HP (per KO; trainer
    # battles pay once per fainted enemy mon via HP-restore transitions).
    battle_win: float = 0.0
    # Penalty each time one of our own party mons faints (blackout stacks on top).
    faint_penalty: float = 0.0
    # Reward per fraction of party max HP restored (Pokecenter / potions).
    # Post-blackout respawn healing is excluded.
    heal: float = 0.0
    # Level reward cap: party levels above this stop paying `level` reward
    # (anti-grind exploit). 0 = uncapped.
    level_cap: int = Field(0, ge=0)


class RewardConfig(BaseModel):
    weights: RewardWeights = Field(default_factory=RewardWeights)


class LoggingConfig(BaseModel):
    run_id: str | None = None  # auto-generated if None
    output_dir: Path = Path("runs/")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    episodes: int = Field(10, gt=0)


class UIConfig(BaseModel):
    """Diagnostic dashboard (pygame window with HUD, minimap, and run controls)."""

    enabled: bool = False
    scale: int = Field(3, ge=1, le=6, description="Game view scale factor")
    start_paused: bool = True  # wait for the user to press START before running
    # --- Streaming / playability options (toggleable live in the Options menu) ---
    sound: bool = False  # play emulated game audio through the dashboard window
    volume: int = Field(80, ge=0, le=100, description="Audio volume percent")
    # Layout preset: "full" (all diagnostic panels), "clean" (big game + minimal
    # HUD + goals, for stream), or "game" (game view only).
    view_mode: Literal["full", "clean", "game"] = "full"
    # Smooth per-frame rendering of the game view during a step (vs. one frame
    # per env step, which looks choppy). Costs CPU; auto-throttled to ~60fps.
    smooth_rendering: bool = True
    # Auto-catch: during a wild battle, whatever strategy is playing will weaken
    # a *new* species and throw a ball at it on its own (great for streaming).
    # Toggle live in the Options menu. The dedicated Catcher does this regardless.
    auto_catch: bool = True


class TrainingConfig(BaseModel):
    """DQN training hyperparameters (used when agent.type == "dqn")."""

    learning_rate: float = 1e-3
    gamma: float = 0.99
    # Epsilon-greedy exploration schedule (linear decay over steps)
    epsilon_start: float = 1.0
    epsilon_end: float = 0.05
    epsilon_decay_steps: int = Field(50_000, gt=0)
    # Replay buffer
    buffer_size: int = Field(100_000, gt=0)
    batch_size: int = Field(64, gt=0)
    learn_start: int = Field(1_000, ge=0)  # steps collected before learning begins
    train_interval: int = Field(4, gt=0)  # gradient step every N env steps
    target_update_interval: int = Field(1_000, gt=0)  # target net sync period
    # Network
    hidden_size: int = Field(256, gt=0)
    # --- Anti-collapse (entropy floor against perseveration) ---
    # Double DQN: online net selects the next action, target net evaluates it.
    # Curbs the max-operator overestimation bias that drives Q-value collapse.
    double_dqn: bool = True
    # Boltzmann exploitation: sample from softmax(z-scored Q / T) instead of
    # argmax. Z-scoring makes T scale-invariant and caps the top action's
    # probability even if raw Q-values diverge — a structural entropy floor
    # against perseveration. 0 = legacy greedy argmax (for ablation).
    boltzmann_temperature: float = Field(1.0, ge=0.0)
    # --- PPO (used when agent.type == "ppo"; shares learning_rate/gamma/
    # hidden_size/batch_size with DQN above) ---
    rollout_steps: int = Field(2048, gt=0)  # env steps per policy update
    ppo_epochs: int = Field(4, gt=0)  # passes over each rollout
    clip_range: float = Field(0.2, gt=0.0)  # PPO clipped-surrogate epsilon
    gae_lambda: float = Field(0.95, ge=0.0, le=1.0)
    entropy_coef: float = Field(0.01, ge=0.0)  # exploration pressure
    value_coef: float = Field(0.5, ge=0.0)
    # Checkpointing: fresh start by default (evaluation = start from scratch)
    checkpoint_interval: int = Field(50, gt=0)  # episodes between saves
    checkpoint_dir: Path = Path("checkpoints/")
    resume_from: Path | None = None  # checkpoint path to resume; None = from scratch
    device: Literal["auto", "cuda", "cpu"] = "auto"


class Config(BaseModel):
    emulator: EmulatorConfig
    environment: EnvironmentConfig = Field(default_factory=EnvironmentConfig)
    agent: AgentConfig
    reward: RewardConfig = Field(default_factory=RewardConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    training: TrainingConfig = Field(default_factory=TrainingConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Config":
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)
