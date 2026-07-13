"""The FireRed story brain is emulator-agnostic and importable without mGBA/PIL.

Guards the extraction out of the Docker server: StoryAgent/Explorer construct
and step against a zero-memory mock emu (no real map) without raising, and the
objective bookkeeping has the expected shape. Navigation correctness itself is
covered by the Navigator/vision/pathing tests.
"""
from __future__ import annotations

from pokeai.agents.firered_story import Explorer, StoryAgent
from pokeai.perception.navigator import Navigator
from pokeai.skills.navigate_to import NavigateTo


class MockEmu:
    """Zero memory + recording input surface (the EmulatorWrapper contract)."""

    def __init__(self):
        self.mem: dict[int, int] = {}
        self.calls: list[tuple] = []

    def read_byte(self, a):
        return self.mem.get(a, 0)

    def read_u16(self, a):
        return self.read_byte(a) | (self.read_byte(a + 1) << 8)

    def read_u32(self, a):
        return self.read_u16(a) | (self.read_u16(a + 2) << 16)

    def read_range(self, s, e):
        return [self.mem.get(a, 0) for a in range(s, e)]

    def press_button_pulse(self, *a, **k):
        self.calls.append(("pulse", *a))

    def press_button_held(self, *a, **k):
        self.calls.append(("held", *a))

    def press_direction_settle(self, *a, **k):
        self.calls.append(("settle", *a))
        return False

    def tick(self, *a, **k):
        self.calls.append(("tick", *a))


def _brain():
    emu = MockEmu()
    nav = Navigator(emu)
    skill = NavigateTo(emu, nav)
    story = StoryAgent(emu, nav, skill, lambda *_: None)
    explorer = Explorer(emu, nav, lambda *_: None)
    return emu, story, explorer


def test_story_tasks_shape():
    _, story, _ = _brain()
    t = story.tasks()
    assert [x["name"] for x in t][:1] == ["Leave the bedroom"]
    assert t[-1]["name"] == "Explore & train"
    assert len(t) == len(story.objs) + 1


def test_story_step_runs_without_raising():
    _, story, _ = _brain()
    story.step()
    assert 0 <= story.idx <= len(story.objs)


def test_explorer_step_runs_without_raising():
    _, _, explorer = _brain()
    explorer.step()  # zero map -> falls through to idle tick, must not raise
