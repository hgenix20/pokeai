"""navigate_to — the foundational callable skill (F3).

Wraps the verified `perception.navigator.Navigator` (vision collision grid + BFS
+ tile-accurate movement + warp triggering + warp-avoiding overworld nav) into
the verbs the planner/task-queue dispatches:

  * tile(target)        — walk to (x, y) on the current map
  * warp(warp_xy)       — path to and trigger a specific warp (stairs/door)
  * leave_building()    — exit to the overworld (nearest working exit door)
  * overworld_exit(dir) — walk off a map-connection edge to the adjacent map

Synchronous v1 (drives to completion). The resumable `step() -> Action` form the
real-time loop wants (design §7) is a thin later adaptation; the planning/driving
logic lives here and in Navigator so it stays the single source of truth.
"""
from __future__ import annotations

from pokeai.perception.navigator import Navigator

_EDGE = {
    # direction -> (sort key for the edge gap, button to walk off the edge)
    "north": (lambda w, h, px: (lambda t: (t[1], abs(t[0] - px))), "UP"),
    "south": (lambda w, h, px: (lambda t: (-t[1], abs(t[0] - px))), "DOWN"),
    "west": (lambda w, h, px: (lambda t: (t[0], abs(t[1]))), "LEFT"),
    "east": (lambda w, h, px: (lambda t: (-t[0], abs(t[1]))), "RIGHT"),
}


class NavigateTo:
    name = "navigate_to"

    def __init__(self, emu, navigator: Navigator | None = None):
        self.emu = emu
        self.nav = navigator or Navigator(emu)

    def current_map(self) -> tuple[int, int]:
        return self.nav.current_map()

    def tile(self, target: tuple[int, int]) -> bool:
        return self.nav.go_to(target)

    def warp(self, warp_xy: tuple[int, int]) -> tuple[int, int] | None:
        return self.nav.take_warp(warp_xy)

    def leave_building(self) -> tuple[int, int] | None:
        return self.nav.leave_building()

    def overworld_exit(self, direction: str = "north", steps: int = 10) -> tuple[int, int] | None:
        """Navigate (warp-avoiding) to the map-edge gap in `direction` and walk
        off it to the connected map. A-mashes between steps so an edge event
        (e.g. the Oak intercept) advances. Returns the new map, or None."""
        if direction not in _EDGE:
            raise ValueError(f"direction must be one of {list(_EDGE)}")
        w, h, m = self.nav.vision.layout()
        warps = {(wp["x"], wp["y"]) for wp in self.nav.map_warps_full()}
        px, py = self.nav.vision.player_xy()
        keyfn, press = _EDGE[direction]
        cands = [(x, y) for y in range(h) for x in range(w)
                 if self.nav.vision.walkable(x, y, (w, h, m)) and (x, y) not in warps]
        if not cands:
            return None
        cands.sort(key=keyfn(w, h, px))
        self.nav.go_to(cands[0])
        start = self.current_map()
        for _ in range(steps):
            self.emu.press_direction_settle(press)
            for _ in range(2):
                self.emu.press_button_pulse("A", 16)  # advance any edge event
            if self.current_map() != start:
                return self.current_map()
        return None
