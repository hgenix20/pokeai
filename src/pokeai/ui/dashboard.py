"""Diagnostic + streaming dashboard: game view + HUD, AI-vision minimap,
thoughts, memory, goal tracker, run controls, manual takeover, and an options
menu.

Layout (full view, window 1160x560 at scale 3):

    +------------------------------+----------------+----------------+
    | game view (160x144 * scale)  | AI VISION      | THOUGHTS       |
    |  with HUD overlay            |  minimap       |  (AI bubble +  |
    |  (party, map, badges, HP)    |  + legend      |   event log)   |
    |                              | DIAGNOSTICS    | MEMORY / GOALS |
    +------------------------------+----------------+----------------+
    | ● RUNNING  ● AI  Strategy   [START][PAUSE]... SPEED  OPTIONS    |
    +----------------------------------------------------------------+

View modes (Tab to cycle): full (all panels) -> clean (big game + goals) ->
game (game only). Stream-friendly.

Controls:
    Space  - start / pause
    N      - single step (while paused)
    R      - restart current episode (discards it)
    1/2/3/4 - speed 1x / 2x / 4x / MAX
    Tab    - cycle view mode (full / clean / game)
    O      - open / close the options menu
    M      - toggle manual takeover
    Esc/Q  - stop run (or close the options menu if open)
    Close window - same as stop

Manual mode (M): you drive the game.
    Arrows - D-pad     X - A button     Z - B button
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import numpy as np

from pokeai.config import UIConfig
from pokeai.env.action_controller import ACTION_TO_BUTTON, Action
from pokeai.evaluation.metrics import RunMetrics
from pokeai.knowledge.game_data import map_name, species_name, status_text, type_name
from pokeai.knowledge.visit_memory import VisitMemory
from pokeai.ui.audio import AudioPlayer
from pokeai.ui.goals import GoalTracker
from pokeai.ui.run_control import RunControl, RunState
from pokeai.ui.thoughts import ThoughtTracker

if TYPE_CHECKING:
    from pokeai.agents.base import Agent
    from pokeai.env.pokemon_red_env import PokemonRedEnv

# Game Boy screen dimensions
GB_W, GB_H = 160, 144
# Game area grid (Pokemon Gen 1 wrapper)
GRID_COLS, GRID_ROWS = 20, 18

# --- Colors ---
C_BG = (24, 26, 32)
C_PANEL = (36, 40, 48)
C_PANEL_ALT = (30, 33, 40)
C_PANEL_LINE = (60, 66, 78)
C_TEXT = (220, 224, 230)
C_TEXT_DIM = (140, 146, 158)
C_ACCENT = (90, 170, 255)
C_GOOD = (90, 200, 120)
C_WARN = (240, 180, 60)
C_BAD = (230, 90, 90)
C_GOLD = (250, 205, 90)
# Mode indicators
C_AI = (90, 200, 120)        # AI control = green
C_MANUAL = (180, 130, 255)   # manual control = purple
# Minimap tile colors
C_TILE_WALKABLE = (70, 120, 80)
C_TILE_BLOCKED = (50, 52, 60)
C_TILE_UNKNOWN = (40, 42, 48)
C_TILE_GRASS = (70, 190, 90)   # tall grass (wild encounters)
C_SPRITE = (230, 90, 90)
C_PLAYER = (90, 170, 255)
# HUD
C_HUD_BG = (0, 0, 0, 170)  # semi-transparent
C_HP_BAR = (90, 200, 120)
C_HP_BAR_LOW = (230, 90, 90)
C_HP_BAR_BG = (60, 60, 60)

# Speed presets: label -> PyBoy emulation speed (0 = unlimited)
SPEED_PRESETS: list[tuple[str, int]] = [("1x", 1), ("2x", 2), ("4x", 4), ("MAX", 0)]

# Friendly, viewer-facing names for the agent strategies.
STRATEGY_NAMES: dict[str, str] = {
    "random": "Random Walk",
    "heuristic": "Heuristic",
    "strategist": "Strategist",
    "planner": "Planner",
    "tactician": "Battle Tactician",
    "learner": "Learner",
    "catcher": "Catcher",
    "adventurer": "Adventurer",
}
# Compact labels for the options-menu buttons.
STRATEGY_SHORT: dict[str, str] = {
    "random": "Random",
    "heuristic": "Heur",
    "strategist": "Strat",
    "planner": "Plan",
    "tactician": "Battle",
    "learner": "Learn",
    "catcher": "Catch",
    "adventurer": "Adventure",
}
STRATEGY_ORDER: list[str] = [
    "adventurer", "planner", "tactician", "catcher", "learner", "strategist", "heuristic", "random"
]

VIEW_MODES: list[str] = ["full", "clean", "game"]

# Reduced button-hold while a human plays, so input feels responsive instead of
# locking the game for a full AI frame-skip per press.
MANUAL_FRAME_SKIP = 8
# Target redraw rate for the smooth per-frame renderer.
RENDER_FPS = 60


def strategy_label(name: str) -> str:
    return STRATEGY_NAMES.get(name, name.title())


class Dashboard:
    """Pygame window implementing the StepMonitor protocol for the training loop."""

    COL_W = 340  # width of each side column (full view)
    BOTTOM_H = 128  # control panel height (full view)
    THIN_H = 72  # control bar height (clean / game views)

    def __init__(self, ui_config: UIConfig, control: RunControl | None = None):
        # Import here so headless installs never need a working pygame/display.
        import pygame

        self.pygame = pygame
        self.config = ui_config
        self.control = control or RunControl(start_paused=ui_config.start_paused)
        self.env: PokemonRedEnv | None = None
        self.agent: Agent | None = None

        self.scale = ui_config.scale
        self.game_w = GB_W * self.scale
        self.game_h = GB_H * self.scale
        self.win_w = self.game_w + 2 * self.COL_W
        self.win_h = self.game_h + self.BOTTOM_H

        pygame.init()
        pygame.display.set_caption("pokeai — diagnostic dashboard")
        self.screen = pygame.display.set_mode((self.win_w, self.win_h))
        self.font = pygame.font.SysFont("consolas", 14)
        self.font_small = pygame.font.SysFont("consolas", 12)
        self.font_big = pygame.font.SysFont("consolas", 18, bold=True)
        self.font_huge = pygame.font.SysFont("consolas", 26, bold=True)
        self.clock = pygame.time.Clock()

        # Run context
        self.episode = 0
        self.total_episodes = 0
        self.last_action: int | None = None
        self.last_info: dict[str, Any] = {}
        self.episode_history: list[RunMetrics] = []
        self._buttons: dict[str, Any] = {}  # name -> pygame.Rect
        self._speed_buttons: dict[int, Any] = {}  # speed value -> pygame.Rect
        self._option_buttons: dict[str, Any] = {}  # option key -> pygame.Rect
        self.current_speed: int = 0

        # Cognition views
        self.thoughts = ThoughtTracker()
        self.memory = VisitMemory()
        self.goals = GoalTracker()
        self._last_observed_step = -1
        self._battle_brain: Any = None  # set in attach()
        # Session-event trackers (celebration toasts + ticker)
        self._prev_level = 0
        self._prev_badges = 0
        self._prev_battles_won = 0
        self._session_battles_won = 0

        # --- Streaming / control state ---
        self.view_mode = ui_config.view_mode if ui_config.view_mode in VIEW_MODES else "full"
        self.show_options = False
        self.sound_on = ui_config.sound
        self.auto_catch = ui_config.auto_catch  # opportunistic catching in battle
        self.manual_mode = False
        self._saved_frame_skip: int | None = None
        # Agent control (live strategy switching + manual takeover)
        self.full_config: Any = None  # full Config, captured in attach()
        self._learner: Agent | None = None  # the loop's agent (the learner)
        self._active_agent: Agent | None = None  # the agent that last acted
        self._active_thought: str = ""
        self.active_strategy: str = "random"
        self._strategies: dict[str, Agent] = {}

        # Audio (degrades to a no-op if no device is available)
        self.audio = AudioPlayer(pygame, sample_rate=48000, volume=ui_config.volume)
        self._game_rect = pygame.Rect(0, 0, self.game_w, self.game_h)
        self._bottom_h = self.BOTTOM_H
        self._session_start = time.monotonic()
        self._last_render = 0.0
        # True when the whole window (not just the game view) needs repainting —
        # set by UI interactions, cleared by a full _draw().
        self._dirty = True
        # Transient on-screen notification (text, monotonic time) for setting
        # changes — gives immediate feedback that an action took effect.
        self._toast: tuple[str, float] | None = None

    # --- StepMonitor protocol ---

    def attach(self, env: "PokemonRedEnv", agent: "Agent | None" = None) -> None:
        self.env = env
        self.agent = agent
        self._learner = agent
        self._active_agent = agent
        self.full_config = env.config
        self.current_speed = env.config.emulator.emulation_speed
        if agent is not None:
            self.active_strategy = agent.name
            self._strategies[agent.name] = agent
        # Independent battle analyst for the BATTLE panel: shows the type-chart
        # matchup + recommended move for ANY strategy (and manual play).
        from pokeai.agents.battle_brain import BattleBrain

        self._battle_brain = BattleBrain(env.state_reader)
        self._session_start = time.monotonic()
        # Smooth rendering + audio both need a per-frame callback during steps.
        self._apply_frame_hook()

    def on_episode_start(self, episode: int, total_episodes: int) -> None:
        self.episode = episode
        self.total_episodes = total_episodes
        self.last_action = None
        self.thoughts.reset_episode()
        self.memory.reset_episode()
        self._last_observed_step = -1
        self._prev_level = 0
        self._prev_badges = 0
        self._prev_battles_won = 0

    def pump(self, last_action: int | None, info: dict[str, Any]) -> None:
        """Process UI events and redraw. Blocks while paused (still pumping)."""
        self.last_action = last_action
        self.last_info = info
        self._observe_step(info)

        self._handle_events()
        self._draw()

        # Pause loop: keep the window alive at ~30fps until resumed/stepped/stopped.
        # A restart request also exits the loop (the training loop consumes it).
        while (
            self.control.paused
            and not self.control.stop_requested
            and not self.control.restart_requested
        ):
            if self.control.consume_step_request():
                return  # execute exactly one step, then we'll be called again
            self._handle_events()
            self._draw()
            self.clock.tick(30)

    def on_episode_end(self, metrics: RunMetrics) -> None:
        self.episode_history.append(metrics)

    @property
    def stop_requested(self) -> bool:
        return self.control.stop_requested

    def consume_restart_request(self) -> bool:
        return self.control.consume_restart_request()

    def close(self) -> None:
        if self.env is not None:
            try:
                self.env.emulator.set_frame_hook(None)
            except Exception:
                pass
        self.audio.close()
        self.pygame.quit()

    # --- Action selection (manual takeover + live strategy switch) ---

    def select_action(self, obs: np.ndarray, agent: "Agent") -> int:
        """Loop hook: decide the action to take this step.

        Returns a manual action when the human has taken over, otherwise the
        action from the currently selected strategy (which may differ from the
        loop's learner if the user switched strategy live).
        """
        self._learner = agent
        if self.manual_mode:
            action = self._read_manual_action()
            self._active_agent = None
            btn = ACTION_TO_BUTTON.get(action, "NOOP")
            self._active_thought = (
                "Manual control — you have the controls"
                if btn == "NOOP"
                else f"Manual control — pressing {btn}"
            )
            return action
        active = self._agent_for(self.active_strategy)
        self._active_agent = active
        # Let the active strategy catch on its own during wild battles (any brain
        # agent honours this; agents without the attribute simply ignore it).
        if hasattr(active, "auto_catch"):
            active.auto_catch = self.auto_catch
        action = active.act(obs)
        self._active_thought = active.thought
        return action

    def _agent_for(self, name: str) -> "Agent":
        """Return the agent for a strategy, reusing the learner and caching others."""
        if self._learner is not None and name == self._learner.name:
            return self._learner
        if name in self._strategies:
            return self._strategies[name]
        # Build a fresh agent of this type from a copy of the run config.
        from pokeai.agents import build_agent

        try:
            cfg = self.full_config.model_copy(deep=True)
            cfg.agent.type = name
            agent = build_agent(cfg)
        except Exception as exc:  # e.g. torch import failure for dqn
            self._active_thought = f"Could not load {strategy_label(name)}: {exc}"
            self._set_toast(f"{strategy_label(name)} unavailable — kept current")
            # Fall back to the learner so the run continues.
            self.active_strategy = self._learner.name if self._learner else name
            return self._learner if self._learner is not None else _NullAgent()
        if self.env is not None:
            agent.attach_env(self.env)
        self._strategies[name] = agent
        return agent

    def _read_manual_action(self) -> int:
        """Map currently-held keys to a discrete action (A/B prioritized)."""
        pygame = self.pygame
        keys = pygame.key.get_pressed()
        if keys[pygame.K_x]:
            return int(Action.A)
        if keys[pygame.K_z]:
            return int(Action.B)
        if keys[pygame.K_UP]:
            return int(Action.UP)
        if keys[pygame.K_DOWN]:
            return int(Action.DOWN)
        if keys[pygame.K_LEFT]:
            return int(Action.LEFT)
        if keys[pygame.K_RIGHT]:
            return int(Action.RIGHT)
        return int(Action.NOOP)

    def _set_manual(self, on: bool) -> None:
        if on == self.manual_mode:
            return
        self.manual_mode = on
        controller = self.env.action_controller if self.env is not None else None
        if on:
            # Resume running so manual input flows, slow to a playable speed, and
            # shorten the button-hold for responsiveness.
            self.control.start()
            if self.current_speed == 0:
                self._set_speed(1)
            if controller is not None:
                self._saved_frame_skip = controller.frame_skip
                controller.frame_skip = MANUAL_FRAME_SKIP
        else:
            if controller is not None and self._saved_frame_skip is not None:
                controller.frame_skip = self._saved_frame_skip
                self._saved_frame_skip = None
            self._active_thought = ""
        self._set_toast("Manual control — you're playing" if on else "AI control resumed")
        self._apply_frame_hook()

    def _set_strategy(self, name: str) -> None:
        self.active_strategy = name
        if self.manual_mode:
            self._set_manual(False)
        self._set_toast(f"AI Strategy → {strategy_label(name)}")

    def _set_toast(self, text: str) -> None:
        self._toast = (text, time.monotonic())
        self._dirty = True

    # --- Per-frame hook (smooth rendering + audio capture) ---

    def _apply_frame_hook(self) -> None:
        """Register/clear the emulator frame hook based on what's active."""
        if self.env is None:
            return
        need_audio = self.sound_on and self.current_speed == 1
        need = self.config.smooth_rendering or need_audio or self.manual_mode
        try:
            self.env.emulator.set_frame_hook(self._frame_tick if need else None)
        except Exception:
            pass

    def _frame_tick(self) -> None:
        """Called after every emulated frame during a step.

        Collects audio every frame (so there are no gaps) and repaints *only the
        game view* at up to RENDER_FPS so motion is smooth. The heavy diagnostic
        panels are NOT redrawn here — a full repaint takes ~20ms, which is more
        than the 16.6ms/frame budget and would drop the emulator below 1x (the
        cause of choppy audio). Panels refresh once per step in pump().
        """
        if self.env is None:
            return
        if self.sound_on and self.current_speed == 1:
            self.audio.feed(self.env.emulator.audio_samples())
            self.audio.pump()
        if not self.config.smooth_rendering and not self.manual_mode:
            return
        now = time.perf_counter()
        if now - self._last_render < 1.0 / RENDER_FPS:
            return
        self._last_render = now
        self._handle_events()
        # A UI interaction (menu, view switch, mode/strategy change) needs the
        # full window repainted; otherwise just repaint the game region.
        if self._dirty or self.show_options:
            self._draw()
        else:
            self._render_game_region()

    # --- Cognition feeds (only on real step advances, not pause redraws) ---

    def _observe_step(self, info: dict[str, Any]) -> None:
        if self.env is None:
            return
        step = info.get("step_count", 0)
        if step == self._last_observed_step:
            return
        self._last_observed_step = step

        try:
            state = self.env.state_reader.read()
            party = self.env.state_reader.read_party_details()
        except Exception:
            return

        # Memory: record position
        self.memory.record(state.current_map, state.x_pos, state.y_pos)
        # Goals: milestone progress
        self.goals.observe(state)

        # Celebration toasts: battle wins, level ups, badges.
        battles = info.get("battles_won", 0)
        if battles > self._prev_battles_won:
            self._session_battles_won += battles - self._prev_battles_won
            self._set_toast("KO! Battle won!")
        self._prev_battles_won = battles
        if self._prev_level and state.party_total_level > self._prev_level:
            self._set_toast(f"LEVEL UP! Party level {state.party_total_level}")
        self._prev_level = state.party_total_level
        if state.badge_count > self._prev_badges and step > 1:
            self._set_toast(f"BADGE GET! ({state.badge_count}/8)")
        self._prev_badges = state.badge_count

        # Thoughts: active-agent rationale (or manual note) + event narration
        if self._active_thought:
            self.thoughts.add_agent_thought(step, self._active_thought)
        self.thoughts.observe(step, state, [m.species_id for m in party])

    # --- Event handling ---

    def _handle_events(self) -> None:
        pygame = self.pygame
        for event in pygame.event.get():
            if event.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
                # Any interaction may change panels/menus -> force a full repaint.
                self._dirty = True
            if event.type == pygame.QUIT:
                self.control.stop()
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    if self.show_options:
                        self.show_options = False  # Esc closes the menu first
                    else:
                        self.control.stop()
                elif event.key == pygame.K_o:
                    self.show_options = not self.show_options
                elif event.key == pygame.K_TAB:
                    self._cycle_view()
                elif event.key == pygame.K_m:
                    self._set_manual(not self.manual_mode)
                elif event.key == pygame.K_SPACE:
                    self.control.toggle_pause()
                elif event.key == pygame.K_n:
                    self.control.request_step()
                elif event.key == pygame.K_r:
                    self.control.request_restart()
                elif event.key == pygame.K_1:
                    self._set_speed(1)
                elif event.key == pygame.K_2:
                    self._set_speed(2)
                elif event.key == pygame.K_3:
                    self._set_speed(4)
                elif event.key == pygame.K_4:
                    self._set_speed(0)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self._handle_click(event.pos)

    def _handle_click(self, pos: tuple[int, int]) -> None:
        # Options modal swallows clicks while open.
        if self.show_options:
            for key, rect in self._option_buttons.items():
                if rect.collidepoint(pos):
                    self._apply_option(key)
                    return
            return
        for name, rect in self._buttons.items():
            if rect.collidepoint(pos):
                self._dispatch_button(name)
                return
        for speed, rect in self._speed_buttons.items():
            if rect.collidepoint(pos):
                self._set_speed(speed)
                return

    def _dispatch_button(self, name: str) -> None:
        if name == "start":
            self.control.start()
        elif name == "pause":
            self.control.pause()
        elif name == "toggle":
            self.control.toggle_pause()
        elif name == "step":
            self.control.request_step()
        elif name == "stop":
            self.control.stop()
        elif name == "restart":
            self.control.request_restart()
        elif name == "manual":
            self._set_manual(not self.manual_mode)
        elif name == "options":
            self.show_options = not self.show_options

    def _cycle_view(self) -> None:
        i = VIEW_MODES.index(self.view_mode) if self.view_mode in VIEW_MODES else 0
        self.view_mode = VIEW_MODES[(i + 1) % len(VIEW_MODES)]
        self._set_toast(f"View: {self.view_mode}")

    def _set_speed(self, speed: int) -> None:
        self.current_speed = speed
        if self.env is not None:
            try:
                self.env.emulator.set_speed(speed)
            except Exception:
                pass
        if speed != 1:
            self.audio.reset()  # audio is real-time only; mute fast-forward
        self._apply_frame_hook()

    def _apply_option(self, key: str) -> None:
        if key == "close":
            self.show_options = False
        elif key == "mode:ai":
            self._set_manual(False)
        elif key == "mode:manual":
            self._set_manual(True)
        elif key.startswith("strat:"):
            self._set_strategy(key.split(":", 1)[1])
        elif key == "sound:on":
            self.sound_on = True
            self._set_toast("Sound ON" if self.audio.ok else "Sound ON (no audio device)")
            self._apply_frame_hook()
        elif key == "sound:off":
            self.sound_on = False
            self.audio.reset()
            self._set_toast("Sound OFF")
            self._apply_frame_hook()
        elif key == "vol:-":
            self.audio.set_volume(self.audio.volume - 10)
        elif key == "vol:+":
            self.audio.set_volume(self.audio.volume + 10)
        elif key.startswith("view:"):
            self.view_mode = key.split(":", 1)[1]
        elif key == "smooth:on":
            self.config.smooth_rendering = True
            self._apply_frame_hook()
        elif key == "smooth:off":
            self.config.smooth_rendering = False
            self._apply_frame_hook()
        elif key == "catch:on":
            self.auto_catch = True
            self._set_toast("Auto-catch ON — will catch new species")
        elif key == "catch:off":
            self.auto_catch = False
            self._set_toast("Auto-catch OFF")
        elif key.startswith("speed:"):
            self._set_speed(int(key.split(":", 1)[1]))

    # --- Drawing ---

    def _compute_layout(self) -> None:
        pygame = self.pygame
        if self.view_mode == "full":
            self._bottom_h = self.BOTTOM_H
            top_h = self.win_h - self._bottom_h
            self._game_rect = pygame.Rect(0, 0, self.game_w, top_h)
        else:
            self._bottom_h = self.THIN_H
            top_h = self.win_h - self._bottom_h
            gh = top_h
            gw = min(int(gh * GB_W / GB_H), self.win_w)
            gx = 0 if self.view_mode == "clean" else (self.win_w - gw) // 2
            self._game_rect = pygame.Rect(gx, 0, gw, gh)

    def _draw(self) -> None:
        """Full-window repaint (game + all panels). ~20ms — call once per step."""
        self.screen.fill(C_BG)
        self._compute_layout()
        self._draw_game_view()
        self._draw_hud()
        if self.view_mode == "full":
            self._draw_vision_column()
            self._draw_cognition_column()
        elif self.view_mode == "clean":
            self._draw_clean_sidebar()
        self._draw_overlays()
        self._draw_bottom_panel()
        if self.show_options:
            self._draw_options()
        self._dirty = False
        self.pygame.display.flip()

    def _render_game_region(self) -> None:
        """Lightweight per-frame repaint of just the game view (for smooth motion).

        Leaves the diagnostic panels from the last full _draw() untouched and
        only presents the game rectangle, so it costs a few ms instead of ~20.
        """
        self._compute_layout()
        self._draw_game_view()
        self._draw_hud()
        self._draw_overlays()
        self._draw_thinking()
        self.pygame.display.update(self._game_rect)

    def _draw_thinking(self) -> None:
        """Over-game 'the strategist is thinking' animation, shown while the LLM
        advisor is mid-call. Animates per frame and shows an estimated time so
        viewers know roughly how long the pause will last."""
        agent = self._active_agent
        if not getattr(agent, "thinking", False):
            return
        pygame = self.pygame
        rect = self._game_rect
        dim = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
        dim.fill((10, 12, 20, 150))
        self.screen.blit(dim, (rect.x, rect.y))

        t = time.monotonic()
        spinner = "|/-\\"[int(t * 8) % 4]
        dots = "." * (1 + int(t * 3) % 3)
        elapsed = float(getattr(agent, "think_elapsed", 0.0))
        estimate = float(getattr(agent, "think_estimate", 0.0)) or 1.0
        title = f"{spinner}  AI is thinking{dots}"
        sub = f"~{estimate:.0f}s expected   (elapsed {elapsed:.0f}s)"

        bw, bh = min(rect.w - 32, 320), 104
        bx, by = rect.x + (rect.w - bw) // 2, rect.y + (rect.h - bh) // 2
        pygame.draw.rect(self.screen, C_PANEL, (bx, by, bw, bh), border_radius=10)
        pygame.draw.rect(self.screen, C_ACCENT, (bx, by, bw, bh), width=2, border_radius=10)
        tw = self.font_huge.size(title)[0]
        self._text(title, (bx + (bw - tw) // 2, by + 14), self.font_huge, C_ACCENT)
        sw = self.font.size(sub)[0]
        self._text(sub, (bx + (bw - sw) // 2, by + 48), self.font, C_TEXT_DIM)
        # Progress toward the expected time (caps at full; may overrun on a slow call).
        frac = max(0.0, min(elapsed / estimate, 1.0))
        bar_w = bw - 32
        pygame.draw.rect(self.screen, C_HP_BAR_BG, (bx + 16, by + 76, bar_w, 8), border_radius=4)
        pygame.draw.rect(self.screen, C_AI, (bx + 16, by + 76, int(bar_w * frac), 8), border_radius=4)
        reason = getattr(agent, "think_reason", "")
        if reason:
            rw = self.font_small.size(reason)[0]
            if rw <= bw - 16:
                self._text(reason, (bx + (bw - rw) // 2, by + bh + 6), self.font_small, C_TEXT_DIM)

    def _text(self, text, pos, font=None, color=C_TEXT):
        font = font or self.font
        self.screen.blit(font.render(text, True, color), pos)

    def _wrap(self, text: str, font, max_w: int, max_lines: int = 2) -> list[str]:
        """Greedy word-wrap into at most max_lines lines (last line ellipsized)."""
        words = text.split()
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if font.size(candidate)[0] <= max_w:
                current = candidate
            else:
                lines.append(current)
                current = word
                if len(lines) == max_lines:
                    break
        if current and len(lines) < max_lines:
            lines.append(current)
        if len(lines) == max_lines and words and font.size(" ".join(words))[0] > max_w * max_lines:
            lines[-1] = lines[-1][:-1] + "…"
        return lines or [""]

    def _button(self, name: str, rect, label: str, active: bool, store: dict) -> None:
        """Draw a rounded button, record its rect, and color it by active state."""
        pygame = self.pygame
        store[name] = rect
        fill = C_ACCENT if active else C_PANEL_LINE
        pygame.draw.rect(self.screen, fill, rect, border_radius=6)
        lw, lh = self.font.size(label)
        self._text(
            label,
            (rect.x + (rect.w - lw) // 2, rect.y + (rect.h - lh) // 2),
            self.font,
            C_BG if active else C_TEXT,
        )

    # -- Game view + HUD (left) --

    def _draw_game_view(self) -> None:
        pygame = self.pygame
        rect = self._game_rect
        if self.env is None:
            return
        try:
            frame = self.env.emulator.screen_rgb()  # (144, 160, 3)
        except Exception:
            frame = np.zeros((GB_H, GB_W, 3), dtype=np.uint8)
        # pygame surfarray expects (w, h, 3)
        frame = np.ascontiguousarray(np.transpose(frame, (1, 0, 2)))
        surf = pygame.surfarray.make_surface(frame)
        surf = pygame.transform.scale(surf, (rect.w, rect.h))
        self.screen.blit(surf, (rect.x, rect.y))

    def _draw_hud(self) -> None:
        """Semi-transparent overlay strips on the game view: top = location, bottom = party."""
        pygame = self.pygame
        rect = self._game_rect
        if self.env is None:
            return
        try:
            state = self.env.state_reader.read()
            party = self.env.state_reader.read_party_details()
        except Exception:
            return

        # Top strip: map / position / badges / money
        top = pygame.Surface((rect.w, 24), pygame.SRCALPHA)
        top.fill(C_HUD_BG)
        self.screen.blit(top, (rect.x, rect.y))
        loc = f"{map_name(state.current_map)}  ({state.x_pos},{state.y_pos})"
        right = f"badges {state.badge_count}  ${state.money}"
        self._text(loc, (rect.x + 8, rect.y + 4), self.font, C_TEXT)
        rw = self.font.size(right)[0]
        self._text(right, (rect.right - rw - 8, rect.y + 4), self.font, C_TEXT)

        # Battle indicator
        if state.battle_type != 0:
            self._text("IN BATTLE", (rect.x + 8, rect.y + 30), self.font_big, C_BAD)

        # Bottom strip: lead Pokemon (species, level, types, status, DVs, HP bar)
        if party:
            mon = party[0]
            strip_h = 42
            bottom = pygame.Surface((rect.w, strip_h), pygame.SRCALPHA)
            bottom.fill(C_HUD_BG)
            self.screen.blit(bottom, (rect.x, rect.bottom - strip_h))
            y0 = rect.bottom - strip_h + 4

            types = type_name(mon.type1)
            if mon.type2 != mon.type1:
                types += f"/{type_name(mon.type2)}"
            line1 = (
                f"{species_name(mon.species_id)}  Lv{mon.level}  {types}  "
                f"{status_text(mon.status)}"
            )
            self._text(line1, (rect.x + 8, y0), self.font, C_TEXT)

            # DV "genome" readout (hex digits: HP/Atk/Def/Spd/Spc)
            dvs = (
                f"DV {mon.dv_hp:X}{mon.dv_attack:X}{mon.dv_defense:X}"
                f"{mon.dv_speed:X}{mon.dv_special:X}"
            )
            dw = self.font_small.size(dvs)[0]
            self._text(dvs, (rect.right - dw - 8, y0), self.font_small, C_TEXT_DIM)

            # HP bar
            bar_y = y0 + 20
            bar_w = rect.w - 120
            frac = mon.hp / mon.max_hp if mon.max_hp > 0 else 0.0
            pygame.draw.rect(self.screen, C_HP_BAR_BG, (rect.x + 8, bar_y, bar_w, 10))
            color = C_HP_BAR if frac > 0.3 else C_HP_BAR_LOW
            pygame.draw.rect(self.screen, color, (rect.x + 8, bar_y, int(bar_w * frac), 10))
            self._text(
                f"{mon.hp}/{mon.max_hp}", (rect.x + bar_w + 16, bar_y - 2), self.font, C_TEXT
            )
        else:
            # No Pokemon yet — flag it (this is the Phase 1.5-A symptom)
            self._text("PARTY EMPTY", (rect.x + 8, rect.bottom - 24), self.font, C_WARN)

    # -- On-game overlays: mode badge, milestone banner (clean / game views) --

    def _draw_overlays(self) -> None:
        if self.view_mode != "full":
            self._draw_mode_badge()
        self._draw_goal_banner()
        self._draw_toast()

    def _draw_toast(self) -> None:
        """Transient setting-change notification near the top of the game view."""
        if self._toast is None:
            return
        text, t = self._toast
        if time.monotonic() - t > 2.5:
            self._toast = None
            return
        pygame = self.pygame
        rect = self._game_rect
        tw = self.font_big.size(text)[0]
        bw = tw + 28
        bx = rect.x + (rect.w - bw) // 2
        by = rect.y + 8
        chip = pygame.Surface((bw, 30), pygame.SRCALPHA)
        chip.fill((0, 0, 0, 205))
        self.screen.blit(chip, (bx, by))
        pygame.draw.rect(self.screen, C_ACCENT, (bx, by, bw, 30), 1, border_radius=6)
        self._text(text, (bx + 14, by + 6), self.font_big, C_TEXT)

    def _draw_mode_badge(self) -> None:
        """Compact mode + strategy chip on the game view (clean / game modes)."""
        pygame = self.pygame
        rect = self._game_rect
        manual = self.manual_mode
        color = C_MANUAL if manual else C_AI
        label = "MANUAL" if manual else "AI"
        sub = "you are playing" if manual else f"Strategy: {strategy_label(self.active_strategy)}"
        text = f"  ● {label}   {sub}  "
        w = self.font.size(text)[0]
        chip = pygame.Surface((w, 26), pygame.SRCALPHA)
        chip.fill((0, 0, 0, 180))
        self.screen.blit(chip, (rect.x + 6, rect.y + 28))
        self._text(f"  ● {label}", (rect.x + 6, rect.y + 32), self.font, color)
        off = self.font.size(f"  ● {label}   ")[0]
        self._text(sub, (rect.x + 6 + off, rect.y + 32), self.font, C_TEXT)

        # Current objective, top-right.
        goal = self.goals.current_goal()
        if goal:
            gtext = f"Goal: {goal}  "
            gw = self.font.size(gtext)[0]
            gchip = pygame.Surface((gw + 8, 26), pygame.SRCALPHA)
            gchip.fill((0, 0, 0, 180))
            self.screen.blit(gchip, (rect.right - gw - 12, rect.y + 28))
            self._text(gtext, (rect.right - gw - 6, rect.y + 32), self.font, C_GOLD)

    def _draw_goal_banner(self) -> None:
        """Brief celebratory banner when a milestone is unlocked."""
        label = self.goals.recent_unlock()
        if not label:
            return
        pygame = self.pygame
        rect = self._game_rect
        text = f"▸ MILESTONE: {label}"
        tw = self.font_big.size(text)[0]
        bw = tw + 32
        bx = rect.x + (rect.w - bw) // 2
        by = rect.y + rect.h // 3
        banner = pygame.Surface((bw, 36), pygame.SRCALPHA)
        banner.fill((0, 0, 0, 200))
        self.screen.blit(banner, (bx, by))
        pygame.draw.rect(self.screen, C_GOLD, (bx, by, bw, 36), 2, border_radius=8)
        self._text(text, (bx + 16, by + 8), self.font_big, C_GOLD)

    # -- Column 2: AI vision (minimap) + diagnostics --

    def _draw_vision_column(self) -> None:
        pygame = self.pygame
        x0 = self.game_w
        pygame.draw.rect(self.screen, C_PANEL, (x0, 0, self.COL_W, self.game_h))
        pygame.draw.line(self.screen, C_PANEL_LINE, (x0, 0), (x0, self.game_h))

        y = 8
        self._text("AI VISION", (x0 + 12, y), self.font_big, C_ACCENT)
        y += 26
        y = self._draw_minimap(x0 + 12, y)
        y += 10
        self._text("DIAGNOSTICS", (x0 + 12, y), self.font_big, C_ACCENT)
        y += 24
        self._draw_diagnostics(x0 + 12, y)

    def _draw_minimap(self, x0: int, y0: int) -> int:
        """The agent's-eye map of what each visible tile *is*: walkable, wall,
        grass (encounters), a person, and the player. This is the same semantic
        grid the agent navigates on — so viewers see exactly what it sees.

        In battle there is no overworld map, so we show the BATTLE panel instead.
        For a GameSense brain we show the *learned* map it has been building —
        the whole area it remembers, not just the screen in front of it.
        """
        from pokeai.emulator.screen_reader import TileClass

        pygame = self.pygame
        tile = 12
        w, h = GRID_COLS * tile, GRID_ROWS * tile

        in_battle = False
        if self.env is not None:
            try:
                in_battle = self.env.state_reader.read().battle_type != 0
            except Exception:
                in_battle = False
        if in_battle:
            return self._draw_minimap_battle(x0, y0, tile, w, h)

        brain = self._active_brain()
        if brain is not None and hasattr(brain, "sense"):
            mapped = self._draw_learned_map(brain, x0, y0, w, h)
            if mapped:
                return y0 + h + 24

        sem = None
        if self.env is not None:
            try:
                sem = self.env.screen_reader.semantic_tiles()
            except Exception:
                sem = None

        class_color = {
            int(TileClass.UNKNOWN): C_TILE_UNKNOWN,
            int(TileClass.WALKABLE): C_TILE_WALKABLE,
            int(TileClass.WALL): C_TILE_BLOCKED,
            int(TileClass.GRASS): C_TILE_GRASS,
            int(TileClass.NPC): C_SPRITE,
            int(TileClass.PLAYER): C_PLAYER,
        }
        for row in range(GRID_ROWS):
            for col in range(GRID_COLS):
                cls = int(sem[row, col]) if sem is not None else int(TileClass.UNKNOWN)
                color = class_color.get(cls, C_TILE_UNKNOWN)
                pygame.draw.rect(
                    self.screen, color, (x0 + col * tile, y0 + row * tile, tile - 1, tile - 1)
                )

        pygame.draw.rect(self.screen, C_PANEL_LINE, (x0 - 1, y0 - 1, w + 2, h + 2), 1)

        # Legend
        ly = y0 + h + 6
        legend = [
            (C_TILE_WALKABLE, "path"),
            (C_TILE_GRASS, "grass"),
            (C_TILE_BLOCKED, "wall"),
            (C_SPRITE, "person"),
            (C_PLAYER, "you"),
        ]
        lx = x0
        for color, label in legend:
            pygame.draw.rect(self.screen, color, (lx, ly + 2, 10, 10))
            self._text(label, (lx + 14, ly), self.font_small, C_TEXT_DIM)
            lx += 14 + self.font_small.size(label)[0] + 10
        return ly + 18

    def _draw_learned_map(self, brain, x0: int, y0: int, w: int, h: int) -> bool:
        """Render the brain's remembered map of the current area, centred on the
        player, so viewers watch the map get drawn as it explores. Returns False
        if there's nothing mapped yet (caller falls back to the screen view)."""
        from pokeai.agents.brain.world_model import Cell

        pygame = self.pygame
        try:
            state = self.env.state_reader.read()
            m, px, py = state.current_map, state.x_pos, state.y_pos
            grid = brain.sense.world.maps.get(m, {})
        except Exception:
            return False
        if not grid:
            return False

        cell_color = {
            Cell.FLOOR: C_TILE_WALKABLE,
            Cell.WALL: C_TILE_BLOCKED,
            Cell.GRASS: C_TILE_GRASS,
            Cell.NPC: C_SPRITE,
            Cell.WARP: C_GOLD,           # doors / stairs / route seams
        }
        # A window of tiles centred on the player, sized to fill the panel.
        cell = 6
        cols, rows = w // cell, h // cell
        cx, cy = cols // 2, rows // 2
        pygame.draw.rect(self.screen, C_TILE_UNKNOWN, (x0, y0, cols * cell, rows * cell))
        for r in range(rows):
            for c in range(cols):
                wx, wy = px + (c - cx), py + (r - cy)
                cls = grid.get((wx, wy), Cell.UNKNOWN)
                if cls == Cell.UNKNOWN:
                    continue
                color = cell_color.get(cls, C_TILE_UNKNOWN)
                pygame.draw.rect(self.screen, color, (x0 + c * cell, y0 + r * cell, cell, cell))
        # The player, always dead centre.
        pygame.draw.rect(self.screen, C_PLAYER, (x0 + cx * cell, y0 + cy * cell, cell, cell))
        pygame.draw.rect(self.screen, C_PANEL_LINE, (x0 - 1, y0 - 1, cols * cell + 2, rows * cell + 2), 1)

        # Legend + how much it has mapped.
        ly = y0 + rows * cell + 6
        legend = [(C_TILE_WALKABLE, "path"), (C_TILE_GRASS, "grass"),
                  (C_TILE_BLOCKED, "wall"), (C_GOLD, "door"), (C_PLAYER, "you")]
        lx = x0
        for color, label in legend:
            pygame.draw.rect(self.screen, color, (lx, ly + 2, 10, 10))
            self._text(label, (lx + 14, ly), self.font_small, C_TEXT_DIM)
            lx += 14 + self.font_small.size(label)[0] + 10
        self._text(f"{len(grid)} tiles remembered here", (x0, ly + 16), self.font_small, C_TEXT_DIM)
        return True

    def _draw_minimap_battle(self, x0: int, y0: int, tile: int, w: int, h: int) -> int:
        """Battle replacement for the overworld minimap: the BATTLE panel.

        Live matchup analysis from the BattleBrain — both fighters with HP
        bars, every move scored against the enemy's typing, and the plan
        (fight/flee). Shown for every strategy and manual play, so viewers
        always see what the smart play would be.
        """
        pygame = self.pygame

        analysis = None
        if self._battle_brain is not None:
            try:
                analysis = self._battle_brain.analyze()
            except Exception:
                analysis = None
        if analysis is None or not analysis.battle.in_battle:
            self._text("battle stats unavailable", (x0, y0 + 6), self.font_small, C_WARN)
            return y0 + 24

        b = analysis.battle
        kind = "TRAINER BATTLE" if b.in_battle == 2 else "WILD BATTLE"
        self._text(kind, (x0, y0), self.font_big, C_BAD)
        y = y0 + 26

        def hp_bar(y: int, frac: float, color) -> None:
            bar_w = w - 56
            pygame.draw.rect(self.screen, C_HP_BAR_BG, (x0, y, bar_w, 8))
            fill = color if frac > 0.3 else C_HP_BAR_LOW
            pygame.draw.rect(self.screen, fill, (x0, y, int(bar_w * max(0.0, frac)), 8))
            self._text(f"{frac * 100:3.0f}%", (x0 + bar_w + 8, y - 3), self.font_small, C_TEXT)

        # Enemy
        etypes = type_name(b.enemy_type1)
        if b.enemy_type2 != b.enemy_type1:
            etypes += "/" + type_name(b.enemy_type2)
        self._text(
            f"{species_name(b.enemy_species)}  Lv{b.enemy_level}  {etypes}",
            (x0, y),
            self.font,
            C_TEXT,
        )
        hp_bar(y + 18, b.enemy_hp_frac, C_BAD)
        y += 32

        # Own mon
        own = analysis.own
        if own is not None:
            otypes = type_name(own.type1)
            if own.type2 != own.type1:
                otypes += "/" + type_name(own.type2)
            self._text(
                f"{species_name(own.species_id)}  Lv{own.level}  {otypes}",
                (x0, y),
                self.font,
                C_TEXT,
            )
            hp_bar(y + 18, b.own_hp_frac, C_HP_BAR)
            y += 36

        # Move scores (power x type x STAB), best one highlighted.
        self._text("MOVES vs " + species_name(b.enemy_species), (x0, y), self.font_small, C_ACCENT)
        y += 16
        max_score = max((s.score for s in analysis.scores), default=0.0) or 1.0
        for s in analysis.scores:
            is_best = analysis.best is not None and s.slot == analysis.best.slot
            mark = "▸" if is_best else " "
            color = C_GOLD if is_best else (C_TEXT if s.score > 0 else C_TEXT_DIM)
            label = f"{mark} {s.name[:12]:<12}"
            self._text(label, (x0, y), self.font_small, color)
            # Effectiveness chip + score bar
            if s.power > 0:
                chip = f"×{s.multiplier:g}" + ("+S" if s.stab > 1 else "")
            else:
                chip = "stat"
            self._text(chip, (x0 + 118, y), self.font_small, color)
            bar_x = x0 + 162
            bar_w = w - 162 - 34
            pygame.draw.rect(self.screen, C_HP_BAR_BG, (bar_x, y + 3, bar_w, 7))
            if s.score > 0:
                pygame.draw.rect(
                    self.screen,
                    C_GOLD if is_best else C_ACCENT,
                    (bar_x, y + 3, max(2, int(bar_w * s.score / max_score)), 7),
                )
            self._text(f"{s.pp_left}", (bar_x + bar_w + 6, y), self.font_small, C_TEXT_DIM)
            y += 16

        # The plan
        y += 4
        if analysis.intent == "flee":
            plan = "Plan: RUN — HP critical, live to fight again"
            color = C_WARN
        else:
            plan = f"Plan: {analysis.matchup_text}"
            color = C_GOOD
        for line in self._wrap(plan, self.font_small, w, max_lines=2):
            self._text(line, (x0, y), self.font_small, color)
            y += 15
        return y + 6

    def _draw_diagnostics(self, x0: int, y0: int) -> None:
        """Compact diagnostic readout from the latest env info + state."""
        info = self.last_info
        max_steps = self.env.config.environment.max_steps if self.env else 0

        lines: list[tuple[str, str]] = [
            ("episode", f"{self.episode + 1}/{self.total_episodes}"),
            ("step", f"{info.get('step_count', 0)}/{max_steps}"),
            ("cum reward", f"{info.get('cumulative_reward', 0.0):.3f}"),
        ]

        breakdown = info.get("reward_breakdown")
        if breakdown:
            parts = [f"{k[:3]}{v:+.1f}" for k, v in breakdown.items() if v != 0]
            lines.append(("last reward", " ".join(parts) if parts else "0"))

        lines.append(
            ("maps/events", f"{info.get('unique_maps_visited', 0)}/{info.get('events_set', 0)}")
        )
        lines.append(("party level", str(info.get("party_total_level", 0))))
        lines.append(("blackout", "YES" if info.get("blackout_occurred") else "no"))
        lines.append(("steps stuck", str(self.thoughts.steps_stuck)))

        if self.env is not None:
            try:
                state = self.env.state_reader.read()
                lines.append(("map", f"0x{state.current_map:02X} ({state.x_pos},{state.y_pos})"))
                lines.append(("battle/party", f"{state.battle_type}/{state.party_count}"))
            except Exception:
                pass

        y = y0
        for label, value in lines:
            self._text(label, (x0, y), self.font_small, C_TEXT_DIM)
            self._text(value, (x0 + 110, y), self.font_small, C_TEXT)
            y += 16

    # -- Column 3: thoughts + reading + memory + skills --

    def _draw_cognition_column(self) -> None:
        """Right column: THOUGHTS, READING, MEMORY, SKILLS stacked top-to-bottom.

        Each section reports the y where its content ended, so the next section's
        divider sits just below it — panels expand and contract with their
        content instead of overlapping a fixed grid.
        """
        pygame = self.pygame
        x0 = self.game_w + self.COL_W
        x = x0 + 12
        pygame.draw.rect(self.screen, C_PANEL_ALT, (x0, 0, self.COL_W, self.game_h))
        pygame.draw.line(self.screen, C_PANEL_LINE, (x0, 0), (x0, self.game_h))

        brain = self._active_brain()
        if brain is not None:
            self._draw_cognition_brain(brain, x0, x)
        else:
            self._draw_cognition_legacy(x0, x)

    def _draw_cognition_brain(self, brain, x0: int, x: int) -> None:
        """Brain layout: GOAL + THOUGHTS + CAPABILITIES always visible up top
        (the engagement stars); READING + MEMORY flow below and clip gracefully."""
        # GOAL / PLAN / capability-in-use — the most viewer-relevant thing.
        y = 8
        self._text("GOAL", (x, y), self.font_big, C_ACCENT)
        y = self._draw_goal_plan(brain, x, y + 24) + 8

        y = self._section_header(x0, y, "THOUGHTS")
        self._draw_thoughts(x, y, 56)
        y += 56

        # CAPABILITIES: the brain's skill profile, active one highlighted.
        y = self._section_header(x0, y, "CAPABILITIES")
        y = self._draw_capability_bars(brain, x, y) + 8

        y = self._section_header(x0, y, "READING")
        y = self._draw_reading(x, y) + 10

        if y < self.game_h - 40:  # only if there's real room left
            y = self._section_header(x0, y, "MEMORY")
            self._draw_memory(x, y, max_lines=self.MEMORY_MAX_LINES)

    def _draw_cognition_legacy(self, x0: int, x: int) -> None:
        """Original layout for the non-brain agents (strategist/heuristic/random)."""
        self._text("THOUGHTS", (x, 8), self.font_big, C_ACCENT)
        thoughts_h = 100
        self._draw_thoughts(x, 34, thoughts_h)
        y = 34 + thoughts_h

        y = self._section_header(x0, y, "READING")
        y = self._draw_reading(x, y) + 10

        y = self._section_header(x0, y, "MEMORY")
        y = self._draw_memory(x, y, max_lines=self.MEMORY_MAX_LINES) + 10

        y = self._section_header(x0, y, "SKILLS")
        self._draw_skill_sparklines(x, y)

    def _active_brain(self):
        """The active agent if it's one of the GameSense brains (exposes goal +
        capabilities), else None."""
        a = self._active_agent
        if a is not None and hasattr(a, "goal_text") and hasattr(a, "capabilities"):
            return a
        return None

    def _draw_goal_plan(self, brain, x0: int, y0: int) -> int:
        """Goal (what it's trying to achieve) + Plan (its next move) + the
        capability it's using right now. Returns the y it ended at."""
        panel_w = self.COL_W - 24
        y = y0
        for line in self._wrap(brain.goal_text, self.font_small, panel_w, max_lines=2):
            self._text(line, (x0, y), self.font_small, C_GOLD)
            y += 15
        plan = getattr(brain, "plan_text", "") or ""
        if plan:
            for line in self._wrap(f"→ {plan}", self.font_small, panel_w, max_lines=2):
                self._text(line, (x0, y), self.font_small, C_TEXT)
                y += 15
        cap = getattr(brain, "active_capability", "") or ""
        if cap:
            self._text(f"using: {cap}", (x0, y), self.font_small, C_ACCENT)
            y += 15
        return y

    def _section_header(self, x0: int, y: int, title: str) -> int:
        """Draw a divider + section title at y; return the content-start y."""
        self.pygame.draw.line(
            self.screen, C_PANEL_LINE, (x0 + 8, y), (x0 + self.COL_W - 8, y)
        )
        self._text(title, (x0 + 12, y + 6), self.font_big, C_ACCENT)
        return y + 30

    def _draw_reading(self, x0: int, y0: int) -> int:
        """Show what the AI actually perceives on screen: the decoded text and
        what kind of screen it is. This is the agent's-eye view — proof it can
        read dialogue, menus and battle messages, not just mash buttons.
        Returns the y where its content ended."""
        from pokeai.emulator.screen_reader import ScreenContext

        panel_w = self.COL_W - 24
        view = None
        if self.env is not None:
            try:
                in_b = self.env.state_reader.read().battle_type != 0
                view = self.env.screen_reader.view(in_battle=in_b)
            except Exception:
                view = None
        if view is None:
            self._text("(no screen access)", (x0, y0), self.font_small, C_TEXT_DIM)
            return y0 + 15

        ctx_label = {
            ScreenContext.FREE_ROAM: ("Walking around", C_GOOD),
            ScreenContext.DIALOGUE: ("Someone's talking", C_GOLD),
            ScreenContext.MENU: ("Menu open", C_ACCENT),
            ScreenContext.BATTLE: ("In battle", C_BAD),
        }[view.context]
        label, color = ctx_label
        if view.context == ScreenContext.MENU and view.cursor_option:
            label = f"Menu — on \"{view.cursor_option}\""
        self._text(f"• {label}", (x0, y0), self.font_small, color)

        # The decoded on-screen words, in quotes, as the AI reads them.
        seen = view.dialogue or view.text
        y = y0 + 18
        if seen:
            for line in self._wrap(f'"{seen}"', self.font_small, panel_w, max_lines=3):
                self._text(line, (x0, y), self.font_small, C_TEXT)
                y += 15
        else:
            self._text("(no text on screen)", (x0, y), self.font_small, C_TEXT_DIM)
            y += 15
        return y

    def _draw_thoughts(self, x0: int, y0: int, max_h: int) -> None:
        """Current agent thought in a bubble, then the recent event log below."""
        pygame = self.pygame
        panel_w = self.COL_W - 24

        # Current thought bubble (active agent's live rationale, or manual note)
        current = self._active_thought or "..."
        bubble_lines = self._wrap(current, self.font_small, panel_w - 16, max_lines=2)
        bubble_h = 8 + len(bubble_lines) * 15 + 5
        accent = C_MANUAL if self.manual_mode else C_ACCENT
        pygame.draw.rect(self.screen, C_PANEL, (x0, y0, panel_w, bubble_h), border_radius=8)
        pygame.draw.rect(self.screen, accent, (x0, y0, panel_w, bubble_h), 1, border_radius=8)
        for i, line in enumerate(bubble_lines):
            self._text(line, (x0 + 8, y0 + 6 + i * 15), self.font_small, C_TEXT)

        # Event log (skip agent-kind thoughts: the bubble already shows the live one)
        y = y0 + bubble_h + 8
        y_limit = y0 + max_h
        kind_colors = {"event": C_TEXT, "alert": C_WARN, "agent": C_TEXT_DIM}
        for thought in self.thoughts.thoughts:
            if thought.kind == "agent":
                continue
            color = kind_colors.get(thought.kind, C_TEXT)
            prefix = f"[{thought.step}] "
            wrapped = self._wrap(prefix + thought.text, self.font_small, panel_w, max_lines=2)
            if y + len(wrapped) * 15 > y_limit:
                break
            for line in wrapped:
                self._text(line, (x0, y), self.font_small, color)
                y += 15

    MEMORY_MAX_LINES = 5  # full-view MEMORY panel rows (incl. the best-ep row)

    def _draw_memory(self, x0: int, y0: int, max_lines: int = 12) -> int:
        """What the AI has accumulated: positions seen, maps known, episode
        history. Returns the y where its content ended."""
        lines: list[tuple[str, str, tuple]] = []

        # Spatial memory (run-level = what persists across episodes)
        lines.append(
            (
                "positions known",
                f"{self.memory.unique_positions_episode} ep / "
                f"{self.memory.unique_positions_run} run",
                C_TEXT,
            )
        )
        maps_known = ", ".join(map_name(m) for m in sorted(self.memory.maps_seen_run))
        lines.append(
            ("maps known", self._wrap(maps_known or "—", self.font_small, 200, 1)[0], C_TEXT)
        )

        # Current position familiarity (stuck/loop indicator)
        if self.env is not None:
            try:
                state = self.env.state_reader.read()
                count = self.memory.visit_count(state.current_map, state.x_pos, state.y_pos)
                novelty = self.memory.novelty(state.current_map, state.x_pos, state.y_pos)
                color = C_TEXT if count < 20 else (C_WARN if count < 60 else C_BAD)
                lines.append(("here before", f"{count}x (novelty {novelty:.2f})", color))
            except Exception:
                pass

        # Last + best episode results (mini leaderboard)
        if self.episode_history:
            metrics = self.episode_history[-1]
            summary = (
                f"r={metrics.cumulative_reward:+.1f} "
                f"{metrics.steps_taken}st "
                f"{metrics.terminated_reason.value}"
            )
            color = C_BAD if metrics.terminated_reason.value == "BLACKOUT" else C_TEXT
            lines.append((f"last ep ({metrics.episode_index + 1})", summary, color))
            best = max(self.episode_history, key=lambda m: m.cumulative_reward)
            lines.append(
                (
                    f"best ep ({best.episode_index + 1})",
                    f"r={best.cumulative_reward:+.1f} {best.battles_won}KO "
                    f"{best.unique_maps_visited}maps",
                    C_GOLD,
                )
            )

        y = y0
        for label, value, color in lines[:max_lines]:
            if label:
                self._text(label, (x0, y), self.font_small, C_TEXT_DIM)
            if value:
                self._text(value, (x0 + 110, y), self.font_small, color)
            y += 16
        return y

    def _draw_skills(self, x0: int, y0: int) -> None:
        """For a GameSense brain: its capability profile as bars, with the
        capability it's using right now highlighted. Otherwise: per-skill
        sparklines of how metrics change across episodes."""
        brain = self._active_brain()
        if brain is not None:
            self._draw_capability_bars(brain, x0, y0)
            return
        self._draw_skill_sparklines(x0, y0)

    def _draw_capability_bars(self, brain, x0: int, y0: int) -> int:
        """Horizontal bars for the brain's innate capabilities; the active one
        is highlighted so viewers see which skill it's leaning on. Returns the y
        it ended at."""
        pygame = self.pygame
        active = getattr(brain, "active_capability", "")
        bar_x = x0 + 92
        bar_w = 120
        bar_h = 9
        y = y0
        for label, level in brain.capabilities.items():
            is_active = label == active
            color = C_GOOD if is_active else C_ACCENT
            self._text(label, (x0, y - 1), self.font_small,
                       C_TEXT if is_active else C_TEXT_DIM)
            pygame.draw.rect(self.screen, C_PANEL, (bar_x, y, bar_w, bar_h), border_radius=3)
            pygame.draw.rect(self.screen, color, (bar_x, y, int(bar_w * level), bar_h),
                             border_radius=3)
            if is_active:
                pygame.draw.rect(self.screen, C_GOOD, (bar_x, y, bar_w, bar_h), 1, border_radius=3)
            y += 16
        # The Learner shares what it has figured out this run.
        lessons = getattr(brain, "lessons", None)
        if lessons:
            y += 2
            self._text("learned:", (x0, y), self.font_small, C_TEXT_DIM)
            y += 15
            for lesson in lessons[-2:]:
                for line in self._wrap(f"• {lesson}", self.font_small, self.COL_W - 24, max_lines=1):
                    self._text(line, (x0, y), self.font_small, C_GOLD)
                    y += 14
        return y

    def _draw_skill_sparklines(self, x0: int, y0: int) -> None:
        """Per-skill sparklines: how the agent's skills change across episodes.

        Each row: skill name | sparkline of per-episode values | latest + trend.
        """
        pygame = self.pygame
        history = self.episode_history

        # (label, series extractor, desired direction)
        skill_rows = [
            ("explore", lambda m: float(m.unique_tiles_visited), "up"),
            ("battle", lambda m: float(m.battles_won), "up"),
            ("survive", lambda m: 0.0 if m.blackout_occurred else 1.0, "up"),
            ("progress", lambda m: float(m.cumulative_reward), "up"),
        ]

        if len(history) < 2:
            self._text(
                "Play 2+ episodes to chart skills...",
                (x0, y0),
                self.font_small,
                C_TEXT_DIM,
            )
            # Show the learner's internals meanwhile (if DQN/PPO)
            self._draw_agent_internals(x0, y0 + 20)
            return

        spark_x = x0 + 86
        spark_w = 130
        spark_h = 13
        row_h = 20

        y = y0
        for label, extract, desired in skill_rows:
            series = [extract(m) for m in history]
            lo, hi = min(series), max(series)
            span = (hi - lo) or 1.0

            self._text(label, (x0, y + 2), self.font_small, C_TEXT_DIM)

            # Sparkline
            n = len(series)
            points = []
            for i, v in enumerate(series):
                px = spark_x + int(i * spark_w / max(n - 1, 1))
                py = y + spark_h - int((v - lo) / span * spark_h)
                points.append((px, py))
            if len(points) >= 2:
                pygame.draw.lines(self.screen, C_ACCENT, False, points, 1)
            for px, py in points[-1:]:  # highlight latest point
                pygame.draw.circle(self.screen, C_GOOD, (px, py), 2)

            # Latest value + trend verdict
            latest = series[-1]
            mid = len(series) // 2
            first_half = sum(series[:mid]) / max(mid, 1)
            second_half = sum(series[mid:]) / max(len(series) - mid, 1)
            improving = (second_half > first_half) == (desired == "up")
            arrow = "+" if second_half > first_half else ("-" if second_half < first_half else "=")
            color = C_GOOD if improving else C_WARN
            value_text = f"{latest:.2f}" if abs(latest) < 100 else f"{latest:.0f}"
            self._text(
                f"{value_text} {arrow}", (spark_x + spark_w + 10, y + 2), self.font_small, color
            )

            y += row_h

        # Learner internals below the curves
        self._draw_agent_internals(x0, y + 2)

    def _draw_agent_internals(self, x0: int, y0: int) -> None:
        """Learner internals: DQN (ε, loss, buffer) or PPO (entropy, loss, updates)."""
        agent = self._learner
        if agent is None:
            return
        parts: list[str] = []
        if hasattr(agent, "epsilon"):
            parts.append(f"ε={agent.epsilon:.2f}")
        entropy = getattr(agent, "entropy", None)
        if entropy is not None:
            parts.append(f"H={entropy:.2f}")
        loss = getattr(agent, "mean_episode_loss", None)
        if loss is not None:
            parts.append(f"loss={loss:.3f}")
        if hasattr(agent, "global_step"):
            parts.append(f"steps={agent.global_step}")
        if hasattr(agent, "buffer"):
            parts.append(f"buffer={len(agent.buffer)}")
        if hasattr(agent, "updates_done"):
            parts.append(f"updates={agent.updates_done}")
        if parts:
            self._text("  ".join(parts), (x0, y0), self.font_small, C_TEXT_DIM)

    def _draw_goals(self, x0: int, y0: int, w: int, max_rows: int = 7) -> None:
        """Milestone checklist: shows progress toward Pokémon Red goals.

        Centers the window of rows on the current objective so viewers always
        see what's done and what's next.
        """
        goals = self.goals.goals
        n = len(goals)
        # Window the list around the first undone goal (the current objective).
        cur = next((i for i, g in enumerate(goals) if not g.done), n - 1)
        start = max(0, min(cur - 1, max(0, n - max_rows)))
        y = y0
        for idx in range(start, min(start + max_rows, n)):
            g = goals[idx]
            if g.done:
                mark, color = "✓", C_GOOD
            elif idx == cur:
                mark, color = "▸", C_GOLD
            else:
                mark, color = "·", C_TEXT_DIM
            self._text(mark, (x0, y), self.font_small, color)
            label = self._wrap(g.label, self.font_small, w - 18, max_lines=1)[0]
            self._text(label, (x0 + 16, y), self.font_small, C_TEXT if g.done else color)
            y += 16

    # -- Clean-view sidebar (mode, strategy, goals, session stats) --

    def _draw_clean_sidebar(self) -> None:
        pygame = self.pygame
        x0 = self._game_rect.right
        w = self.win_w - x0
        pygame.draw.rect(self.screen, C_PANEL_ALT, (x0, 0, w, self._game_rect.h))
        pygame.draw.line(self.screen, C_PANEL_LINE, (x0, 0), (x0, self._game_rect.h))

        pad = 16
        x = x0 + pad
        y = 16

        # Mode + strategy headline
        color = C_MANUAL if self.manual_mode else C_AI
        self._text(f"● {'MANUAL' if self.manual_mode else 'AI'}", (x, y), self.font_huge, color)
        y += 34
        sub = "You are playing" if self.manual_mode else f"AI Strategy: {strategy_label(self.active_strategy)}"
        self._text(sub, (x, y), self.font_big, C_TEXT)
        y += 34

        # Goals
        self._text("GOALS", (x, y), self.font_big, C_ACCENT)
        gtext = f"{self.goals.completed}/{self.goals.total}"
        gw = self.font.size(gtext)[0]
        self._text(gtext, (x0 + w - gw - pad, y + 4), self.font, C_GOLD)
        y += 26
        self._draw_goals(x, y, w - 2 * pad, max_rows=8)
        y += 8 * 16 + 12

        pygame.draw.line(self.screen, C_PANEL_LINE, (x0 + 8, y), (self.win_w - 8, y))
        y += 10
        self._text("SESSION", (x, y), self.font_big, C_ACCENT)
        y += 26
        self._draw_session_stats(x, y, w - 2 * pad)

    def _draw_session_stats(self, x0: int, y0: int, w: int) -> None:
        info = self.last_info
        state = None
        if self.env is not None:
            try:
                state = self.env.state_reader.read()
            except Exception:
                state = None
        deaths = sum(1 for m in self.episode_history if m.blackout_occurred)
        best = max((m.cumulative_reward for m in self.episode_history), default=None)
        rows = [
            ("playtime", _fmt_duration(time.monotonic() - self._session_start)),
            ("badges", str(state.badge_count if state else 0)),
            ("party level", str(state.party_total_level if state else 0)),
            ("battles won", str(self._session_battles_won)),
            ("deaths", str(deaths)),
            ("maps explored", str(len(self.memory.maps_seen_run))),
            ("best episode", f"{best:+.0f}" if best is not None else "—"),
            ("episode", f"{self.episode + 1}/{self.total_episodes}"),
            ("steps", str(info.get("step_count", 0))),
            ("speed", next((lbl for lbl, s in SPEED_PRESETS if s == self.current_speed), "?")),
        ]
        y = y0
        for label, value in rows:
            self._text(label, (x0, y), self.font, C_TEXT_DIM)
            vw = self.font.size(value)[0]
            self._text(value, (x0 + w - vw, y), self.font, C_TEXT)
            y += 20

    # -- Bottom control panel --

    def _draw_bottom_panel(self) -> None:
        if self.view_mode == "full":
            self._draw_bottom_full()
        else:
            self._draw_bottom_thin()

    def _mode_strategy_labels(self, x: int, y: int) -> None:
        """Draw the '● AI / ● MANUAL' chip and the 'AI Strategy: ...' line."""
        manual = self.manual_mode
        color = C_MANUAL if manual else C_AI
        self._text(f"● {'MANUAL' if manual else 'AI'}", (x, y), self.font_big, color)
        off = self.font_big.size("● MANUAL ")[0]
        if manual:
            self._text("you have the controls", (x + off, y + 2), self.font, C_TEXT_DIM)
        else:
            self._text(
                f"AI Strategy: {strategy_label(self.active_strategy)}",
                (x + off, y + 2),
                self.font,
                C_TEXT,
            )

    def _session_ticker_text(self) -> str:
        """Compact session stats line: playtime · attempt · KOs · deaths · best."""
        deaths = sum(1 for m in self.episode_history if m.blackout_occurred)
        best = max((m.cumulative_reward for m in self.episode_history), default=None)
        cur = self.last_info.get("cumulative_reward")
        if cur is not None and (best is None or cur > best):
            best = cur
        parts = [
            _fmt_duration(time.monotonic() - self._session_start),
            f"attempt {self.episode + 1}",
            f"KOs {self._session_battles_won}",
            f"deaths {deaths}",
        ]
        if best is not None:
            parts.append(f"best {best:+.0f}")
        return "  ·  ".join(parts)

    def _draw_bottom_full(self) -> None:
        pygame = self.pygame
        y0 = self.game_h
        pygame.draw.rect(self.screen, C_PANEL, (0, y0, self.win_w, self.BOTTOM_H))
        pygame.draw.line(self.screen, C_PANEL_LINE, (0, y0), (self.win_w, y0))

        # State banner + mode/strategy
        state = self.control.state
        state_color = {
            RunState.RUNNING: C_GOOD,
            RunState.PAUSED: C_WARN,
            RunState.STOPPED: C_BAD,
        }[state]
        self._text(f"● {state.value}", (16, y0 + 8), self.font_big, state_color)
        self._mode_strategy_labels(170, y0 + 8)


        # Control buttons
        self._buttons = {}
        labels = [
            ("start", "START"),
            ("pause", "PAUSE"),
            ("step", "STEP"),
            ("stop", "STOP"),
            ("restart", "RESTART"),
        ]
        bw, bh = 84, 34
        bx, by = 16, y0 + 46
        for name, label in labels:
            active = (
                (name == "start" and state == RunState.RUNNING)
                or (name == "pause" and state == RunState.PAUSED)
                or (name == "stop" and state == RunState.STOPPED)
            )
            self._button(name, pygame.Rect(bx, by, bw, bh), label, active, self._buttons)
            bx += bw + 8

        # Manual + options toggles
        bx += 6
        self._button(
            "manual",
            pygame.Rect(bx, by, 100, bh),
            "MANUAL" if not self.manual_mode else "AI MODE",
            self.manual_mode,
            self._buttons,
        )
        bx += 108
        self._button("options", pygame.Rect(bx, by, 100, bh), "OPTIONS", self.show_options, self._buttons)
        bx += 108

        # Speed controls
        sx = bx + 16
        self._text("SPEED", (sx, y0 + 12), self.font_small, C_ACCENT)
        self._draw_speed_buttons(sx, y0 + 46, 50, 34)

        # Controller display (right side)
        ctrl_x = sx + 4 * 56 + 24
        self._text("CONTROLLER", (ctrl_x, y0 + 8), self.font_small, C_ACCENT)
        self._draw_controller(ctrl_x, y0 + 28)

        # Keyboard hints (left) + session ticker (right) on the bottom row
        hint = "Space: pause   N: step   1-4: speed   Tab: view   M: manual   O: options"
        if self.manual_mode:
            hint = "MANUAL —  Arrows: move   X: A   Z: B    |    M: back to AI"
        self._text(hint, (16, y0 + self.BOTTOM_H - 18), self.font_small, C_TEXT_DIM)
        ticker = self._session_ticker_text()
        tw = self.font_small.size(ticker)[0]
        self._text(
            ticker, (self.win_w - tw - 16, y0 + self.BOTTOM_H - 18), self.font_small, C_TEXT
        )

    def _draw_bottom_thin(self) -> None:
        pygame = self.pygame
        y0 = self.win_h - self.THIN_H
        pygame.draw.rect(self.screen, C_PANEL, (0, y0, self.win_w, self.THIN_H))
        pygame.draw.line(self.screen, C_PANEL_LINE, (0, y0), (self.win_w, y0))

        state = self.control.state
        state_color = {
            RunState.RUNNING: C_GOOD,
            RunState.PAUSED: C_WARN,
            RunState.STOPPED: C_BAD,
        }[state]
        self._text(f"● {state.value}", (16, y0 + 8), self.font, state_color)
        self._mode_strategy_labels(150, y0 + 6)

        # Compact controls
        self._buttons = {}
        bw, bh = 78, 28
        bx, by = 16, y0 + 36
        toggle_label = "RESUME" if state == RunState.PAUSED else "PAUSE"
        for name, label in (
            ("toggle", toggle_label),
            ("step", "STEP"),
            ("stop", "STOP"),
            ("restart", "RESTART"),
        ):
            self._button(name, pygame.Rect(bx, by, bw, bh), label, False, self._buttons)
            bx += bw + 6
        bx += 6
        self._button(
            "manual",
            pygame.Rect(bx, by, 92, bh),
            "MANUAL" if not self.manual_mode else "AI MODE",
            self.manual_mode,
            self._buttons,
        )
        bx += 98
        self._button("options", pygame.Rect(bx, by, 92, bh), "OPTIONS", self.show_options, self._buttons)
        bx += 100
        self._draw_speed_buttons(bx + 10, by, 44, bh)

        hint = "Tab: view   O: options"
        if self.manual_mode:
            hint = "Arrows move · X=A · Z=B"
        hw = self.font_small.size(hint)[0]
        self._text(hint, (self.win_w - hw - 16, y0 + 12), self.font_small, C_TEXT_DIM)

    def _draw_speed_buttons(self, sx: int, y: int, sw: int, sh: int) -> None:
        pygame = self.pygame
        self._speed_buttons = {}
        for label, speed in SPEED_PRESETS:
            rect = pygame.Rect(sx, y, sw, sh)
            self._speed_buttons[speed] = rect
            active = speed == self.current_speed
            fill = C_GOOD if active else C_PANEL_LINE
            pygame.draw.rect(self.screen, fill, rect, border_radius=6)
            lw, lh = self.font.size(label)
            self._text(
                label,
                (sx + (sw - lw) // 2, y + (sh - lh) // 2),
                self.font,
                C_BG if active else C_TEXT,
            )
            sx += sw + 6

    def _draw_controller(self, x0: int, y0: int) -> None:
        """Gamepad layout with the last-pressed button highlighted."""
        pygame = self.pygame
        pressed = ""
        if self.last_action is not None:
            pressed = ACTION_TO_BUTTON.get(self.last_action, "")

        size = 22
        gap = 2
        # D-pad on the left, A/B on the right
        pads = {
            "UP": (x0 + size + gap, y0),
            "LEFT": (x0, y0 + size + gap),
            "RIGHT": (x0 + 2 * (size + gap), y0 + size + gap),
            "DOWN": (x0 + size + gap, y0 + 2 * (size + gap)),
            "B": (x0 + 4 * size + 16, y0 + size + gap + 8),
            "A": (x0 + 5 * size + 24, y0 + size - 8),
        }
        glyphs = {"UP": "^", "DOWN": "v", "LEFT": "<", "RIGHT": ">", "A": "A", "B": "B"}

        for name, (bx, by) in pads.items():
            active = name == pressed
            color = (C_MANUAL if self.manual_mode else C_ACCENT) if active else C_PANEL_LINE
            pygame.draw.rect(self.screen, color, (bx, by, size, size), border_radius=4)
            lbl = glyphs[name]
            lw, lh = self.font.size(lbl)
            self._text(
                lbl,
                (bx + (size - lw) // 2, by + (size - lh) // 2),
                self.font,
                C_BG if active else C_TEXT_DIM,
            )

        if pressed == "NOOP":
            self._text("NOOP", (x0 + 3 * size + 10, y0 + 2 * (size + gap) + 4), self.font, C_WARN)

    # -- Options / settings modal --

    def _draw_options(self) -> None:
        pygame = self.pygame
        # Dim backdrop
        overlay = pygame.Surface((self.win_w, self.win_h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 170))
        self.screen.blit(overlay, (0, 0))

        pw, ph = 520, 470
        px, py = (self.win_w - pw) // 2, (self.win_h - ph) // 2
        pygame.draw.rect(self.screen, C_PANEL, (px, py, pw, ph), border_radius=12)
        pygame.draw.rect(self.screen, C_ACCENT, (px, py, pw, ph), 2, border_radius=12)

        self._option_buttons = {}
        x = px + 24
        y = py + 18
        self._text("OPTIONS / SETTINGS", (x, y), self.font_big, C_ACCENT)
        y += 38

        y = self._option_row(
            "Control mode",
            [("AI", "mode:ai", not self.manual_mode), ("Manual", "mode:manual", self.manual_mode)],
            x, y, pw - 48,
        )
        y = self._option_row(
            "AI strategy",
            [
                (
                    STRATEGY_SHORT.get(s, s.title()),
                    f"strat:{s}",
                    (not self.manual_mode and self.active_strategy == s),
                )
                for s in STRATEGY_ORDER
            ],
            x, y, pw - 48,
        )
        y = self._option_row(
            "Sound",
            [("On", "sound:on", self.sound_on), ("Off", "sound:off", not self.sound_on)],
            x, y, pw - 48,
        )
        # Volume row (label + -/+ + value)
        self._text("Volume", (x, y + 6), self.font, C_TEXT_DIM)
        vol_x = x + 150
        self._button("vol:-", pygame.Rect(vol_x, y, 40, 30), "-", False, self._option_buttons)
        self._text(f"{self.audio.volume}%", (vol_x + 52, y + 6), self.font, C_TEXT)
        self._button("vol:+", pygame.Rect(vol_x + 100, y, 40, 30), "+", False, self._option_buttons)
        if not self.audio.ok:
            self._text("(no audio device)", (vol_x + 150, y + 6), self.font_small, C_WARN)
        y += 42
        y = self._option_row(
            "View",
            [
                ("Full", "view:full", self.view_mode == "full"),
                ("Clean", "view:clean", self.view_mode == "clean"),
                ("Game", "view:game", self.view_mode == "game"),
            ],
            x, y, pw - 48,
        )
        y = self._option_row(
            "Smooth video",
            [
                ("On", "smooth:on", self.config.smooth_rendering),
                ("Off", "smooth:off", not self.config.smooth_rendering),
            ],
            x, y, pw - 48,
        )
        y = self._option_row(
            "Auto-catch",
            [
                ("On", "catch:on", self.auto_catch),
                ("Off", "catch:off", not self.auto_catch),
            ],
            x, y, pw - 48,
        )
        y = self._option_row(
            "Speed",
            [(lbl, f"speed:{s}", s == self.current_speed) for lbl, s in SPEED_PRESETS],
            x, y, pw - 48,
        )

        # Close button + hint
        y += 8
        self._button(
            "close", pygame.Rect(px + pw - 124, py + ph - 48, 100, 32), "CLOSE", False, self._option_buttons
        )
        self._text("Press O or Esc to close", (x, py + ph - 40), self.font_small, C_TEXT_DIM)

    def _option_row(self, label: str, choices: list[tuple[str, str, bool]], x: int, y: int, w: int) -> int:
        """Draw a labeled row of toggle buttons; return the next y."""
        pygame = self.pygame
        self._text(label, (x, y + 6), self.font, C_TEXT_DIM)
        bx = x + 150
        bw = min(108, (w - 150) // max(len(choices), 1) - 6)
        for text, key, active in choices:
            self._button(key, pygame.Rect(bx, y, bw, 30), text, active, self._option_buttons)
            bx += bw + 6
        return y + 42


class _NullAgent:
    """Last-resort no-op agent (keeps the loop alive if strategy build fails)."""

    name = "none"
    thought = ""

    def act(self, observation) -> int:  # pragma: no cover - defensive
        return int(Action.NOOP)


def _fmt_duration(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"
