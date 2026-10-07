"""Action controller. Discrete action space, 7 actions.

START and SELECT are excluded per Phase 1 decision. If START is needed
for menu access in later phases, append it to ACTIONS and update the
action space dimension.
"""
from __future__ import annotations

from enum import IntEnum

from pokeai.emulator.pyboy_wrapper import EmulatorWrapper


class Action(IntEnum):
    NOOP = 0
    A = 1
    B = 2
    UP = 3
    DOWN = 4
    LEFT = 5
    RIGHT = 6


# Maps integer action -> button name expected by EmulatorWrapper
ACTION_TO_BUTTON: dict[int, str] = {
    Action.NOOP: "NOOP",
    Action.A: "A",
    Action.B: "B",
    Action.UP: "UP",
    Action.DOWN: "DOWN",
    Action.LEFT: "LEFT",
    Action.RIGHT: "RIGHT",
}

ACTION_SPACE_SIZE = len(Action)


class ActionController:
    """Translates discrete actions into emulator button presses.

    Directions are held for the whole step (walking needs a continuous hold);
    A/B are pulsed (pressed then released within the step) because Gen 1 menus
    and dialogue only advance on a new press *edge* — holding A across steps
    is one continuous press the game ignores after the first frame.
    """

    # wIsInBattle (0 = overworld). In battle, directions drive the menu cursor,
    # so they must use fixed-frame presses; in the overworld they are walking
    # moves and we settle them to one clean tile.
    _ADDR_IS_IN_BATTLE = 0xD057

    def __init__(self, emulator: EmulatorWrapper, frame_skip: int):
        self.emu = emulator
        self.frame_skip = frame_skip

    def apply(self, action: int, settle_moves: bool = True) -> None:
        """Apply an action. `settle_moves` should be False whenever a direction
        drives a menu cursor rather than walking (battle, or an open overworld
        menu/dialogue) — there we need a fixed-length press, not a move that
        waits for the player tile to change (which never happens in a menu)."""
        if action not in ACTION_TO_BUTTON:
            raise ValueError(f"Invalid action: {action}")
        button = ACTION_TO_BUTTON[action]
        if button in ("A", "B"):
            self.emu.press_button_pulse(button, self.frame_skip)
        elif button == "NOOP":
            self.emu.press_button_held(button, self.frame_skip)
        elif (
            settle_moves
            and not self._in_battle()
            and hasattr(self.emu, "press_direction_settle")
        ):
            # Overworld walking: settle to one clean tile for reliable reads.
            self.emu.press_direction_settle(button)
        else:
            # Cursor navigation (battle/menu) or no settle support: fixed press.
            self.emu.press_button_held(button, self.frame_skip)

    def _in_battle(self) -> bool:
        try:
            return self.emu.read_byte(self._ADDR_IS_IN_BATTLE) != 0
        except Exception:
            return False
