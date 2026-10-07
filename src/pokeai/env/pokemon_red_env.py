"""Pokémon Red environment, Gymnasium-compatible.

reset() always loads from the configured init_state_path.
Termination: all 8 badges (success) or party blackout.
Truncation: max_steps reached.

Observation modes (config.environment.observation_mode):
  "ram"        12-dim vector of RAM-derived fields
  "ram+tiles"  ram + a semantic tile grid (what each tile *is*: walkable, wall,
               grass, NPC, player), neighbor-novelty, a screen-perception block
               (is text/menu showing, where the cursor is), and battle vision.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from pokeai.config import Config
from pokeai.emulator.pyboy_wrapper import EmulatorWrapper
from pokeai.emulator.screen_reader import ScreenContext, ScreenReader, ScreenView, TileClass
from pokeai.emulator.state_reader import BattleState, GameState, StateReader
from pokeai.env.action_controller import ACTION_SPACE_SIZE, ActionController
from pokeai.env.reward_engine import RewardEngine


# Observation vector layout. Order is fixed; agents should treat this as opaque.
OBS_FIELDS = (
    "party_count",
    "party_total_hp",
    "party_total_max_hp",
    "party_total_level",
    "money",
    "current_map",
    "y_pos",
    "x_pos",
    "badge_count",
    "event_flags_set",
    "battle_type",
    "menu_cursor",
)
OBS_DIM = len(OBS_FIELDS)

# Tile grid dimensions (PyBoy Pokemon Gen 1 game area)
TILE_ROWS, TILE_COLS = 18, 20
TILE_DIM = TILE_ROWS * TILE_COLS
_TILE_NORM = float(max(int(c) for c in TileClass))  # scale class ids into [0, 1]

# Neighbor-novelty features: novelty of the current position and its 4
# neighbors, so "move toward unexplored ground" is perceivable (and learnable).
NOVELTY_DIM = 5

# Screen-perception block: lets the agent know what kind of screen it is looking
# at and whether someone is talking to it — the difference between reading the
# game and mashing buttons. context one-hot(4) + has_text(1) + cursor_row(1)
# + grass_nearby(1).
PERCEPTION_DIM = 7

# Battle perception block (appended last). Gives the agent vision during fights,
# where the tile grid is blank: in-battle/trainer flags, own & enemy HP fraction,
# level, types, status, and HP/level advantage. See state_reader.read_battle.
BATTLE_DIM = 14
_TYPE_NORM = 26.0  # max Gen-1 type id (0x1A Dragon); scales type ids into ~[0, 1]


def state_to_obs(state: GameState) -> np.ndarray:
    d = asdict(state)
    return np.array([d[k] for k in OBS_FIELDS], dtype=np.float32)


def perception_to_obs(view: ScreenView, grass_nearby: bool) -> np.ndarray:
    """Normalized screen-perception vector (length PERCEPTION_DIM)."""
    ctx = view.context
    return np.array(
        [
            1.0 if ctx == ScreenContext.FREE_ROAM else 0.0,
            1.0 if ctx == ScreenContext.DIALOGUE else 0.0,
            1.0 if ctx == ScreenContext.MENU else 0.0,
            1.0 if ctx == ScreenContext.BATTLE else 0.0,
            1.0 if view.has_text else 0.0,
            (view.cursor_row / TILE_ROWS) if view.cursor_row >= 0 else 0.0,
            1.0 if grass_nearby else 0.0,
        ],
        dtype=np.float32,
    )


def obs_dim_for(observation_mode: str) -> int:
    """Total observation width for a mode. Single source of truth shared by the
    env and the agent factory so the two can never disagree on obs_dim."""
    if observation_mode == "ram+tiles":
        spatial = OBS_DIM + TILE_DIM + NOVELTY_DIM + PERCEPTION_DIM
    else:
        spatial = OBS_DIM
    return spatial + BATTLE_DIM


def battle_to_obs(b: BattleState) -> np.ndarray:
    """Normalized battle-perception vector (length BATTLE_DIM)."""
    in_b = 1.0 if b.in_battle != 0 else 0.0
    return np.array(
        [
            in_b,
            1.0 if b.in_battle == 2 else 0.0,  # trainer (vs wild) battle
            b.own_hp_frac,
            b.own_level / 100.0,
            b.own_type1 / _TYPE_NORM,
            b.own_type2 / _TYPE_NORM,
            1.0 if b.own_status != 0 else 0.0,
            b.enemy_hp_frac,
            b.enemy_level / 100.0,
            b.enemy_type1 / _TYPE_NORM,
            b.enemy_type2 / _TYPE_NORM,
            1.0 if b.enemy_status != 0 else 0.0,
            (b.own_hp_frac - b.enemy_hp_frac) * in_b,  # HP advantage (0 out of battle)
            (b.own_level - b.enemy_level) / 100.0 * in_b,  # level advantage
        ],
        dtype=np.float32,
    )


class PokemonRedEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, config: Config, emulator: EmulatorWrapper | None = None):
        """If `emulator` is provided, it is used as-is (dependency injection for
        testing or alternate backends). Otherwise a real PyBoy-backed
        EmulatorWrapper is constructed from config.
        """
        super().__init__()
        self.config = config
        self._use_tiles = config.environment.observation_mode == "ram+tiles"

        self.emulator = emulator or EmulatorWrapper(
            rom_path=config.emulator.rom_path,
            render=config.emulator.render,
            sound=config.emulator.sound,
            emulation_speed=config.emulator.emulation_speed,
            # The dashboard displays emulator frames, so keep the screen
            # buffer rendered even when the PyBoy window is off.
            capture_screen=config.ui.enabled,
            # When the dashboard is up, emulate the APU so its sound toggle can
            # play game audio without opening PyBoy's own window. Cheap enough
            # for interactive use; left off on the headless training path.
            emulate_sound=config.ui.enabled,
        )
        self.state_reader = StateReader(self.emulator)
        self.screen_reader = ScreenReader(self.emulator)
        self.action_controller = ActionController(
            self.emulator, frame_skip=config.environment.frame_skip
        )
        self.reward_engine = RewardEngine(config.reward.weights)

        # Gymnasium spaces
        self.action_space = spaces.Discrete(ACTION_SPACE_SIZE)
        obs_dim = obs_dim_for(config.environment.observation_mode)
        self.observation_space = spaces.Box(
            low=0.0,
            high=np.finfo(np.float32).max,
            shape=(obs_dim,),
            dtype=np.float32,
        )

        self._step_count = 0
        self._cumulative_reward = 0.0

    # --- Gymnasium API ---

    def reset(
        self, *, seed: int | None = None, options: dict[str, Any] | None = None
    ) -> tuple[np.ndarray, dict[str, Any]]:
        super().reset(seed=seed)
        # The loop may override which save state to load (e.g. the title screen
        # for an occasional from-the-beginning run); default is the checkpoint.
        state_path = (options or {}).get("state_path") or self.config.emulator.init_state_path
        self.emulator.load_state(state_path)
        self.reward_engine.reset_episode()
        self._step_count = 0
        self._cumulative_reward = 0.0

        state = self.state_reader.read()
        battle = self.state_reader.read_battle()
        # Seed reward engine with initial state (returns 0 reward)
        self.reward_engine.compute(state, battle=battle)
        obs = self._build_obs(state, battle)
        info = self._info(state, reward_breakdown=None)
        return obs, info

    def full_reset(self) -> None:
        """Wipe the run-level curiosity memory so the next reset() explores from
        a blank slate. Called periodically by the loop (full_reset_every) to keep
        a long stream from settling into a rut. The next reset() still reloads
        init_state like any other episode."""
        self.reward_engine.reset_run()

    def step(
        self, action: int
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        # Settle directional moves to one clean tile only when actually walking.
        # In a menu or dialogue a direction nudges a cursor, so a fixed press is
        # needed (settling would hold the button and over-scroll the cursor).
        settle_moves = True
        try:
            in_battle = self.state_reader.read().battle_type != 0
            settle_moves = self.screen_reader.view(in_battle=in_battle).context == ScreenContext.FREE_ROAM
        except Exception:
            settle_moves = True
        self.action_controller.apply(action, settle_moves=settle_moves)
        self._step_count += 1

        state = self.state_reader.read()
        battle = self.state_reader.read_battle()
        breakdown = self.reward_engine.compute(state, action=action, battle=battle)
        reward = breakdown.total
        self._cumulative_reward += reward

        terminated = self._is_terminated(state)
        truncated = self._step_count >= self.config.environment.max_steps

        obs = self._build_obs(state, battle)
        info = self._info(state, breakdown)
        return obs, reward, terminated, truncated, info

    def close(self) -> None:
        self.emulator.close()

    # --- Internals ---

    def _build_obs(self, state: GameState, battle_state: BattleState) -> np.ndarray:
        ram_obs = state_to_obs(state)
        # Battle perception block is appended last in every observation mode so
        # the agent can perceive fights (where the tile grid is blank/zero).
        battle = battle_to_obs(battle_state)
        if not self._use_tiles:
            return np.concatenate([ram_obs, battle])
        # Semantic tile grid: what each visible tile *is* (walkable / wall /
        # grass / NPC / player), normalized — far richer than a binary
        # walkable mask, so the policy can tell grass from a path from a person.
        sem = self.screen_reader.semantic_tiles().astype(np.float32).flatten() / _TILE_NORM
        if sem.shape[0] != TILE_DIM:  # defensive: unexpected grid size
            padded = np.zeros(TILE_DIM, dtype=np.float32)
            padded[: min(sem.shape[0], TILE_DIM)] = sem[:TILE_DIM]
            sem = padded
        # Novelty of here + 4 neighbors, so "move toward unexplored ground" is
        # perceivable (and therefore learnable) by the policy.
        vm = self.reward_engine.visit_memory
        m, x, y = state.current_map, state.x_pos, state.y_pos
        novelty = np.array(
            [
                vm.novelty(m, x, y),
                vm.novelty(m, x, y - 1),  # north
                vm.novelty(m, x, y + 1),  # south
                vm.novelty(m, x - 1, y),  # west
                vm.novelty(m, x + 1, y),  # east
            ],
            dtype=np.float32,
        )
        # Screen-perception block: is text/menu showing, where the cursor is.
        view = self.screen_reader.view(in_battle=battle_state.in_battle != 0)
        perception = perception_to_obs(view, self.screen_reader.grass_nearby())
        return np.concatenate([ram_obs, sem, novelty, perception, battle])

    def _is_terminated(self, state: GameState) -> bool:
        # Success: all 8 badges
        if state.badge_count >= 8:
            return True
        # Failure: blackout (all party fainted, party non-empty)
        if state.all_party_fainted:
            return True
        return False

    def _info(self, state: GameState, reward_breakdown) -> dict[str, Any]:
        engine = self.reward_engine
        info = {
            "step_count": self._step_count,
            "cumulative_reward": self._cumulative_reward,
            "badge_count": state.badge_count,
            "events_set": state.event_flags_set,
            "current_map": state.current_map,
            "unique_maps_visited": engine.unique_maps_visited,
            "party_total_level": state.party_total_level,
            "blackout_occurred": engine.blackout_occurred,
            # Skills-profile metrics
            "unique_tiles_visited": engine.unique_tiles_visited,
            "repeat_action_rate": engine.repeat_action_rate,
            "steps_stuck": engine.steps_stuck,
            "total_steps_stuck": engine.total_steps_stuck,
            "curiosity_reward_total": engine.curiosity_reward_total,
            "recovered_from_low_hp": engine.recovered_from_low_hp,
            "battles_won": engine.battles_won,
        }
        if reward_breakdown is not None:
            info["reward_breakdown"] = asdict(reward_breakdown)
        return info
