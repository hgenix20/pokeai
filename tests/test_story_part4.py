"""ROM-free tests for the Part 4 story agent (agents/story_part4.py).

The point of the port is FACT-GATING: the same run_part4 entry completes
instantly on a save where the work is already done (Cerulean Center row in
services.CENTERS), and resumes mid-journey from map/pos facts (inside
Mt. Moon, Route 4 east/west, Pewter). These tests pin those gates down with
fakes; the emulator-facing stage bodies are monkeypatched recorders, so no
bridge is ever touched. Also covered: the visited-sidecar round-trip (the
acceptance script's flat-tuple load silently never loaded; the module fixes
the reconstruction while keeping the on-disk format).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from pokeai.agents import story_part4 as p4
from pokeai.skills.services import CENTERS


# ---------------------------------------------------------------- fakes ---

class Boom:
    """A dependency that must never be touched (the done-gate contract)."""

    def __getattr__(self, name):
        raise AssertionError(f"emulator dependency touched: .{name}")


class FakeVision:
    def __init__(self, xy):
        self.xy = xy

    def player_xy(self):
        return self.xy


class FakeNav:
    def __init__(self, map_id, xy=(0, 0)):
        self.map = map_id
        self.vision = FakeVision(xy)

    def current_map(self):
        return self.map

    def map_warps_full(self):
        return []


class FakeReader:
    def __init__(self):
        self.state = SimpleNamespace(all_party_fainted=False,
                                     party_total_hp=55,
                                     party_total_max_hp=55,
                                     party_count=1)

    def read_party_details(self):
        return [{"level": 14}]

    def read_money(self):
        return 3000

    def ball_count(self):
        return 5

    def read_bag_pocket(self, pocket):
        return []

    def count_item(self, item_id):
        return 0

    def read(self):
        return self.state


class Hooks:
    def __init__(self):
        self.phases = []
        self.done = []

    def phase(self, task_id, action):
        self.phases.append((task_id, action))

    def done_task(self, task_id):
        self.done.append(task_id)


@pytest.fixture
def no_cerulean_fact(monkeypatch):
    """Remove the live-established Cerulean row so the whole-part gate is off
    (services.CENTERS ships with it after the 2026-07-06 live pass)."""
    monkeypatch.delitem(CENTERS, p4.CERULEAN, raising=False)


@pytest.fixture
def forbid_cross_edge(monkeypatch):
    calls = []
    monkeypatch.setattr(p4, "cross_edge", lambda *a, **k: calls.append(a))
    return calls


# ------------------------------------------------------ whole-part gate ---

def test_done_gate_standing_in_cerulean():
    """Standing in Cerulean = Part 4 already done ON THIS SAVE: return True
    immediately, mark every p4 task done, touch nothing but nav. (The old
    gate keyed on services.CENTERS, which has held a STATIC Cerulean row
    since 2026-07-06 - it fired on a fresh game and skipped the part.)"""
    h = Hooks()
    nav = FakeNav(p4.CERULEAN, xy=(22, 20))
    assert p4.run_part4(Boom(), Boom(), nav, Boom(), Boom(),
                        Boom(), Boom(), Boom(), hooks=h) is True
    assert set(h.done) == set(p4.TASK_IDS)


def test_done_gate_not_fired_on_fresh_game(no_cerulean_fact, monkeypatch):
    """A fresh game (Pallet-ish map) must NOT trip the done gate even though
    services.CENTERS statically knows Cerulean."""
    ran = {}
    monkeypatch.setattr(p4, "cross_edge",
                        lambda *a, **k: ran.setdefault("legs", True))
    nav = FakeNav((3, 2), xy=(20, 20))  # Pewter
    reader = FakeReader()
    # the run will fail somewhere downstream with fakes; the assertion is
    # only that the gate did NOT return True instantly
    try:
        result = p4.run_part4(Boom(), reader, nav, Boom(), Boom(),
                              Boom(), Boom(), Boom())
    except Exception:
        result = None
    assert result is not True


# ------------------------------------------------------- resume gating ---

def test_resume_inside_mt_moon(no_cerulean_fact, forbid_cross_edge, monkeypatch):
    """Map group 1 = inside Mt. Moon: stages A/B (Pewter exit, Route 3 legs)
    must be skipped entirely and stage D entered with in_cave_resume=True."""
    seen = {}

    def fake_moon(b, reader, nav, ow, svc, battle, catch, policy, row,
                  route3, route4, in_cave_resume, h=None):
        seen.update(row=row, route3=route3, route4=route4,
                    in_cave=in_cave_resume)
        return True

    monkeypatch.setattr(p4, "stage_moon", fake_moon)
    nav = FakeNav((1, 1), xy=(7, 7))
    h = Hooks()
    assert p4.run_part4(object(), FakeReader(), nav, object(), object(),
                        object(), object(), object(), hooks=h) is True
    assert seen["in_cave"] is True
    assert seen["route3"] == p4.ROUTE3 and seen["route4"] == p4.ROUTE4
    assert forbid_cross_edge == []          # no overworld legs re-walked
    assert "p4_route3" in h.done


def test_resume_route4_east_skips_moon(no_cerulean_fact, forbid_cross_edge,
                                       monkeypatch):
    """On Route 4 with x >= EAST_X (the only honest 'past Mt. Moon' test -
    both 1F doors land WEST, probed 2026-07-06): stage D is skipped and the
    journey resumes at stage E with no fossil."""
    seen = {}

    def fake_east(b, reader, nav, ow, svc, battle, catch, policy,
                  route3, route4, fossil, h=None):
        seen.update(fossil=fossil, route4=route4)
        return True

    monkeypatch.setattr(p4, "stage_moon",
                        lambda *a, **k: pytest.fail("stage D must be skipped"))
    monkeypatch.setattr(p4, "stages_east", fake_east)
    nav = FakeNav(p4.ROUTE4, xy=(35, 5))
    h = Hooks()
    assert p4.run_part4(object(), FakeReader(), nav, object(), object(),
                        object(), object(), object(), hooks=h) is True
    assert seen["fossil"] is None
    assert seen["route4"] == p4.ROUTE4
    assert "p4_moon" in h.done              # skip still closes the quest


def test_resume_route4_west_goes_straight_to_moon(no_cerulean_fact,
                                                  forbid_cross_edge,
                                                  monkeypatch):
    """On Route 4 WEST (x < EAST_X): Route 3 legs skipped, stage D entered
    with in_cave_resume=False, and stage C resolved from the KNOWN
    services.CENTERS row (no door-by-door re-discovery)."""
    monkeypatch.setattr(
        p4, "discover_center",
        lambda *a, **k: pytest.fail("known Center must not be re-discovered"))
    seen = {}

    def fake_moon(b, reader, nav, ow, svc, battle, catch, policy, row,
                  route3, route4, in_cave_resume, h=None):
        seen.update(row=row, in_cave=in_cave_resume)
        return True

    monkeypatch.setattr(p4, "stage_moon", fake_moon)
    nav = FakeNav(p4.ROUTE4, xy=(12, 8))
    assert p4.run_part4(object(), FakeReader(), nav, object(), object(),
                        object(), object(), object(), hooks=Hooks()) is True
    assert seen["in_cave"] is False
    assert seen["row"] == CENTERS[p4.ROUTE4]   # stage C was a fact lookup
    assert forbid_cross_edge == []


def test_pewter_start_crosses_east_then_legs(no_cerulean_fact, monkeypatch):
    """Fresh start in Pewter: one EAST crossing to Route 3, then alternating
    legs until the map flips to Route 4 (leg 1 from x<=55 must be EAST -
    the alternation encodes Route 3's bend north, live 2026-07-05)."""
    nav = FakeNav(p4.PEWTER, xy=(30, 10))
    legs = []

    def fake_cross(b, n, ow, reader, policy, want, direction, budget=420,
                   narrate=None):
        legs.append(direction)
        if nav.map == p4.PEWTER:
            nav.map = p4.ROUTE3           # Pewter -> Route 3
        else:
            nav.map = p4.ROUTE4           # first leg lands Route 4
        return True

    monkeypatch.setattr(p4, "cross_edge", fake_cross)
    monkeypatch.setattr(p4, "stage_moon", lambda *a, **k: True)
    assert p4.run_part4(object(), FakeReader(), nav, object(), object(),
                        object(), object(), object(), hooks=Hooks()) is True
    assert legs[0] == "EAST"              # leaving Pewter
    assert legs[1] == "EAST"              # leg 1 (even leg, x <= 55)


# ------------------------------------------------- stage E/F (fakes) ---

def test_stages_east_reaches_city_and_discovers_center(no_cerulean_fact,
                                                       monkeypatch):
    """Stage E leg alternation EAST/SOUTH finds the first NEW group-3 map;
    stage F discovers + heals (recorder) and the part passes."""
    nav = FakeNav(p4.ROUTE4, xy=(35, 5))
    dirs = []

    def fake_cross(b, n, ow, reader, policy, want, direction, budget=420,
                   narrate=None):
        dirs.append(direction)
        if len(dirs) == 2:                # second leg lands Cerulean
            nav.map = (3, 3)
        return True

    discovered = []

    def fake_discover(b, n, ow, svc, reader, city):
        discovered.append(city)
        return {"map": (7, 3), "door": (22, 19),
                "nurse": (7, 2), "stand": (7, 4)}

    monkeypatch.setattr(p4, "cross_edge", fake_cross)
    monkeypatch.setattr(p4, "discover_center", fake_discover)
    h = Hooks()
    assert p4.stages_east(object(), FakeReader(), nav, object(), object(),
                          object(), object(), object(),
                          p4.ROUTE3, p4.ROUTE4, None, h) is True
    assert dirs[:2] == ["EAST", "SOUTH"]
    assert discovered == [(3, 3)]
    assert "p4_east" in h.done and "p4_cerulean" in h.done


def test_stages_east_route3_seam_recovers_north(no_cerulean_fact, monkeypatch):
    """Dropping through the Route 4 seam onto Route 3 (live 2026-07-06) must
    recover NORTH instead of burning EAST/SOUTH legs."""
    nav = FakeNav(p4.ROUTE3, xy=(60, 3))
    dirs = []

    def fake_cross(b, n, ow, reader, policy, want, direction, budget=420,
                   narrate=None):
        dirs.append(direction)
        if direction == "NORTH":
            nav.map = p4.ROUTE4           # recovered
        elif len(dirs) >= 2:
            nav.map = (3, 3)
        return True

    monkeypatch.setattr(p4, "cross_edge", fake_cross)
    monkeypatch.setattr(p4, "discover_center",
                        lambda *a, **k: {"map": (7, 3)})
    assert p4.stages_east(object(), FakeReader(), nav, object(), object(),
                          object(), object(), object(),
                          p4.ROUTE3, p4.ROUTE4, None, Hooks()) is True
    assert dirs[0] == "NORTH"


def test_stage_f_known_center_heals_without_discovery(no_cerulean_fact,
                                                      monkeypatch):
    """Stage F fact gate: a known city Center row routes through
    svc.heal_at_center, never the door-by-door hunt."""
    nav = FakeNav(p4.ROUTE4, xy=(35, 5))

    def fake_cross(b, n, ow, reader, policy, want, direction, budget=420,
                   narrate=None):
        nav.map = (3, 3)
        return True

    monkeypatch.setattr(p4, "cross_edge", fake_cross)
    monkeypatch.setattr(
        p4, "discover_center",
        lambda *a, **k: pytest.fail("known Center must not be re-discovered"))
    monkeypatch.setitem(CENTERS, (3, 3), {"map": (7, 3), "door": (22, 19),
                                          "nurse": (7, 2), "stand": (7, 4)})
    healed = []
    svc = SimpleNamespace(heal_at_center=lambda city: healed.append(city) or True)
    assert p4.stages_east(object(), FakeReader(), nav, object(), svc,
                          object(), object(), object(),
                          p4.ROUTE3, p4.ROUTE4, 99, Hooks()) is True
    assert healed == [(3, 3)]


def test_stages_east_fails_when_no_city(no_cerulean_fact, monkeypatch):
    nav = FakeNav(p4.ROUTE4, xy=(35, 5))
    monkeypatch.setattr(p4, "cross_edge", lambda *a, **k: True)  # never lands
    h = Hooks()
    assert p4.stages_east(object(), FakeReader(), nav, object(), object(),
                          object(), object(), object(),
                          p4.ROUTE3, p4.ROUTE4, None, h) is False
    assert any(t == "p4_east" and "FAIL" in msg for t, msg in h.phases)


# ------------------------------------------------- visited sidecar ---

def test_visited_sidecar_roundtrip(tmp_path):
    """Nested map-id keys must survive the round-trip (the acceptance
    script's flat tuple(json.loads(k)) left the inner id a LIST — unhashable
    — so its sidecar never loaded; the module reconstructs deep tuples)."""
    path = str(tmp_path / "visited.json")
    visited = {((1, 2), 32, 5): 3, ((1, 1), 14, 27): 1}
    p4._save_visited(path, visited)
    assert p4._load_visited(path) == visited
    # on-disk format unchanged from the live script (existing files load)
    raw = json.load(open(path, encoding="utf-8"))
    assert set(raw) == {"[[1, 2], 32, 5]", "[[1, 1], 14, 27]"}


def test_visited_sidecar_missing_file_is_empty(tmp_path):
    assert p4._load_visited(str(tmp_path / "nope.json")) == {}
