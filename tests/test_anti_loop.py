"""Tests for the GameSense anti-loop behaviour: don't walk in and out of a
building forever, keep the remembered world across episodes, seek out people to
talk to when walking is exhausted, and idle calmly when truly stuck."""
from __future__ import annotations

import types

import numpy as np

from pokeai.agents.brain.gamesense import REPROBE_STEPS, WARP_COOLDOWN_STEPS, GameSense
from pokeai.agents.brain.world_model import Cell
from pokeai.emulator.screen_reader import TileClass
from pokeai.env.action_controller import Action


def _st(m, x, y, events=0):
    return types.SimpleNamespace(current_map=m, x_pos=x, y_pos=y, event_flags_set=events)


def _sem_walkable() -> np.ndarray:
    g = np.full((18, 20), int(TileClass.WALKABLE), dtype=np.int8)
    for r in (8, 9):
        for c in (8, 9):
            g[r, c] = int(TileClass.PLAYER)
    return g


def _boxed_room(wm, m, fx, fy, warp_dir=None):
    """One floor tile walled in on all sides; optionally one wall is a door."""
    wm.mark_floor(m, fx, fy)
    for d in (Action.UP, Action.DOWN, Action.LEFT, Action.RIGHT):
        wm.mark_blocked(m, fx, fy, d)
    if warp_dir is not None:
        wm.mark_warp(m, fx, fy, warp_dir)  # overwrites that wall with a door


def test_exhausted_world_paces_ground_not_the_door():
    """Everything reachable is explored. The agent keeps moving on open ground —
    it must NOT freeze, and must NOT step back through the door (no in/out loop)."""
    gs = GameSense(seed=1)
    wm = gs.world
    for x in (4, 5, 6):                       # a small walled-in strip of floor
        wm.mark_floor(0, x, 5)
        wm.mark_blocked(0, x, 5, Action.UP)
        wm.mark_blocked(0, x, 5, Action.DOWN)
    wm.mark_blocked(0, 4, 5, Action.LEFT)     # west wall
    wm.mark_warp(0, 6, 5, Action.RIGHT)       # a door at the east end
    _boxed_room(wm, 1, 5, 5)                   # the room behind it, also explored
    gs._warp_dest[(0, 7, 5)] = 1
    gs._visited_maps = {0, 1}
    gs._control = True

    assert gs._all_reachable_exhausted(0)
    # Standing right next to the door, it steps back onto open ground, not through
    # the door — and does not freeze.
    action = gs.explore_action(_st(0, 6, 5))
    assert action == int(Action.LEFT)
    assert action != int(Action.NOOP)
    assert gs.idle


def test_exhausted_agent_reprobes_instead_of_freezing():
    """A story gate it can't open yet (modelled as a wall on every side): the
    agent doesn't sit frozen — after a while it re-probes, reopening the blocked
    tiles so it walks back up and re-tests them (catching a gate that has since
    opened)."""
    gs = GameSense(seed=1)
    _boxed_room(gs.world, 0, 5, 5)  # one floor tile, walled in on all sides
    gs._control = True

    assert gs.explore_action(_st(0, 5, 5)) is not None
    assert gs.idle  # nothing to do right now...
    for _ in range(REPROBE_STEPS + 2):
        gs.explore_action(_st(0, 5, 5))
    # ...but a re-probe has reopened the walls, so it's back to mapping, not stuck.
    assert gs.world.cell(0, 5, 4) == Cell.UNKNOWN
    assert gs.idle is False


def test_reprobe_reopens_blocked_paths():
    gs = GameSense(seed=1)
    wm = gs.world
    wm.mark_floor(0, 5, 5)
    wm.mark_blocked(0, 5, 5, Action.UP)   # a 'wall' to the north (e.g. the old man)
    gs.mark_interacted(0, 5, 4)
    gs._warp_cd[frozenset((0, 9))] = 30
    assert wm.cell(0, 5, 4) == Cell.WALL

    gs._reprobe(0)
    assert wm.cell(0, 5, 4) == Cell.UNKNOWN       # re-test the block next time we pass
    assert (5, 4) not in gs._interacted_on(0)     # re-talk to people on this map
    assert not gs._warp_cd                         # cooldowns touching map 0 cleared


def test_warp_cooldown_blocks_immediate_recrossing():
    """Right after crossing between two maps, the reverse crossing is refused for
    a while — the core fix for in/out-of-building oscillation."""
    gs = GameSense(seed=1)
    gs.world.mark_floor(0, 5, 5)
    gs.world.mark_warp(0, 5, 5, Action.UP)  # door at (5,4) -> map 1
    gs.world.mark_floor(1, 3, 3)            # map 1 still has unexplored ground
    gs.world._set(1, 0, 0, Cell.WARP)       # map 1 has multiple exits (a route, not
    gs.world._set(1, 9, 9, Cell.WARP)       # a one-door dead-end building)
    gs._warp_dest[(0, 5, 4)] = 1
    gs._visited_maps = {0, 1}
    gs._control = True

    # Normally the door is worth taking (house still has frontier).
    assert gs._best_warp(0, 5, 5, None, None, want="frontier") == [Action.UP]
    # But not while the {town, house} pair is on cooldown.
    gs._warp_cd[frozenset((0, 1))] = WARP_COOLDOWN_STEPS
    assert gs._best_warp(0, 5, 5, None, None, want="frontier") is None


def test_visited_one_door_building_is_not_re_entered():
    """A visited single-exit building (one warp) is a dead end — the explorer
    won't keep routing back into it; it pushes onward instead."""
    gs = GameSense(seed=1)
    gs.world.mark_floor(0, 5, 5)
    gs.world.mark_warp(0, 5, 5, Action.UP)     # door at (5,4) -> map 1 (a house)
    gs.world.mark_floor(1, 3, 3)               # house has leftover interior frontier
    gs.world._set(1, 7, 7, Cell.WARP)          # the house's single door (back out)
    gs._warp_dest[(0, 5, 4)] = 1
    gs._visited_maps = {0, 1}
    gs._control = True
    assert gs._is_dead_end(1) is True
    # No frontier warp worth taking -> won't route back into the explored house.
    assert gs._best_warp(0, 5, 5, None, None, want="frontier") is None


def test_crossing_a_map_sets_a_cooldown():
    gs = GameSense(seed=1)
    gs._last_events = 0
    # Pretend we just stepped UP from map 0 (5,5) and arrived on map 1.
    gs._prev = (0, 5, 5)
    gs._prev_action = Action.UP
    gs.perceive(_st(1, 5, 9), _sem_walkable())
    assert gs._warp_cd.get(frozenset((0, 1)), 0) == WARP_COOLDOWN_STEPS


def test_reset_keeps_world_but_full_reset_wipes_it():
    gs = GameSense(seed=1)
    gs.world.mark_floor(0, 5, 5)
    gs._visited_maps.add(0)
    gs.mark_interacted(0, 1, 1)

    gs.reset()  # per-episode: memory survives (no re-exploring from scratch)
    assert gs.world.cell(0, 5, 5) == Cell.FLOOR
    assert 0 in gs._visited_maps
    assert (1, 1) in gs._interacted_on(0)

    gs.full_reset()  # new playthrough: forget everything
    assert gs.world.cell(0, 5, 5) == Cell.UNKNOWN
    assert not gs._visited_maps
    assert gs._uninteracted_npc_count(0) == 0


def test_event_progress_reopens_people_and_doors():
    """When an in-game event fires (event flags rise), the agent re-considers
    everyone it had talked to and every door it had on cooldown."""
    gs = GameSense(seed=1)
    gs._last_events = 5
    gs.mark_interacted(0, 1, 1)
    gs._warp_cd[frozenset((0, 1))] = 30

    gs.perceive(_st(0, 5, 5, events=6), _sem_walkable())  # an event fired
    assert (1, 1) not in gs._interacted_on(0)
    assert not gs._warp_cd


def test_routes_to_an_unmet_npc_when_walking_is_exhausted():
    """Map fully mapped but someone hasn't been spoken to: head over to them and
    flag that we're hunting for the event that unblocks progress."""
    gs = GameSense(seed=1)
    # A corridor with a person at the end; everything else known.
    for x in range(5, 8):
        gs.world.mark_floor(0, x, 5)
    gs.world._set(0, 8, 5, Cell.NPC)
    for x in range(5, 8):
        for d in (Action.UP, Action.DOWN):
            gs.world.mark_blocked(0, x, 5, d)
    gs.world.mark_blocked(0, 5, 5, Action.LEFT)
    gs._control = True

    action = gs.explore_action(_st(0, 5, 5))
    assert action == Action.RIGHT
    assert gs.seeking_event
