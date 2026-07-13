"""ROM-free fact-gate tests for agents/story_part3.py (run_part3).

Everything drives injected fakes — no emulator, no bridge. The tests pin
the FACT-GATING contract (badge flag completes the whole part; map facts
skip legs) and the port fidelity of the pure pieces (_northmost pick,
_flood_north's lateral tiebreak + ledge hops, the blackout/battle branches
of the travel loop with journey.warp_exit stubbed out).
"""
from __future__ import annotations

from types import SimpleNamespace

import pokeai.agents.story_part3 as sp3
from pokeai.agents.story_part3 import (
    FLAG_BADGE01,
    FOREST,
    GYM,
    PEWTER,
    ROUTE2,
    _ALL_TASKS,
    _flood_north,
    _northmost,
    run_part3,
)

GYM_DOOR = {"x": 36, "y": 15, "destGroup": GYM[0], "destMap": GYM[1]}


# --------------------------------------------------------------------------
# fakes
# --------------------------------------------------------------------------

class Hooks:
    def __init__(self):
        self.phases: list[tuple[str, str]] = []
        self.done: list[str] = []

    def phase(self, task_id, action):
        self.phases.append((task_id, action))

    def done_task(self, task_id):
        self.done.append(task_id)


class FakeBridge:
    def __init__(self):
        self.log: list[tuple] = []
        self.xy = (4, 4)

    def player_xy(self):
        return self.xy

    def press_direction_settle(self, d):
        self.log.append(("settle", d))
        return False

    def press_button_held(self, btn, frames):
        self.log.append(("held", btn, frames))

    def tap(self, btn, frames=6):
        self.log.append(("tap", btn, frames))


class FakeReader:
    """read_flag over a mutable flag set; read() pops a scripted queue of
    all_party_fainted values (default False once exhausted)."""

    def __init__(self, flags=(), fainted=()):
        self.flags = set(flags)
        self.fainted = list(fainted)

    def read_flag(self, flag_id):
        return flag_id in self.flags

    def read(self):
        fainted = self.fainted.pop(0) if self.fainted else False
        return SimpleNamespace(all_party_fainted=fainted)


class FakeVision:
    def __init__(self, nav):
        self.nav = nav

    def player_xy(self):
        return self.nav.b.xy

    def object_tiles(self):
        return set(self.nav.npcs.get(self.nav.map, ()))

    def nav_grid(self):
        return {"walk": set(), "w": 15, "h": 10, "ledge_dir": {}}

    def walkable(self, x, y, layout=None):
        return True


class FakeNav:
    def __init__(self, b, start, warps=None, npcs=None):
        self.b = b
        self.map = start
        self.warps = warps or {}      # map id -> [warp dicts]
        self.npcs = npcs or {}        # map id -> [npc tiles]
        self.vision = FakeVision(self)
        self.calls: list[tuple] = []

    def current_map(self):
        return self.map

    def map_warps_full(self):
        return list(self.warps.get(self.map, ()))

    def go_to(self, target, attempts=10):
        self.calls.append(("go_to", target))
        return True

    def take_warp(self, warp_xy):
        self.calls.append(("take_warp", tuple(warp_xy)))
        for w in self.warps.get(self.map, ()):
            if (w["x"], w["y"]) == tuple(warp_xy):
                self.map = (w["destGroup"], w["destMap"])
                return self.map
        return None

    def leave_building(self):
        self.calls.append(("leave_building",))
        self.map = PEWTER
        return self.map

    def plan(self, target, **kw):
        return None

    def walk_path(self, path):
        return True


class FakeOverworld:
    """interact() flips the injected battle active (the leader challenge)."""

    def __init__(self, battle=None):
        self.battle = battle
        self.interactions: list = []

    def wait_control(self, timeout=25.0, confirm=2):
        return True

    def interact(self, target, rounds=6):
        self.interactions.append(target)
        if self.battle is not None:
            self.battle.active_now = True
        return True


class FakeBattle:
    """fight_smart pops (verdict, sets_badge) pairs and records turn_cap."""

    def __init__(self, reader, script=()):
        self.reader = reader
        self.script = list(script)
        self.active_now = False
        self.rideouts: list[tuple] = []
        self.fights: list[int] = []

    def active(self):
        return self.active_now

    def is_trainer_battle(self):
        return True

    def ride_out_end(self, button="B", cap=40):
        self.rideouts.append((button, cap))
        return True

    def fight_smart(self, narrate=None, turn_cap=30):
        verdict, badge = self.script.pop(0) if self.script else ("win", True)
        self.fights.append(turn_cap)
        self.active_now = False
        if badge:
            self.reader.flags.add(FLAG_BADGE01)
        return verdict


class FakeCatch:
    def __init__(self, battle):
        self.battle = battle
        self.lead_faint_rides = 0

    def confirm_real_battle(self, max_tries=8, assume_locked=False):
        return self.battle.active()

    def _ride_out_lead_faint(self):
        self.lead_faint_rides += 1


class FakeServices:
    def __init__(self, ok=True):
        self.ok = ok
        self.heals: list = []

    def heal_at_center(self, city_map=None):
        self.heals.append(city_map)
        return self.ok


class FakePolicy:
    def __init__(self, results=()):
        self.results = list(results)
        self.calls = 0

    def handle(self, assume_locked=False):
        self.calls += 1
        return self.results.pop(0) if self.results else None


def make_world(start, *, flags=(), fainted=(), fights=(), heal_ok=True,
               warps=None, npcs=None, policy_results=()):
    b = FakeBridge()
    reader = FakeReader(flags=flags, fainted=fainted)
    nav = FakeNav(b, start, warps=warps, npcs=npcs)
    battle = FakeBattle(reader, script=fights)
    return {
        "b": b, "reader": reader, "nav": nav,
        "ow": FakeOverworld(battle), "svc": FakeServices(ok=heal_ok),
        "battle": battle, "catch": FakeCatch(battle),
        "policy": FakePolicy(policy_results),
    }


def gym_world(start=GYM, **kw):
    """A world where the gym is enterable and one interact beats Brock."""
    kw.setdefault("warps", {PEWTER: [dict(GYM_DOOR)]})
    kw.setdefault("npcs", {GYM: [(4, 2)]})       # player (4,4): adjacent
    kw.setdefault("fights", [("win", True)])
    return make_world(start, **kw)


# --------------------------------------------------------------------------
# fact gates
# --------------------------------------------------------------------------

def test_badge_flag_completes_whole_part_without_touching_the_game():
    w = make_world((3, 1), flags={FLAG_BADGE01})   # starting back in Viridian
    hooks = Hooks()
    assert run_part3(**w, hooks=hooks) is True
    assert hooks.done == list(_ALL_TASKS)          # every task rolled off
    assert w["b"].log == []                        # no buttons pressed
    assert w["svc"].heals == []                    # no heal detour
    assert w["policy"].calls == 0                  # no battles handled


def test_start_inside_gym_skips_travel_and_heal():
    w = gym_world()
    hooks = Hooks()
    assert run_part3(**w, hooks=hooks) is True
    assert w["svc"].heals == []                    # map fact skipped the heal
    assert w["policy"].calls == 0                  # travel loop never ran
    assert w["ow"].interactions == [(4, 2)]        # challenged the top NPC
    assert w["battle"].fights == [60]              # Brock turn_cap preserved
    for tid in _ALL_TASKS:
        assert tid in hooks.done
    # travel legs were finished by the map fact BEFORE the gym gauntlet
    assert hooks.done.index("p3_pewter") < hooks.done.index("brock")


def test_start_in_pewter_skips_travel_but_heals_and_enters_gym():
    w = gym_world(start=PEWTER)
    hooks = Hooks()
    assert run_part3(**w, hooks=hooks) is True
    assert w["policy"].calls == 0                  # no forest journey
    assert w["svc"].heals == [PEWTER]              # CENTERS-row heal used
    assert ("take_warp", (GYM_DOOR["x"], GYM_DOOR["y"])) in w["nav"].calls
    assert hooks.done.index("p3_pewter") < hooks.done.index("p3_heal")
    assert "brock" in hooks.done


def test_aisle_trainer_win_marks_p3_trainer_before_brock():
    # two gym fights: the aisle trainer (no badge), then Brock (badge)
    w = gym_world(fights=[("win", False), ("win", True)])
    # after the first win the walker re-approaches: needs a second interact
    hooks = Hooks()
    assert run_part3(**w, hooks=hooks) is True
    assert w["battle"].fights == [60, 60]
    assert hooks.done.index("p3_trainer") < hooks.done.index("brock")


# --------------------------------------------------------------------------
# travel leg (warp_exit stubbed at the module seam)
# --------------------------------------------------------------------------

def test_travel_leg_blackout_battle_then_warp_to_pewter(monkeypatch):
    w = gym_world(start=FOREST, fainted=[True],
                  policy_results=["wild:fled"])
    warp_calls = []

    def fake_warp_exit(b, nav, ow, pick, narrate=None):
        warp_calls.append(pick)
        nav.map = PEWTER                 # the north gate chain, collapsed
        return True

    monkeypatch.setattr(sp3, "warp_exit", fake_warp_exit)
    hooks = Hooks()
    assert run_part3(**w, hooks=hooks) is True
    # blackout rode the whiteout out on A (the recovery path, not a failure)
    assert w["battle"].rideouts[0] == ("A", 80)
    assert w["policy"].calls >= 1                  # the wild was policy-handled
    assert warp_calls and warp_calls[0] is sp3._northmost
    assert hooks.done.index("p3_route2") < hooks.done.index("p3_forest")
    assert w["svc"].heals == [PEWTER]


def test_travel_timeout_fails_part_with_route2_fact_kept():
    w = make_world(ROUTE2)
    hooks = Hooks()
    assert run_part3(**w, hooks=hooks, travel_budget=0.05) is False
    assert "p3_route2" in hooks.done               # map fact still recorded
    assert "p3_pewter" not in hooks.done
    assert w["catch"].lead_faint_rides >= 1        # wedge breaker engaged


# --------------------------------------------------------------------------
# heal + gym legs
# --------------------------------------------------------------------------

def test_heal_failure_is_not_fatal():
    w = gym_world(start=PEWTER, heal_ok=False)
    hooks = Hooks()
    assert run_part3(**w, hooks=hooks) is True
    assert "p3_heal" not in hooks.done             # left honestly pending
    assert "brock" in hooks.done


def test_missing_gym_door_fails_before_the_gauntlet():
    w = make_world(PEWTER, warps={})               # no doors at all
    hooks = Hooks()
    assert run_part3(**w, hooks=hooks) is False
    assert "p3_gym" not in hooks.done
    assert "brock" not in hooks.done


def test_gym_budget_exhausted_without_badge_fails():
    w = make_world(GYM, npcs={GYM: []})            # nobody to challenge
    hooks = Hooks()
    assert run_part3(**w, hooks=hooks, gym_budget=0.0) is False
    assert "brock" not in hooks.done


# --------------------------------------------------------------------------
# pure port fidelity
# --------------------------------------------------------------------------

def test_northmost_pick_is_min_y_then_min_x():
    warps = [{"x": 5, "y": 8}, {"x": 7, "y": 1}, {"x": 2, "y": 1}]
    assert _northmost(warps) == {"x": 2, "y": 1}


class GridVision:
    def __init__(self, walk, start, ledges=None, objects=()):
        self.walk = set(walk)
        self.start = start
        self.ledges = dict(ledges or {})
        self.objects = set(objects)

    def nav_grid(self):
        return {"walk": set(self.walk), "ledge_dir": dict(self.ledges),
                "w": 10, "h": 10}

    def object_tiles(self):
        return set(self.objects)

    def player_xy(self):
        return self.start


def _grid_nav(**kw):
    return SimpleNamespace(vision=GridVision(**kw))


def test_flood_north_prefers_north_then_players_column():
    nav = _grid_nav(walk={(2, 3), (1, 2), (2, 2), (3, 2)}, start=(2, 3))
    assert _flood_north(nav) == (2, 2)             # lateral tiebreak preserved


def test_flood_north_hops_ledges_and_respects_npc_blocks():
    nav = _grid_nav(walk={(2, 3), (2, 1)}, start=(2, 3),
                    ledges={(2, 2): "up"})
    assert _flood_north(nav) == (2, 1)             # ledge-hop lands past the lip
    nav = _grid_nav(walk={(2, 3), (2, 2)}, start=(2, 3), objects={(2, 2)})
    assert _flood_north(nav) is None               # NPC tile is not progress


def test_flood_north_returns_none_when_walled():
    assert _flood_north(_grid_nav(walk={(2, 3)}, start=(2, 3))) is None
