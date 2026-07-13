"""Tests for ActionController button dispatch, incl. settled overworld moves."""
from __future__ import annotations

from pokeai.env.action_controller import ActionController, Action


class RecordingEmu:
    """Records which press method each action routed to."""

    def __init__(self, in_battle: bool = False):
        self._in_battle = in_battle
        self.calls: list[tuple[str, str]] = []

    def read_byte(self, addr: int) -> int:
        # 0xD057 = wIsInBattle
        return 1 if (addr == 0xD057 and self._in_battle) else 0

    def press_button_pulse(self, button: str, frames: int, hold: int = 8) -> None:
        self.calls.append(("pulse", button))

    def press_button_held(self, button: str, frames: int) -> None:
        self.calls.append(("held", button))

    def press_direction_settle(self, button: str, max_frames: int = 48, settle: int = 4) -> bool:
        self.calls.append(("settle", button))
        return True


def test_ab_are_pulsed():
    emu = RecordingEmu()
    ctrl = ActionController(emu, frame_skip=24)
    ctrl.apply(int(Action.A))
    ctrl.apply(int(Action.B))
    assert emu.calls == [("pulse", "A"), ("pulse", "B")]


def test_overworld_directions_settle():
    emu = RecordingEmu(in_battle=False)
    ctrl = ActionController(emu, frame_skip=24)
    ctrl.apply(int(Action.UP))
    ctrl.apply(int(Action.RIGHT))
    assert emu.calls == [("settle", "UP"), ("settle", "RIGHT")]


def test_battle_directions_are_fixed_held():
    """In battle, directions drive the menu cursor -> fixed-length press."""
    emu = RecordingEmu(in_battle=True)
    ctrl = ActionController(emu, frame_skip=24)
    ctrl.apply(int(Action.DOWN))
    assert emu.calls == [("held", "DOWN")]


def test_falls_back_when_no_settle_support():
    """An emulator without press_direction_settle (e.g. the mock) uses held."""

    class OldEmu:
        def __init__(self):
            self.calls: list[tuple[str, str]] = []

        def read_byte(self, addr: int) -> int:
            return 0

        def press_button_held(self, button: str, frames: int) -> None:
            self.calls.append(("held", button))

        def press_button_pulse(self, button: str, frames: int, hold: int = 8) -> None:
            self.calls.append(("pulse", button))

    emu = OldEmu()
    ctrl = ActionController(emu, frame_skip=24)
    ctrl.apply(int(Action.LEFT))
    assert emu.calls == [("held", "LEFT")]
