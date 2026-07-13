"""PyBoy emulator wrapper.

Encapsulates PyBoy v2.6.1 API to keep the rest of the codebase
decoupled from emulator specifics. If PyBoy changes its API or we
swap emulators, this is the only file that should need to change.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
from pyboy import PyBoy

# Game Boy OAM holds 40 sprite slots
_SPRITE_COUNT = 40


class EmulatorWrapper:
    """Thin wrapper around PyBoy with the operations we need."""

    BUTTON_NAMES = {
        "A": "a",
        "B": "b",
        "UP": "up",
        "DOWN": "down",
        "LEFT": "left",
        "RIGHT": "right",
        "START": "start",
        "SELECT": "select",
    }

    def __init__(
        self,
        rom_path: Path,
        render: bool = False,
        sound: bool = False,
        emulation_speed: int = 0,
        capture_screen: bool = False,
        emulate_sound: bool = False,
    ):
        # PyBoy v2.6.1: window="null" disables rendering for headless training.
        # capture_screen=True keeps the window off but still renders frames into
        # the screen buffer so they can be displayed elsewhere (e.g. the dashboard).
        window = "SDL2" if render else "null"
        # Audio: PyBoy only routes audio to a real output *device* through an SDL2
        # window. But with sound emulation on it still fills `pyboy.sound.ndarray`
        # every frame even when window="null", so the dashboard can pull those
        # samples and play them itself (see audio_samples()). emulate_sound enables
        # the APU without needing the native window. NOTE: a save state created
        # with sound disabled restores a disabled sampler, so the init state must
        # be generated with sound on for audio_samples() to be non-empty.
        self._emulate_sound = sound or emulate_sound
        self.pyboy = PyBoy(
            str(rom_path),
            window=window,
            sound_emulated=self._emulate_sound,
            sound_volume=100 if sound else 0,
        )
        self.pyboy.set_emulation_speed(emulation_speed)
        self._render = render or capture_screen
        # Optional callback invoked after every single emulated frame, used by the
        # dashboard to (a) collect audio samples continuously and (b) redraw the
        # game view smoothly during a multi-frame step. None on the headless
        # training path so tick() keeps its fast single-call behavior.
        self._frame_hook: Callable[[], None] | None = None

    def load_state(self, state_path: Path) -> None:
        with open(state_path, "rb") as f:
            self.pyboy.load_state(f)

    def save_state(self, state_path: Path) -> None:
        with open(state_path, "wb") as f:
            self.pyboy.save_state(f)

    def press_button(self, button: str) -> None:
        """Press a button for one frame. Button is one of BUTTON_NAMES keys, or 'NOOP'."""
        if button == "NOOP":
            return
        if button not in self.BUTTON_NAMES:
            raise ValueError(f"Unknown button: {button}")
        self.pyboy.button(self.BUTTON_NAMES[button])

    def press_button_held(self, button: str, frames: int) -> None:
        """Hold a button across all frames, pressing it once per frame.

        Gen 1 Pokemon requires ~17 consecutive frames of input per tile moved.
        Calling button() once then tick(N) only registers 1 frame of input, which
        is not enough. This method presses the button on every frame of the tick.
        """
        if button == "NOOP":
            self._tick_frames(frames)
            return
        if button not in self.BUTTON_NAMES:
            raise ValueError(f"Unknown button: {button}")
        name = self.BUTTON_NAMES[button]
        for _ in range(frames):
            self.pyboy.button(name)
            self.pyboy.tick(1, render=self._render)
            if self._frame_hook is not None:
                self._frame_hook()

    def press_button_pulse(self, button: str, frames: int, hold: int = 8) -> None:
        """Press for `hold` frames, then release for the remainder of `frames`.

        Gen 1 menus and dialogue advance on a *new* press edge — a button held
        across consecutive env steps is one continuous press the game ignores
        after the first frame. Verified live: an agent holding A every step
        never gets past "Wild RATTATA appeared!", while pulsed presses sail
        through. Use this for A/B; directions use press_button_held (walking
        requires a continuous hold).
        """
        if button == "NOOP":
            self._tick_frames(frames)
            return
        if button not in self.BUTTON_NAMES:
            raise ValueError(f"Unknown button: {button}")
        name = self.BUTTON_NAMES[button]
        hold = min(hold, frames)
        for _ in range(hold):
            self.pyboy.button(name)
            self.pyboy.tick(1, render=self._render)
            if self._frame_hook is not None:
                self._frame_hook()
        self._tick_frames(frames - hold)

    # Player position + map registers (pokered), read to detect a completed move.
    _ADDR_Y_POS = 0xD361
    _ADDR_X_POS = 0xD362
    _ADDR_CUR_MAP = 0xD35E

    def press_direction_settle(self, button: str, max_frames: int = 48, settle: int = 4) -> bool:
        """Hold a direction until the player moves exactly one tile (or until
        `max_frames`), then let the move settle. This yields clean, one-tile
        moves so before/after position reads are reliable — Gen 1 moves take ~16
        frames and otherwise bleed across a fixed-length env step, which corrupts
        a tile-accurate world model. Returns True if the player moved.

        Falls back to a plain held press if this isn't a movement button.
        """
        if button not in self.BUTTON_NAMES:
            raise ValueError(f"Unknown button: {button}")
        name = self.BUTTON_NAMES[button]

        def pos() -> tuple[int, int, int]:
            return (
                self.read_byte(self._ADDR_X_POS),
                self.read_byte(self._ADDR_Y_POS),
                self.read_byte(self._ADDR_CUR_MAP),
            )

        start = pos()
        moved = False
        for _ in range(max_frames):
            self.pyboy.button(name)
            self.pyboy.tick(1, render=self._render)
            if self._frame_hook is not None:
                self._frame_hook()
            if pos() != start:
                moved = True
                break
        # Settle so the walk animation fully commits before the next read.
        for _ in range(settle):
            self.pyboy.tick(1, render=self._render)
            if self._frame_hook is not None:
                self._frame_hook()
        return moved

    def _tick_frames(self, frames: int) -> None:
        """Advance `frames`, invoking the per-frame hook if one is set.

        Without a hook we tick all frames in one PyBoy call (fast path used by
        headless training). With a hook we step frame-by-frame so the dashboard
        can render smoothly and capture audio for every frame.
        """
        if self._frame_hook is None:
            self.pyboy.tick(frames, render=self._render)
            return
        for _ in range(frames):
            self.pyboy.tick(1, render=self._render)
            self._frame_hook()

    def tick(self, frames: int = 1) -> None:
        """Advance the emulator. Rendering only happens on the last frame."""
        self._tick_frames(frames)

    def set_speed(self, speed: int) -> None:
        """Change emulation speed at runtime. 0 = unlimited, 1 = normal, N = Nx."""
        self.pyboy.set_emulation_speed(speed)

    def set_frame_hook(self, hook: Callable[[], None] | None) -> None:
        """Register a callback fired after every emulated frame (or None to clear)."""
        self._frame_hook = hook

    @property
    def sound_sample_rate(self) -> int:
        """Audio sample rate in Hz (per channel). 0 if sound is not emulated."""
        if not self._emulate_sound:
            return 0
        try:
            return int(self.pyboy.sound.sample_rate)
        except Exception:
            return 0

    def audio_samples(self) -> np.ndarray:
        """Stereo audio generated during the most recent frame.

        Returns an (N, 2) int8 array (left, right). Empty if sound is not
        emulated or the loaded save state has sampling disabled. The buffer is
        cleared every frame, so call this once per frame (via the frame hook).
        """
        if not self._emulate_sound:
            return np.empty((0, 2), dtype=np.int8)
        try:
            return np.array(self.pyboy.sound.ndarray, dtype=np.int8, copy=True)
        except Exception:
            return np.empty((0, 2), dtype=np.int8)

    def read_byte(self, addr: int) -> int:
        return self.pyboy.memory[addr]

    def read_range(self, start: int, end: int) -> list[int]:
        """Read bytes in [start, end). Returns a list of ints."""
        return list(self.pyboy.memory[start:end])

    # --- Diagnostic / dashboard accessors ---

    def screen_rgb(self) -> np.ndarray:
        """Copy of the current screen as (144, 160, 3) RGB uint8.

        Requires render or capture_screen to be enabled, otherwise the
        buffer is stale/blank.
        """
        return self.pyboy.screen.ndarray[:, :, :3].copy()

    def game_area(self) -> np.ndarray | None:
        """Screen tile-identifier grid (18 rows x 20 cols), or None if unavailable.

        Provided by PyBoy's Pokemon Gen 1 game wrapper (auto-enabled for
        POKEMON RED cartridges).
        """
        try:
            return np.asarray(self.pyboy.game_area(), dtype=np.uint32).copy()
        except Exception:
            return None

    def game_area_collision(self) -> np.ndarray | None:
        """Walkability grid (18 rows x 20 cols): 1 = walkable, 0 = blocked.

        Only meaningful in the overworld; returns None if the game wrapper
        does not support collision (e.g. non-Pokemon ROM).
        """
        try:
            return np.asarray(self.pyboy.game_area_collision(), dtype=np.uint32).copy()
        except Exception:
            return None

    def visible_sprites(self) -> list[tuple[int, int, int]]:
        """On-screen sprites as (x_px, y_px, tile_identifier) tuples."""
        out = []
        for i in range(_SPRITE_COUNT):
            sprite = self.pyboy.get_sprite(i)
            if sprite.on_screen:
                out.append((sprite.x, sprite.y, sprite.tile_identifier))
        return out

    def close(self) -> None:
        self.pyboy.stop(save=False)
