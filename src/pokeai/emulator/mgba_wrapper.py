"""mGBA emulator wrapper (Pokémon FireRed / GBA).

The GBA counterpart of `pyboy_wrapper.EmulatorWrapper`. It deliberately mirrors
that class's PUBLIC surface (load/save state, button press/hold/pulse/settle,
tick, frame hook, read_byte/read_range, screen_rgb, close) so the env, loop, and
dashboard can swap emulators without changing. See docs/FIRERED_REDESIGN.md §4.

Backed by mGBA via PyGBA (`PyGBA.load` → `core.run_frame` / `core.add_keys` /
`read_u*` / `save_raw_state`). Milestone 0 (docs §1.2) proved this stack boots
FireRed headless. This is the ONLY file that should know mGBA/PyGBA specifics.

Differences from the PyBoy wrapper, by design:
  * GBA screen is 240×160 (PyBoy was 160×144); `screen_rgb()` is (160, 240, 3).
  * The Gen-1 PyBoy game-wrapper conveniences (`game_area`,
    `game_area_collision`, `visible_sprites`) DO NOT EXIST on GBA. They are not
    provided here; that information is reconstructed from EWRAM + pixels in
    `perception/vision.py` (phase F2).
  * Button frame-timing for GBA is NOT the Gen-1 "~17 frames/tile" rule; the
    constants below are reasonable starting points to be re-measured live (F1).
  * Audio is deferred (returns empty); wired in a later phase.

mgba logs very verbosely to stdout by default; we silence it on import.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np

import mgba.core
import mgba.image
from pygba import PyGBA
from pygba.utils import KEY_MAP

# Silence mgba's per-frame BIOS/DMA/video trace logging (otherwise it floods
# stdout). Best-effort: the API has varied across mgba versions.
try:  # pragma: no cover - depends on the mgba build
    import mgba.log

    mgba.log.silence()
except Exception:  # noqa: BLE001
    pass

# GBA native screen dimensions.
SCREEN_W, SCREEN_H = 240, 160

# Starting points for input timing on GBA, to be re-measured live (F1). FireRed
# overworld movement is ~16 frames/tile at walking speed; menus/dialogue advance
# on a fresh press edge, so A/B are pulsed like the Gen-1 wrapper.
DEFAULT_HOLD_FRAMES = 16
DEFAULT_PULSE_HOLD = 8


class MgbaEmulator:
    """Thin wrapper around PyGBA/mGBA with the operations pokeai needs.

    Public surface matches `pyboy_wrapper.EmulatorWrapper`. `render`/`sound`/
    `emulation_speed` are accepted for signature compatibility; headless pacing
    is controlled by the caller (the loop/dashboard), so speed is a no-op here.
    """

    BUTTON_NAMES = {
        "A": "A",
        "B": "B",
        "UP": "up",
        "DOWN": "down",
        "LEFT": "left",
        "RIGHT": "right",
        "START": "start",
        "SELECT": "select",
        "L": "L",
        "R": "R",
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
        self._gba = PyGBA.load(str(rom_path))
        self._core = self._gba.core
        # Wire a video buffer so screen_rgb() works headlessly (mGBA renders into
        # it every frame regardless of any window).
        self._fb = mgba.image.Image(*self._core.desired_video_dimensions())
        self._core.set_video_buffer(self._fb)
        self._core.reset()  # the video buffer takes effect after a reset
        self._frame_hook: Callable[[], None] | None = None
        self._init_state = None  # in-memory raw state for fast reset()

    # --- key helpers ---

    def _mask(self, button: str) -> int:
        if button not in self.BUTTON_NAMES:
            raise ValueError(f"Unknown button: {button}")
        return KEY_MAP[self.BUTTON_NAMES[button]]

    def _run_frame(self) -> None:
        self._core.run_frame()
        if self._frame_hook is not None:
            self._frame_hook()

    # --- state ---

    def capture_init_state(self) -> None:
        """Snapshot the current machine as the in-memory reset point."""
        self._init_state = self._core.save_raw_state()

    def restore_init_state(self) -> bool:
        """Restore the snapshot taken by capture_init_state(). True if one exists."""
        if self._init_state is None:
            return False
        self._core.load_raw_state(self._init_state)
        self._core.run_frame()
        return True

    def load_state(self, state_path: Path) -> None:
        # TODO(F1): file (de)serialization of mGBA raw states. For now episodes
        # reset from the in-memory snapshot (capture/restore_init_state), which is
        # what the loop needs; persisting named states to disk comes with the
        # state-generation scripts. Left explicit so callers don't assume it works.
        raise NotImplementedError(
            "mGBA file save-states not wired yet (F1). Use capture/restore_init_state()."
        )

    def save_state(self, state_path: Path) -> None:
        raise NotImplementedError(
            "mGBA file save-states not wired yet (F1). Use capture/restore_init_state()."
        )

    # --- input ---

    def press_button(self, button: str) -> None:
        """Press a button for one frame. `button` is a BUTTON_NAMES key, or 'NOOP'."""
        if button == "NOOP":
            self._run_frame()
            return
        mask = self._mask(button)
        self._core.add_keys(mask)
        self._run_frame()
        self._core.clear_keys(mask)

    def press_button_held(self, button: str, frames: int) -> None:
        """Hold a button across all frames (used for directional movement)."""
        if button == "NOOP":
            self._tick_frames(frames)
            return
        mask = self._mask(button)
        self._core.add_keys(mask)
        for _ in range(frames):
            self._run_frame()
        self._core.clear_keys(mask)

    def press_button_pulse(self, button: str, frames: int, hold: int = DEFAULT_PULSE_HOLD) -> None:
        """Press for `hold` frames then release for the rest. Menus/dialogue advance
        on a fresh press edge, so use this for A/B; directions use press_button_held."""
        if button == "NOOP":
            self._tick_frames(frames)
            return
        mask = self._mask(button)
        hold = min(hold, frames)
        self._core.add_keys(mask)
        for _ in range(hold):
            self._run_frame()
        self._core.clear_keys(mask)
        self._tick_frames(frames - hold)

    # FireRed live player coords: gObjectEvents[0] currentCoords (x@+0x10,
    # y@+0x12). The low byte alone tracks a one-tile change (coords < 256), which
    # is all press_direction_settle needs. VERIFIED live (see firered_state_reader).
    _ADDR_X_POS = 0x02036E48
    _ADDR_Y_POS = 0x02036E4A

    def press_direction_settle(self, button: str, max_frames: int = 48, settle: int = 8) -> bool:
        """Hold a direction until the player advances exactly one tile (or
        max_frames), release, and settle. This yields tile-accurate moves so a
        BFS path stays in sync — a plain held press can over-shoot 1-2 tiles.
        Returns True if the player moved (or a warp fired and jumped coords)."""
        mask = self._mask(button)

        def pos() -> tuple[int, int]:
            return (self.read_byte(self._ADDR_X_POS), self.read_byte(self._ADDR_Y_POS))

        start = pos()
        moved = False
        self._core.add_keys(mask)
        for _ in range(max_frames):
            self._run_frame()
            if pos() != start:
                moved = True
                break
        self._core.clear_keys(mask)
        # Let the committed tile-step (and any warp transition) finish before the
        # next read, so the caller sees a stable post-move position.
        for _ in range(settle):
            self._run_frame()
        return moved

    # --- ticking / speed / hooks ---

    def _tick_frames(self, frames: int) -> None:
        for _ in range(frames):
            self._run_frame()

    def tick(self, frames: int = 1) -> None:
        self._tick_frames(frames)

    def set_speed(self, speed: int) -> None:
        """No-op: headless pacing is controlled by the caller (loop/dashboard)."""

    def set_frame_hook(self, hook: Callable[[], None] | None) -> None:
        self._frame_hook = hook

    # --- audio (deferred) ---

    @property
    def sound_sample_rate(self) -> int:
        return 0  # TODO: wire mGBA audio in a later phase

    def audio_samples(self) -> np.ndarray:
        return np.empty((0, 2), dtype=np.int8)

    # --- memory ---

    def read_byte(self, addr: int) -> int:
        return self._gba.read_u8(addr)

    def read_range(self, start: int, end: int) -> list[int]:
        """Read bytes in [start, end). Returns a list of ints."""
        return list(self._gba.read_memory(start, end - start))

    def read_u16(self, addr: int) -> int:
        return self._gba.read_u16(addr)

    def read_u32(self, addr: int) -> int:
        return self._gba.read_u32(addr)

    # --- screen ---

    def screen_rgb(self) -> np.ndarray:
        """Current screen as (160, 240, 3) RGB uint8."""
        return np.asarray(self._fb.to_pil().convert("RGB"), dtype=np.uint8)

    # NOTE: game_area(), game_area_collision(), visible_sprites() are intentionally
    # absent. They were PyBoy Gen-1 game-wrapper features with no GBA equivalent;
    # walkability/grass/NPC perception is rebuilt in perception/vision.py (F2).

    def close(self) -> None:
        # PyGBA holds the core; dropping references frees it.
        self._init_state = None
        self._fb = None
        self._core = None
        self._gba = None
