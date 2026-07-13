"""GameSense: turns the remembered map into movement.

This is the policy layer over the WorldModel. Each step it:
  1. learns from what just happened — did the last move succeed, hit a wall, or
     change maps (a warp)? — then records the tiles now in view;
  2. decides where to step to explore *systematically*: expand the edge of the
     known map (frontier), so the agent sweeps a room and walks out the door
     instead of bouncing between the same two tiles.

It deliberately avoids re-entering known warps (e.g. the staircase it just came
down), because a door is only discovered by stepping onto an *unknown* tile —
so plain frontier exploration finds the exit on its own.
"""
from __future__ import annotations

import numpy as np

from pokeai.agents.brain.world_model import DELTA, DIRECTIONS, Cell, WorldModel
from pokeai.env.action_controller import Action

Pos = tuple[int, int, int]  # (map, x, y)

_REVERSE = {Action.UP: Action.DOWN, Action.DOWN: Action.UP,
            Action.LEFT: Action.RIGHT, Action.RIGHT: Action.LEFT}
# After crossing into a new map, commit to exploring it for a good while before
# allowing a step back across the seam — otherwise the agent ping-pongs on the
# boundary instead of pushing forward into the new area.
SEAM_BLOCK_STEPS = 40
# After travelling between two maps via a warp (a door/stairs), refuse to make
# the reverse crossing for this many decisions. This is the anti-oscillation
# guard that stops the agent walking in and out of the same building: once it
# leaves a house it won't re-enter for a good while, and vice-versa.
WARP_COOLDOWN_STEPS = 60
# When everything reachable is explored (usually a story gate we can't open yet),
# keep moving and, after this many idle steps, re-test the blocked ways in case
# an errand/event has since opened one — never freeze in place.
REPROBE_STEPS = 80


class GameSense:
    def __init__(self, seed: int = 0) -> None:
        self.world = WorldModel()
        self.rng = np.random.default_rng(seed)
        self._prev: Pos | None = None
        self._prev_action: Action | None = None
        self._entry_warp: dict[int, tuple[int, int]] = {}  # map -> tile we arrived on
        self._warp_dest: dict[tuple[int, int, int], int] = {}  # (map,x,y) -> dest map
        self._visited_maps: set[int] = set()
        self._heading: Action | None = None
        # Control is "confirmed" only once a move actually changes our position
        # or map. Before that we might be in a locked cutscene (Oak's speech)
        # whose brief free-roam gaps look navigable but aren't — so we must not
        # trust a failed move as a wall, and we probe directions to find control.
        self._control = False
        self._probe_i = 0
        # After crossing a map seam: (map, came_from_direction, steps_left).
        self._seam_block: tuple[int, Action, int] | None = None
        # People/objects we've already walked up to and talked to, as (map,x,y).
        # Talking is what triggers the events that open the way onward, so once
        # walking is exhausted the agent seeks out anyone it hasn't spoken to.
        self._interacted: set[Pos] = set()
        # Cooldown per unordered map-pair: while > 0, don't cross a warp between
        # those two maps. Stops in/out-of-building oscillation.
        self._warp_cd: dict[frozenset[int], int] = {}
        # Last seen event-flag count; a rise means an in-game event fired (we
        # made progress), so it's worth re-considering people and doors again.
        self._last_events = -1
        # Dashboard-facing flags: are we hunting for an event (talking to people)
        # or genuinely out of things to do (everything reachable explored)?
        self.seeking_event = False
        self.idle = False
        # How many consecutive steps we've been out of things to do (drives the
        # periodic re-test of blocked paths so the agent never just freezes).
        self._exhausted_steps = 0
        # Plain-language description of the last navigation choice (for the
        # dashboard PLAN line).
        self.last_intent = "getting my bearings"

    def reset(self) -> None:
        """Per-episode reset. Deliberately KEEPS the remembered world map and who
        we've talked to, so the agent doesn't re-explore from scratch every
        episode (a human who's seen the inside of a house doesn't go re-learn
        it). Only the transient per-step bookkeeping is cleared. Use
        full_reset() to forget everything."""
        self._prev = None
        self._prev_action = None
        self._heading = None
        self._control = False
        self._probe_i = 0
        self._seam_block = None
        self.seeking_event = False
        self.idle = False
        self._exhausted_steps = 0

    def full_reset(self) -> None:
        """Forget the entire remembered world (mirrors env.full_reset / a fresh
        playthrough from the title screen)."""
        self.world.reset()
        self._entry_warp.clear()
        self._warp_dest.clear()
        self._visited_maps.clear()
        self._interacted.clear()
        self._warp_cd.clear()
        self._last_events = -1
        self.reset()

    # --- learning from the last move ---

    def perceive(self, state, sem) -> None:
        """Update the map from movement feedback + current vision."""
        cur: Pos = (state.current_map, state.x_pos, state.y_pos)
        # If the last decision was productive (not the idle branch), the agent is
        # making progress again — clear the exhausted timer.
        if not self.idle:
            self._exhausted_steps = 0
        # An in-game event fired since last step (talked to the right person,
        # picked something up): the world may have opened up, so re-consider
        # everyone and every door again.
        if self._last_events >= 0 and state.event_flags_set > self._last_events:
            self.forget_interactions()  # people may have new dialogue now
            self._warp_cd.clear()       # and a blocked door may have opened
        self._last_events = state.event_flags_set
        act = self._prev_action
        if self._prev is not None and act is not None:
            pm, px, py = self._prev
            if cur[0] != pm:
                # Map changed: the tile we stepped toward was a warp, and we
                # arrived somewhere on the new map (remember it as the entry).
                if act in DELTA:
                    dx, dy = DELTA[act]
                    self.world.mark_warp(pm, px, py, act)
                    # Remember where this warp leads, so we don't keep re-entering
                    # dead-end maps we've already explored.
                    self._warp_dest[(pm, px + dx, py + dy)] = cur[0]
                    # Don't immediately step back across the seam we just crossed.
                    self._seam_block = (cur[0], _REVERSE[act], SEAM_BLOCK_STEPS)
                # Forbid re-crossing between these two maps for a while — this is
                # what breaks the walk-in/walk-out-of-the-building loop.
                self._warp_cd[frozenset((pm, cur[0]))] = WARP_COOLDOWN_STEPS
                self._entry_warp[cur[0]] = (cur[1], cur[2])
                self._visited_maps.add(cur[0])
                self._control = True  # moving through a door proves control
            elif act in DELTA:
                dx, dy = DELTA[act]
                moved = (cur[1], cur[2]) != (px, py)
                reached = (cur[1], cur[2]) == (px + dx, py + dy)
                if moved:
                    self._control = True  # any movement proves we have control
                # Judge by the *intended* tile, not just "did we move at all".
                # Gen 1 can resolve a blocked press as a sideways slip, so a move
                # that didn't land on the tile we aimed at means that tile is a
                # wall — otherwise the agent presses into it forever.
                if not reached and self._control:
                    self.world.mark_blocked(pm, px, py, act)
        self.world.observe(state.current_map, state.x_pos, state.y_pos, sem)

    def note_action(self, state, action: int) -> None:
        """Record the move we are about to make, for next step's feedback."""
        self._prev = (state.current_map, state.x_pos, state.y_pos)
        self._prev_action = Action(action) if action in [int(d) for d in DIRECTIONS] else None

    # --- deciding where to go ---

    def explore_action(self, state) -> Action | None:
        """Next step for systematic exploration of the current map. Returns None
        only if the agent is fully boxed in by walls (caller falls back).

        Priority: (0) find control, (1) grow the map at the frontier, (2) route
        to a frontier, (3) take a door toward somewhere still worth exploring,
        (4) go talk to someone we haven't met, (5) take a door toward someone new
        elsewhere, (6) idle calmly rather than pace in and out of the same door.
        Steps 3 and 5 are the *only* places the agent uses a warp, and both
        refuse exhausted destinations and recently-crossed map pairs — that is
        what stops the in/out-of-building loop."""
        m, x, y = state.current_map, state.x_pos, state.y_pos
        entry = self._entry_warp.get(m)
        self.seeking_event = False
        self.idle = False
        self._tick_cooldowns()

        # 0) Control not yet confirmed: we may be in a locked cutscene whose
        # free-roam gaps look navigable. Rotate through directions to probe for
        # control (the first one that moves us flips _control on); don't rely on
        # the half-built map yet.
        if not self._control:
            self.last_intent = "feeling out the controls"
            d = DIRECTIONS[self._probe_i % len(DIRECTIONS)]
            self._probe_i += 1
            return d

        # Just crossed a map seam? Don't immediately step back across it (the
        # boundary is several tiles wide, so we'd otherwise ping-pong on it).
        avoid: Action | None = None
        if self._seam_block is not None:
            sm, sdir, left = self._seam_block
            if sm == m and left > 0:
                avoid = sdir
                self._seam_block = (sm, sdir, left - 1)
            else:
                self._seam_block = None

        # 1) Standing on the frontier: step straight into an unknown tile to grow
        # the map. Don't deliberately re-enter the warp we came in by.
        unknown = []
        for action in DIRECTIONS:
            if action == avoid:
                continue
            dx, dy = DELTA[action]
            nx, ny = x + dx, y + dy
            if self.world.cell(m, nx, ny) == Cell.UNKNOWN and (nx, ny) != entry:
                unknown.append(action)
        if unknown:
            self.last_intent = "mapping new ground"
            # Prefer keeping the current heading (smooth, human-looking sweep).
            if self._heading in unknown:
                return self._heading
            self._heading = Action(int(self.rng.choice([int(a) for a in unknown])))
            return self._heading

        # 2) Route to the nearest frontier tile elsewhere on the known map.
        path = self.world.path_to_frontier(m, x, y)
        if path and path[0] != avoid:
            self.last_intent = "heading for unexplored ground"
            self._heading = path[0]
            return path[0]

        # 3) This map is fully mapped: take a warp toward a destination that
        # still has unexplored ground (or that we've never been to). Exhausted
        # destinations and recently-crossed map pairs are skipped.
        warp = self._best_warp(m, x, y, entry, avoid, want="frontier")
        if warp:
            self.last_intent = "heading for the way onward"
            self._heading = warp[0]
            return warp[0]

        # Purge phantom/stale NPCs: a real adjacent NPC is talked to by the
        # caller *before* this runs, so any un-met NPC we're standing next to here
        # couldn't actually be talked to (it walked off, or it was furniture/our
        # own reflection misread as a person). Drop it so we don't circle an empty
        # tile forever — this is what was trapping it in Red's House.
        met = self._interacted_on(m)
        for (npx, npy) in self.world.npc_tiles(m):
            if (npx, npy) not in met and abs(npx - x) + abs(npy - y) == 1:
                self.mark_interacted(m, npx, npy)

        # 4) Nothing left to map here: progress is gated behind an in-game event,
        # so go talk to a person/object we haven't dealt with yet.
        npc = self.world.path_to_adjacent_npc(m, x, y, exclude=self._interacted_on(m))
        if npc and npc[0] != avoid:
            self.seeking_event = True
            self.last_intent = "going to talk to someone"
            self._heading = npc[0]
            return npc[0]

        # 5) Everyone here has been spoken to — take a warp toward a map that
        # still has someone new to talk to.
        warp = self._best_warp(m, x, y, entry, avoid, want="npc")
        if warp:
            self.seeking_event = True
            self.last_intent = "heading somewhere I can still talk to people"
            self._heading = warp[0]
            return warp[0]

        # 6) Genuinely out of things to do reachable on foot — almost always a
        # story gate we can't open yet (e.g. an NPC blocking the way until an
        # errand is done). DON'T freeze: keep pacing the area, and every so often
        # re-test the blocked ways in case one has since opened.
        self.idle = True
        self._exhausted_steps += 1
        if self._exhausted_steps >= REPROBE_STEPS:
            self._exhausted_steps = 0
            self._reprobe(m)  # re-open blocked tiles so we walk up and re-try them
            self.last_intent = "going back to check if the way ahead has opened"
        else:
            self.last_intent = "looking for another way around"
        # Keep moving. Prefer open ground (not doors, so we don't loop in and out
        # of a building); allow a door only if there's truly nowhere else to step.
        for include_warps in (False, True):
            walkable = self.world.walkable_dirs(m, x, y, include_warps=include_warps)
            choices = [d for d in walkable if d != avoid] or walkable
            if choices:
                self._heading = Action(int(self.rng.choice([int(a) for a in choices])))
                return self._heading
        return int(Action.NOOP)  # boxed in on all sides (shouldn't normally happen)

    def _reprobe(self, m: int) -> None:
        """Re-test the things we'd written off on this map: forget WALL tiles
        (a blocked path may have opened after an errand), and clear who we've
        spoken to + cooldowns touching this map (people may have new dialogue,
        and a door may now lead somewhere new). FLOOR/GRASS/WARP/NPC knowledge is
        kept — only the "no" facts are re-tested, so the agent walks back up to a
        gate and tries again instead of sitting still forever."""
        grid = self.world.maps.get(m, {})
        for xy in [xy for xy, c in grid.items() if c == Cell.WALL]:
            del grid[xy]  # back to UNKNOWN -> a frontier to re-sweep and re-bump
        self._interacted = {p for p in self._interacted if p[0] != m}
        self._warp_cd = {pair: v for pair, v in self._warp_cd.items() if m not in pair}

    # --- warp choice + exhaustion (anti-loop) ---

    def _best_warp(
        self, m: int, x: int, y: int, entry, avoid, *, want: str
    ) -> list[Action] | None:
        """Shortest path to a warp worth taking. `want="frontier"` seeks a
        destination with unexplored ground (or never visited); `want="npc"`
        seeks one with someone still un-talked-to. Skips the warp we came in by,
        map-pairs on cooldown, and exhausted destinations."""
        best_path: list[Action] | None = None
        best_score = 0
        for (wx, wy) in self.world.warp_tiles(m):
            if (wx, wy) == entry:
                continue
            dest = self._warp_dest.get((m, wx, wy))
            # Don't re-cross a map pair we just used (anti-oscillation).
            if dest is not None and self._warp_cd.get(frozenset((m, dest)), 0) > 0:
                continue
            if want == "frontier":
                if dest is None or dest not in self._visited_maps:
                    score = 2  # unknown / unvisited — most promising
                elif self._is_dead_end(dest):
                    continue  # a one-door building we've already been in — skip
                elif self.world.has_frontier(dest):
                    score = 1  # been there, still ground left
                else:
                    continue  # fully explored — not worth re-entering
            else:  # want == "npc"
                if dest is None or self._uninteracted_npc_count(dest) > 0:
                    score = 1
                else:
                    continue
            if score < best_score:
                continue
            p = self.world.path_to(m, x, y, wx, wy)
            if p and p[0] != avoid and (
                score > best_score or best_path is None or len(p) < len(best_path)
            ):
                best_score, best_path = score, p
        return best_path

    def _is_dead_end(self, dest: int) -> bool:
        """A visited map whose only way out is the door we came in by — i.e. a
        single-exit building. Once we've been inside, don't keep routing back in
        to chase leftover interior frontier; push onward through the world
        instead. (Maps with multiple exits — routes, towns, multi-floor buildings
        — are not treated as dead ends.)"""
        return dest in self._visited_maps and len(self.world.warp_tiles(dest)) <= 1

    def _tick_cooldowns(self) -> None:
        for pair in list(self._warp_cd):
            self._warp_cd[pair] -= 1
            if self._warp_cd[pair] <= 0:
                del self._warp_cd[pair]

    def _interacted_on(self, m: int) -> set[tuple[int, int]]:
        return {(px, py) for (pm, px, py) in self._interacted if pm == m}

    def _uninteracted_npc_count(self, m: int) -> int:
        seen = self._interacted_on(m)
        return sum(1 for xy in self.world.npc_tiles(m) if xy not in seen)

    def _map_exhausted(self, m: int) -> bool:
        """True when a map has no unexplored ground left AND nobody new to talk
        to — there is nothing more to gain by walking around it."""
        return not self.world.has_frontier(m) and self._uninteracted_npc_count(m) == 0

    def _all_reachable_exhausted(self, m: int) -> bool:
        """The current map is exhausted and every door off it leads to a map that
        is exhausted too — so walking can't make progress; an event must."""
        if not self._map_exhausted(m):
            return False
        for (wx, wy) in self.world.warp_tiles(m):
            dest = self._warp_dest.get((m, wx, wy))
            if dest is None or not self._map_exhausted(dest):
                return False
        return True

    def route_toward_map(self, cur_map: int, x: int, y: int, target_map: int) -> Action | None:
        """First step toward a (possibly distant) target map, hopping across the
        warps we've learned connect maps. None if we're already there or no known
        route exists yet. This is what lets a goal like 'go heal at the Viridian
        Center' actually walk there from another map."""
        if cur_map == target_map:
            return None
        # Map adjacency + which warp tiles on each map lead where (learned).
        adj: dict[int, set[int]] = {}
        warp_on: dict[tuple[int, int], list[tuple[int, int]]] = {}
        for (m, wx, wy), dest in self._warp_dest.items():
            adj.setdefault(m, set()).add(dest)
            warp_on.setdefault((m, dest), []).append((wx, wy))

        # BFS over the map graph for the shortest chain of maps to the target.
        from collections import deque
        prev: dict[int, int | None] = {cur_map: None}
        q: deque[int] = deque([cur_map])
        while q:
            m = q.popleft()
            if m == target_map:
                break
            for nxt in adj.get(m, ()):  # sorted for determinism
                if nxt not in prev:
                    prev[nxt] = m
                    q.append(nxt)
        if target_map not in prev:
            return None
        # Walk the chain back to the first hop off the current map.
        node = target_map
        while prev[node] != cur_map:
            node = prev[node]  # type: ignore[assignment]
            if node is None:
                return None
        next_map = node
        # Route within the current map to a warp tile that leads to that next map.
        for (wx, wy) in warp_on.get((cur_map, next_map), []):
            path = self.world.path_to(cur_map, x, y, wx, wy)
            if path:
                return path[0]
        return None

    def mark_interacted(self, m: int, x: int, y: int) -> None:
        """Record that we've talked to the person/object at this tile, so the
        agent moves on instead of pestering it forever (until an event reopens
        the world, which clears these)."""
        self._interacted.add((m, x, y))

    def forget_interactions(self) -> None:
        """Forget who we've talked to, so we re-engage everyone. Used while stuck
        at a gate, because an NPC's dialogue changes as a fetch-quest progresses
        (the clerk hands over the parcel; Oak then takes it)."""
        self._interacted.clear()

    def maps_with_unmet_npcs(self) -> list[int]:
        """Remembered maps that still have a person/object we haven't talked to —
        the places worth travelling to when we're trying to unblock the way on."""
        return [m for m in self.world.maps if self._uninteracted_npc_count(m) > 0]

    # --- dashboard introspection ---

    def known_tiles(self, map_id: int) -> int:
        return self.world.known_count(map_id)
