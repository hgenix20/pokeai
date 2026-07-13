"""ROM-free test that the navigate_to skill delegates to the Navigator."""
from __future__ import annotations

from pokeai.skills.navigate_to import NavigateTo


class StubNav:
    def __init__(self):
        self.calls: list = []

    def current_map(self):
        return (3, 0)

    def go_to(self, t):
        self.calls.append(("go_to", t))
        return True

    def take_warp(self, w):
        self.calls.append(("take_warp", w))
        return (4, 0)

    def leave_building(self):
        self.calls.append(("leave_building",))
        return (3, 0)


def test_navigate_to_delegates_to_navigator():
    nav = StubNav()
    skill = NavigateTo(emu=None, navigator=nav)
    assert skill.tile((5, 6)) is True
    assert skill.warp((10, 2)) == (4, 0)
    assert skill.leave_building() == (3, 0)
    assert skill.current_map() == (3, 0)
    assert nav.calls == [("go_to", (5, 6)), ("take_warp", (10, 2)), ("leave_building",)]


def test_overworld_exit_rejects_bad_direction():
    import pytest
    skill = NavigateTo(emu=None, navigator=StubNav())
    with pytest.raises(ValueError):
        skill.overworld_exit("sideways")
