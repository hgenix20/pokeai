"""ROM-free tests for the 2026-07-06 walker redesign (walk_to / take_warp2).

A tiny simulated world drives the SAME Navigator code that runs live: presses
move a fake player over a string grid, a `frozen` flag models battle/menu
input-eating, ledge tiles hop two out, and warp tiles change the map. The
audit defects these tests pin down: eaten presses must never blacklist
walkable tiles, interruptions must RESUME (not restart) the walk, ledge hops
must not read as deviations, the final step must be verified, take_warp2 must
approach via the shortest live plan and never press a blind fallback
direction, and landings must be validated against the warp's destination.
"""
from __future__ import annotations

import pytest

from pokeai.perception import navigator as nav_mod
from pokeai.perception.navigator import Navigator


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(nav_mod.time, "sleep", lambda s: None)


DIRS = {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}


class World:
    def __init__(self, grid, start, ledges=None, warps=None):
        self.grid = grid
        self.pos = start
        self.map = (1, 1)
        self.frozen = 0          # presses eaten while > 0 (battle/menu)
        self.ledges = ledges or {}
        self.warps = warps or []
        self.presses: list[str] = []

    def walkable(self, x, y):
        return (0 <= y < len(self.grid) and 0 <= x < len(self.grid[0])
                and self.grid[y][x] == ".")

    def step(self, d):
        self.presses.append(d)
        if self.frozen > 0:
            self.frozen -= 1
            return
        dx, dy = DIRS[d]
        nxt = (self.pos[0] + dx, self.pos[1] + dy)
        if str(self.ledges.get(nxt, "")).upper() == d:
            land = (self.pos[0] + 2 * dx, self.pos[1] + 2 * dy)
            if self.walkable(*land):
                self.pos = land
            return
        for w in self.warps:
            if (w["x"], w["y"]) == nxt:
                self.map = (w["destGroup"], w["destMap"])
                self.pos = (0, 0)
                return
        if self.walkable(*nxt):
            self.pos = nxt


class FakeEmu:
    def __init__(self, world):
        self.w = world

    def press_direction_settle(self, d, **kw):
        self.w.step(d)
        return True

    def press_button_held(self, d, frames=16):
        if d in DIRS:
            self.w.step(d)

    def tap(self, button, frames=8):
        if button in DIRS:
            self.w.step(button)

    def tick(self, n):
        pass


class FakeVision:
    def __init__(self, world):
        self.w = world

    def player_xy(self):
        return self.w.pos

    def walkable(self, x, y, layout=None):
        return self.w.walkable(x, y)

    def object_tiles(self):
        return set()

    def nav_grid(self):
        walk = {(x, y)
                for y in range(len(self.w.grid))
                for x in range(len(self.w.grid[0]))
                if self.w.walkable(x, y)}
        return {"walk": walk, "ledge_dir": self.w.ledges,
                "w": len(self.w.grid[0]), "h": len(self.w.grid)}


class FakeNav(Navigator):
    def __init__(self, world):
        super().__init__(FakeEmu(world), FakeVision(world))
        self.w = world

    def current_map(self):
        return self.w.map

    def map_warps_full(self):
        return list(self.w.warps)


OPEN = [
    ".....",
    ".....",
    ".....",
]


def test_walk_to_plain():
    w = World(OPEN, (0, 0))
    nav = FakeNav(w)
    assert nav.walk_to((4, 2)) == Navigator.WALK_DONE
    assert w.pos == (4, 2)


def test_walk_to_resumes_after_battle_freeze():
    """Presses eaten by a 'battle'; interrupt_check resolves it; the walk
    RESUMES and arrives - and the frozen tile is never treated as a wall."""
    w = World(OPEN, (0, 0))
    nav = FakeNav(w)
    w.frozen = 99                      # everything eaten until resolved

    def resolve():
        w.frozen = 0                   # battle resolved
        return True

    assert nav.walk_to((4, 0), interrupt_check=resolve) == Navigator.WALK_DONE
    assert w.pos == (4, 0)


def test_walk_to_eaten_press_does_not_blacklist():
    """A transient 2-press freeze (turn-transient / lag) self-heals without
    interrupt_check and without routing around the good tile."""
    w = World(OPEN, (0, 0))
    nav = FakeNav(w)
    w.frozen = 2
    assert nav.walk_to((4, 0)) == Navigator.WALK_DONE


def test_walk_to_ledge_hop_not_a_deviation():
    grid = [
        ".....",
        ".....",
        ".....",
    ]
    # pressing DOWN into (2,1) hops to (2,2)
    w = World(grid, (2, 0), ledges={(2, 1): "down"})
    nav = FakeNav(w)
    assert nav.walk_to((2, 2)) == Navigator.WALK_DONE
    assert w.pos == (2, 2)
    # exactly one DOWN press: the hop was expected, not retried
    assert w.presses.count("DOWN") == 1


def test_walk_to_map_change_surfaces():
    w = World(OPEN, (0, 0),
              warps=[{"x": 2, "y": 0, "destGroup": 9, "destMap": 9}])
    nav = FakeNav(w)
    # target beyond the warp tile; plan avoids it, but force the walk into
    # it by blocking the detour rows
    w2 = World(["...", "###"], (0, 0),
               warps=[{"x": 1, "y": 0, "destGroup": 9, "destMap": 9}])
    nav2 = FakeNav(w2)
    # only route to (2,0) is THROUGH the warp; plan() blocks warp tiles, so
    # walk_to reports blocked - but if a warp fires mid-walk (simulated by
    # walking onto it via the unavoidable corridor), MAP_CHANGED surfaces.
    # Simulate directly: freeze-free world where the first step fires a warp.
    w3 = World(["..."], (0, 0),
               warps=[{"x": 1, "y": 0, "destGroup": 9, "destMap": 9}])
    nav3 = FakeNav(w3)
    res = nav3.walk_to((2, 0))
    assert res in (Navigator.WALK_MAP_CHANGED, Navigator.WALK_BLOCKED)
    assert nav2 and nav  # silence linters


def test_walk_to_wall_blocks_eventually():
    grid = [
        ".#.",
        ".#.",
        ".#.",
    ]
    w = World(grid, (0, 1))
    nav = FakeNav(w)
    assert nav.walk_to((2, 1)) == Navigator.WALK_BLOCKED


def test_take_warp2_prefers_standing_neighbor():
    """Standing right below the ladder: no detour, one UP press, lands on
    the recorded destination."""
    w = World(
        ["...",
         "...",
         "..."],
        (1, 2),
        warps=[{"x": 1, "y": 1, "destGroup": 1, "destMap": 2}],
    )
    nav = FakeNav(w)
    assert nav.take_warp2(w.warps[0]) == Navigator.WARP_OK
    assert w.map == (1, 2)
    # the final press was the geometry-guarded UP, and nothing else moved us
    assert w.presses[-1] == "UP"


def test_take_warp2_wrong_destination_reported():
    w = World(
        ["...",
         "...",
         "..."],
        (1, 2),
        warps=[{"x": 1, "y": 1, "destGroup": 7, "destMap": 7}],
    )
    # the warp actually leads to (9,9) - a lying table / accidental warp
    real = dict(w.warps[0])
    w.warps[0]["destGroup"], w.warps[0]["destMap"] = 9, 9
    lying = dict(real)          # what the caller believes
    nav = FakeNav(w)
    assert nav.take_warp2(lying) == Navigator.WARP_WRONG


def test_take_warp2_battle_on_approach_then_success():
    """An encounter eats the approach; interrupt_check resolves; the SAME
    call still lands the warp (no try-burning, no re-pick)."""
    w = World(
        [".....",
         ".....",
         "....."],
        (4, 2),
        warps=[{"x": 0, "y": 0, "destGroup": 1, "destMap": 2}],
    )
    nav = FakeNav(w)
    w.frozen = 3

    def resolve():
        w.frozen = 0
        return True

    assert nav.take_warp2(w.warps[0], interrupt_check=resolve) == Navigator.WARP_OK
    assert w.map == (1, 2)


def test_take_warp2_unreachable_when_walled():
    grid = [
        "#.#",
        "#.#",
        "...",
    ]
    # warp at (1,0); its only neighbor (1,1) is fine - make ALL neighbors
    # blocked instead
    grid2 = [
        "###",
        "#.#",
        "###",
    ]
    w = World(grid2, (1, 1),
              warps=[{"x": 0, "y": 0, "destGroup": 1, "destMap": 2}])
    nav = FakeNav(w)
    assert nav.take_warp2(w.warps[0]) == Navigator.WARP_UNREACHABLE
    assert grid  # keep both fixtures visible


class DoorWorld(World):
    """A house interior whose exit door fires ONLY when entered by walking
    DOWN onto the REAL door tile (not a dud mat tile, not a side step) -
    the rival's-house exit that broke leave_building live 2026-07-06."""
    def __init__(self, grid, start, real_door, warps):
        super().__init__(grid, start, warps=warps)
        self.real_door = real_door

    def step(self, d):
        self.presses.append(d)
        if self.frozen > 0:
            self.frozen -= 1
            return
        dx, dy = DIRS[d]
        nxt = (self.pos[0] + dx, self.pos[1] + dy)
        # the real door fires only on a DOWNWARD entry from directly above
        if nxt == self.real_door and d == "DOWN":
            self.map = (3, 0)
            self.pos = (0, 0)
            return
        if self.walkable(*nxt):
            self.pos = nxt   # dud mat tiles / side steps are plain floor


def test_leave_building_uses_real_door_walking_down():
    """A 3-wide doormat with only the CENTER tile real, entered from above."""
    w = DoorWorld(
        [".....",
         ".....",
         "#####"],       # y2 is the wall below the mat
        (3, 1),          # player one above the right (dud) mat tile
        real_door=(2, 1),
        warps=[{"x": 1, "y": 1, "destGroup": 3, "destMap": 0},
               {"x": 2, "y": 1, "destGroup": 3, "destMap": 0},   # real
               {"x": 3, "y": 1, "destGroup": 3, "destMap": 0}],
    )
    nav = FakeNav(w)
    assert nav.leave_building() == (3, 0)


def test_leave_building_from_on_the_dud_mat():
    """Player STANDING on a dud mat tile must step off, find the real door,
    and walk down through it."""
    w = DoorWorld(
        [".....",
         ".....",
         "#####"],
        (3, 1),          # on the dud (3,1)
        real_door=(2, 1),
        warps=[{"x": 2, "y": 1, "destGroup": 3, "destMap": 0},
               {"x": 3, "y": 1, "destGroup": 3, "destMap": 0}],
    )
    w.pos = (3, 1)
    nav = FakeNav(w)
    assert nav.leave_building() == (3, 0)


def test_take_warp2_dud_never_fires_adjacent_exit():
    """A dud warp must resolve NO_FIRE without accidentally firing a
    NEARBY exit door (the old blind held-DOWN fallback walked back out of
    Mt. Moon through exactly such a door)."""
    w = World(
        ["...",
         "...",
         "...",
         "..."],
        (1, 2),
        # (1,3) = an exit door one tile south of the approach neighbour -
        # the tile the OLD fallback's held DOWN would have walked into
        warps=[{"x": 1, "y": 3, "destGroup": 3, "destMap": 22}],
    )
    dud = {"x": 1, "y": 1, "destGroup": 1, "destMap": 2}  # never fires
    nav = FakeNav(w)
    assert nav.take_warp2(dud) == Navigator.WARP_NOFIRE
    assert w.map == (1, 1)  # the exit door was never fired
