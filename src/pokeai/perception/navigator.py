"""Authoritative navigation: drive the player to a target tile or through a warp.

Packages the verified F2 pieces — FireRedVision (collision), bfs_path (planning),
and press_direction_settle (tile-accurate movement) — into one driver. This is
the foundation the `navigate_to` skill (F3) builds on.

Verified live (2026-06-16): the player BFS-paths the exact route to a warp tile
and take_warp() fires it (current_map changes to the warp's destination). Stairs/
door warps often need a STEP TOWARD the stairs after arrival, not just standing on
the tile, so take_warp nudges each direction until the map changes.
"""
from __future__ import annotations

import time

from pokeai.emulator.firered_state_reader import (
    GSAVEBLOCK1_PTR, SB1_MAP_GROUP_OFF, SB1_MAP_NUM_OFF,
)
from pokeai.perception.pathing import bfs_path
from pokeai.perception.vision import GMAPHEADER, FireRedVision

_MAPEVENTS_OFF = 0x04
_WARP_COUNT_OFF = 0x01
_WARPS_PTR_OFF = 0x08
_WARP_STRUCT = 8

# Known working exit doors for story buildings, keyed by (map group, map num) ->
# the door WARP TILE (x, y). A building's doormat can list several exit warps of
# which only one fires; hitting a dud on-camera makes the sprite bump the wall
# before backing off (viewer-facing polish, 2026-07-02). For maps in this table
# leave_building walks STRAIGHT to the real door — no dud probe. Add an entry per
# story building as we reach it; unknown buildings fall back to discover+cache.
KNOWN_EXITS = {
    (4, 0): (4, 8),   # Player's house 1F, Pallet Town — real door (5,8) is a dud
}


class Navigator:
    # Working exit door LEARNED per map, shared across Navigator instances in this
    # process (the boards make a fresh Navigator each Start). Seeded from
    # KNOWN_EXITS; every successful discovery adds to it, so any building is clean
    # on its 2nd+ exit even if it wasn't in the table.
    _door_cache: dict[tuple[int, int], tuple[int, int]] = dict(KNOWN_EXITS)

    def __init__(self, emu, vision: FireRedVision | None = None):
        self.emu = emu
        self.vision = vision or FireRedVision(emu)

    # --- map / warps ---

    def current_map(self) -> tuple[int, int]:
        """SaveBlock1 relocates EVERY frame, so deref-then-read can straddle a
        relocation and return garbage (seen live 2026-07-03: a mid-battle read
        broke a traversal loop). Read until two consecutive reads agree."""
        last = None
        for _ in range(4):
            sb1 = self.emu.read_u32(GSAVEBLOCK1_PTR)
            cur = (self.emu.read_byte(sb1 + SB1_MAP_GROUP_OFF),
                   self.emu.read_byte(sb1 + SB1_MAP_NUM_OFF))
            if cur == last:
                return cur
            last = cur
        return last

    def map_warps(self) -> list[tuple[int, int]]:
        return [(w["x"], w["y"]) for w in self.map_warps_full()]

    def map_warps_full(self) -> list[dict]:
        events = self.emu.read_u32(GMAPHEADER + _MAPEVENTS_OFF)
        n = self.emu.read_byte(events + _WARP_COUNT_OFF)
        wp = self.emu.read_u32(events + _WARPS_PTR_OFF)
        out = []
        for i in range(min(n, 16)):
            b = wp + i * _WARP_STRUCT
            out.append({
                "x": self.emu.read_u16(b + 0x00), "y": self.emu.read_u16(b + 0x02),
                "destMap": self.emu.read_byte(b + 0x06),
                "destGroup": self.emu.read_byte(b + 0x07),
            })
        return out

    # --- planning + driving ---

    def plan(self, target: tuple[int, int], avoid_warps: bool = True,
             extra_blocked: set | None = None) -> list[str] | None:
        start = self.vision.player_xy()
        blocked = self.vision.object_tiles()   # NPCs/objects not in the collision grid
        if avoid_warps:
            # Don't route THROUGH doors/stairs (they'd warp us away mid-travel).
            blocked |= {(w["x"], w["y"]) for w in self.map_warps_full()}
        if extra_blocked:
            blocked |= extra_blocked           # edges movement proved impassable
        blocked.discard(target)                # still allow reaching the target tile
        try:
            # bulk grid: one map sweep, ledge/grass-aware (grass is walkable),
            # one-way ledges hoppable in their direction so descents can cross.
            grid = self.vision.nav_grid()
            walk = grid["walk"]
            jumps = grid.get("ledge_dir")
            return bfs_path(start, target,
                            lambda x, y: (x, y) in walk and (x, y) not in blocked,
                            jump_ledges=jumps)
        except Exception:
            layout = self.vision.layout()   # mock/legacy fallback: per-tile reads
            return bfs_path(
                start, target,
                lambda x, y: self.vision.walkable(x, y, layout) and (x, y) not in blocked,
            )

    def walk_path(self, path: list[str]) -> bool:
        """Walk the directions one tile each, verifying movement. Returns True if
        the whole path was walked OR a map change (warp) interrupted it; False on
        an unexpected block (desync)."""
        for i, d in enumerate(path):
            before = self.vision.player_xy()
            start_map = self.current_map()
            self.emu.press_direction_settle(d.upper())
            if self.current_map() != start_map:
                return True  # warped mid-walk
            if self.vision.player_xy() == before and i < len(path) - 1:
                return False  # blocked unexpectedly
        return True

    _DELTA = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}

    def go_to(self, target: tuple[int, int], attempts: int = 10) -> bool:
        """Walk to target step by step, robust to the two real failure modes seen
        live (2026-07-03, Viridian City):

        1. **Transient no-op steps.** In FRLG the first press toward a new
           direction only TURNS the character; a held settle usually turns+steps,
           but animation/lag can leave it turned-not-moved. So a blocked step is
           RETRIED (up to 3x) before it's believed.
        2. **Accidental warps.** Stepping toward a door tile fires a warp. plan()
           already excludes warp tiles as path nodes; additionally, if the map
           changes unexpectedly this ABORTS (we can't navigate from inside a
           building we didn't mean to enter) unless the target itself was a warp.

        A step that stays blocked after retries is a genuine wall/elevation edge:
        that tile is BLACKLISTED and the route replanned around it."""
        learned: set[tuple[int, int]] = set()
        warps = {(w["x"], w["y"]) for w in self.map_warps_full()}
        start_map = self.current_map()
        target_is_warp = target in warps
        for _ in range(attempts):
            if self.vision.player_xy() == target:
                return True
            path = self.plan(target, extra_blocked=learned)
            if not path:
                return False
            for d in path:
                before = self.vision.player_xy()
                dx, dy = self._DELTA[d.lower()]
                step = (before[0] + dx, before[1] + dy)
                if step in warps and step != target:
                    learned.add(step)     # never step onto a door en route
                    break
                moved = False
                for _ in range(3):        # retry transient turn-not-step
                    self.emu.press_direction_settle(d.upper())
                    if self.current_map() != start_map:
                        return target_is_warp   # warped (intended only if target)
                    if self.vision.player_xy() != before:
                        moved = True
                        break
                if not moved:
                    learned.add(step)     # genuine wall/elevation edge
                    break
        return self.vision.player_xy() == target

    def _tick_until_map_change(self, start_map: tuple[int, int], max_ticks: int) -> None:
        ticked = 0
        while ticked < max_ticks and self.current_map() == start_map:
            self.emu.tick(20)
            ticked += 20

    # ------------------------------------------------------------------
    # walk_to / take_warp2: the 2026-07-06 walker redesign.
    #
    # Audit findings (Mt. Moon, 30-min failures on 3-tile approaches): go_to
    # blacklisted WALKABLE tiles whenever a battle/menu/box ate a press
    # (input-eaten is indistinguishable from a wall without classification),
    # restarted the whole approach after every interruption, take_warp's
    # fixed DOWN-first approach ordering detoured around doors, and its
    # blind held-DOWN fallback walked back OUT of cave exits. walk_to keeps
    # resume semantics (same path index across interruptions), verifies
    # each press against the EXPECTED tile (ledge hops land 2 tiles out),
    # lets the caller resolve battles/menus via `interrupt_check`, and only
    # blacklists (call-scoped) on repeated eaten presses that nothing could
    # resolve. take_warp2 picks the approach neighbour by plan length from
    # the CURRENT position, presses only the direction that faces the warp,
    # and validates the landing against the warp table's destination.
    # ------------------------------------------------------------------

    WALK_DONE = "done"
    WALK_MAP_CHANGED = "map_changed"
    WALK_BLOCKED = "blocked"

    def walk_to(self, target: tuple[int, int], interrupt_check=None,
                max_replans: int = 8) -> str:
        """Resume-capable walk to `target`. Returns WALK_DONE (standing on
        target), WALK_MAP_CHANGED (a warp/blackout moved us to another map -
        the caller must re-orient), or WALK_BLOCKED.

        `interrupt_check()` is called when a press is eaten twice with the
        position frozen: the caller resolves battles / clears menus there
        and returns truthy if it changed anything. The walk then resumes by
        replanning from the live position - it never restarts from scratch
        and never blacklists a tile just because input was eaten."""
        try:
            ledges = self.vision.nav_grid().get("ledge_dir") or {}
        except Exception:
            ledges = {}
        extra: set[tuple[int, int]] = set()
        replans = 0
        interrupts = 0
        while replans <= max_replans:
            if self.vision.player_xy() == target:
                return self.WALK_DONE
            start_map = self.current_map()
            path = self.plan(target, extra_blocked=extra)
            if path is None:
                # transient NPC block (object_tiles is a snapshot; FRLG NPCs
                # wander off a corridor tile within ~1-2s): wait and replan
                replans += 1
                time.sleep(1.5)
                continue
            replans += 1
            i, eaten = 0, 0
            while i < len(path):
                d = path[i]
                before = self.vision.player_xy()
                dx, dy = self._DELTA[d.lower()]
                step = (before[0] + dx, before[1] + dy)
                hop = str(ledges.get(step, "")).lower() == d.lower()
                expected = (before[0] + 2 * dx, before[1] + 2 * dy) if hop else step
                self.emu.press_direction_settle(d.upper())
                if self.current_map() != start_map:
                    return self.WALK_MAP_CHANGED
                now = self.vision.player_xy()
                if now == expected:
                    i += 1
                    eaten = 0
                    continue
                if now != before:
                    break               # displaced/deviated: replan from here
                eaten += 1              # press eaten, position frozen
                if eaten == 1:
                    continue            # FRLG turn-not-step: silent retry
                if interrupt_check is not None and interrupts < 8:
                    interrupts += 1
                    try:
                        handled = bool(interrupt_check())
                    except Exception:
                        handled = False
                    if self.current_map() != start_map:
                        return self.WALK_MAP_CHANGED
                    if handled:
                        break           # battle/menu resolved: replan+resume
                if eaten >= 3:
                    # nothing resolvable and thrice-eaten: wait out NPC
                    # wander once, then call-scoped block evidence
                    time.sleep(1.2)
                    if step != target:
                        extra.add(step)
                    break
        return (self.WALK_DONE if self.vision.player_xy() == target
                else self.WALK_BLOCKED)

    WARP_OK = "warped"
    WARP_WRONG = "wrong_warp"
    WARP_NOFIRE = "no_fire"
    WARP_UNREACHABLE = "unreachable"

    def take_warp2(self, warp: dict, interrupt_check=None) -> str:
        """Take a warp from its `map_warps_full()` row. Returns WARP_OK
        (landed on the warp's recorded destination), WARP_WRONG (a map
        change landed somewhere else - accidental warp or blackout),
        WARP_NOFIRE (approached and pressed, nothing fired), or
        WARP_UNREACHABLE (no approach neighbour ever had a path)."""
        wx, wy = warp["x"], warp["y"]
        dest = (warp["destGroup"], warp["destMap"])
        start_map = self.current_map()
        reached_press = False

        def landed() -> str:
            return self.WARP_OK if self.current_map() == dest else self.WARP_WRONG

        for _ in range(3):
            pos = self.vision.player_xy()
            best, best_len = None, None
            for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                nb = (wx + dx, wy + dy)
                if not self.vision.walkable(*nb):
                    continue
                if pos == nb:
                    best, best_len = nb, 0
                    break
                p = self.plan(nb)
                if p is not None and (best_len is None or len(p) < best_len):
                    best, best_len = nb, len(p)
            if best is None:
                time.sleep(2.0)         # transient NPC on every approach
                continue
            if pos != best:
                res = self.walk_to(best, interrupt_check=interrupt_check)
                if res == self.WALK_MAP_CHANGED:
                    return landed()
                if res != self.WALK_DONE:
                    continue
            # geometry-guarded final press: ONLY the direction whose next
            # tile IS the warp (the old blind held-DOWN fallback stepped
            # back out of cave doors)
            press = {(0, 1): "DOWN", (0, -1): "UP",
                     (1, 0): "RIGHT", (-1, 0): "LEFT"}[(wx - best[0], wy - best[1])]
            reached_press = True
            for _ in range(3):
                self.emu.press_button_held(press, 32)
                self._tick_until_map_change(start_map, 120)
                if self.current_map() != start_map:
                    return landed()
                if interrupt_check is not None:
                    try:
                        interrupt_check()
                    except Exception:
                        pass
                    if self.current_map() != start_map:
                        return landed()
                if self.vision.player_xy() != best:
                    break               # displaced (battle etc.): re-approach
        return self.WARP_NOFIRE if reached_press else self.WARP_UNREACHABLE

    # neighbor offset -> the held direction that STEPS from that neighbor INTO
    # the warp tile (door). Doors are almost always entered from directly above
    # (press DOWN), so that's tried first.
    _WARP_APPROACH = (
        ((0, -1), "DOWN"),   # stand above the door, walk down into it
        ((0, 1), "UP"),      # stand below, walk up
        ((-1, 0), "RIGHT"),  # stand left, walk right
        ((1, 0), "LEFT"),    # stand right, walk left
    )

    def take_warp(self, warp_xy: tuple[int, int]) -> tuple[int, int] | None:
        """Trigger a warp (door/stairs) CLEANLY: stand on a walkable neighbour of
        the warp tile and take one held step INTO it, in the single direction that
        faces the door. This replaces the old 'path onto the tile then try all
        four held directions' loop, whose wrong-direction presses made the sprite
        hit the wall, backtrack, and circle before finally leaving (walkthrough
        [Fix], 2026-07-02). A held press (not a one-tile settle) is required: the
        settle releases before the door/stairs transition completes."""
        start_map = self.current_map()
        wx, wy = warp_xy

        # Preferred: approach from a reachable neighbour and step straight in.
        for (dx, dy), press in self._WARP_APPROACH:
            nb = (wx + dx, wy + dy)
            if not self.vision.walkable(*nb):
                continue
            if self.vision.player_xy() != nb and not self.go_to(nb):
                continue
            self.emu.press_button_held(press, 32)
            self._tick_until_map_change(start_map, 120)
            if self.current_map() != start_map:
                return self.current_map()

        # Fallback: some warps ARE walkable and fire on step-on (or every
        # neighbour was blocked). Path onto the tile, then one DOWN nudge.
        self.go_to(warp_xy)
        self._tick_until_map_change(start_map, 120)
        if self.current_map() != start_map:
            return self.current_map()
        self.emu.press_button_held("DOWN", 32)
        self._tick_until_map_change(start_map, 120)
        if self.current_map() != start_map:
            return self.current_map()
        return None

    def leave_building(self) -> tuple[int, int] | None:
        """Walk out the exit door CLEANLY (walkthrough [Fix], 2026-07-02).

        A house's exit warps sit at the BOTTOM, and some tiles in the doormat row
        are DUDS that never fire (the 1F has (3,9) real + (4,8) + (5,8) dud). The
        old code sorted by distance, so it hit the (5,8) dud first and then
        `take_warp` flailed all four directions with 2-tile held presses -> the
        wall-bump / backtrack / circle. Instead: try the BOTTOM-MOST door first
        (the real doormat), approach only from directly ABOVE, step straight down
        through it, and if a tile duds, step back up and try the next -- no lateral
        flailing."""
        start = self.current_map()
        doors = [w for w in self.map_warps_full() if w["destGroup"] != start[0]]
        known = self._door_cache.get(start)
        px, py = self.vision.player_xy()
        # The known/learned door for this map goes STRAIGHT to the front (order 0),
        # so viewer-facing exits never probe a dud on-camera; otherwise nearest
        # first (discovery).
        doors.sort(key=lambda w: (0, 0) if (w["x"], w["y"]) == known
                   else (1, abs(w["x"] - px) + abs(w["y"] - py)))
        for w in doors:
            # A house door fires ONLY when you walk DOWN onto it from the tile
            # directly ABOVE - NOT from the side (take_warp2's nearest-
            # neighbour approach pressed sideways into it and never fired;
            # live 2026-07-06 rival's-house exit). So: get above the door,
            # then step DOWN, retrying through a frozen press (the FL-9
            # dialogue-tail case) and stepping off first if we START on the
            # dud mat tile.
            if self._exit_door_down(start, (w["x"], w["y"])):
                self._door_cache[start] = (w["x"], w["y"])
                return self.current_map()
        return None

    def _exit_door_down(self, start_map: tuple[int, int],
                        warp_xy: tuple[int, int], tries: int = 4) -> bool:
        """Walk DOWN through the door at `warp_xy` from directly above it.
        Returns True on a map change. Handles: standing on the mat already
        (step up first), a frozen press (dialogue tail - tap B and retry),
        and a dud mat tile (no fire after `tries` -> caller tries the next
        door)."""
        wx, wy = warp_xy
        above = (wx, wy - 1)
        if not self.vision.walkable(*above):
            return False
        for _ in range(tries):
            if self.current_map() != start_map:
                return True
            if self.vision.player_xy() != above:
                # step off the mat if we are on it, then path to `above`
                if self.vision.player_xy() == warp_xy:
                    self.emu.press_direction_settle("UP")
                if self.walk_to(above) == self.WALK_MAP_CHANGED:
                    return True
                if self.vision.player_xy() != above:
                    # a box may be eating the walk - clear it and retry
                    self.emu.tap("B", 5)
                    continue
            self.emu.press_button_held("DOWN", 32)   # step onto the door
            self._tick_until_map_change(start_map, 120)
            if self.current_map() != start_map:
                return True
            self.emu.tap("B", 5)   # clear any dialogue that ate the press
        return False
