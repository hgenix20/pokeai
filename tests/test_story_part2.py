"""Fact-gate tests for the Part 2 storyline agent (story_part2.run_part2).

Same philosophy as tests/test_navigator_walk.py: tiny fakes drive the REAL
agent code, no emulator, no monkeypatched sleeps needed (the skip paths never
sleep). What these pin down is the RESUMABILITY contract (the FL-7 lesson
applied to part 2): a step whose outcome fact already holds in RAM must be
SKIPPED - rolled off the quest board via done_task without a single button
press - and the travel legs must follow the verified Pallet <-> Route 1 <->
Viridian <-> Route 2 rail with the G3 budgets (Route 1 northbound 420s,
everything else 240s). The stage-action sequences themselves are live-verified
ports and are exercised on the real game, not here."""
from __future__ import annotations

from pokeai.agents import story_part2 as sp2

DONE_FLAGS = {sp2.FLAG_SYS_POKEDEX_GET}
DONE_ITEMS = {sp2.ITEM_TOWN_MAP: 1, sp2.ITEM_TEACHY_TV: 1}


class _State:
    def __init__(self, hp, mx, count):
        self.party_total_hp = hp
        self.party_total_max_hp = mx
        self.party_count = count


class FakeReader:
    """count_item / read_flag / read / ball_count over plain dicts."""

    def __init__(self, items=None, flags=(), hp=(20, 20), party=1, balls=5):
        self.items = dict(items or {})
        self.flags = set(flags)
        self.hp = hp
        self.party = party
        self.balls = balls

    def count_item(self, item_id):
        return self.items.get(item_id, 0)

    def read_flag(self, flag_id):
        return flag_id in self.flags

    def read(self):
        return _State(self.hp[0], self.hp[1], self.party)

    def ball_count(self):
        return self.balls


class FakeNav:
    def __init__(self, map_id, outside=None):
        self.map = map_id
        self.outside = outside     # where leave_building lands us
        self.left = 0

    def current_map(self):
        return self.map

    def leave_building(self):
        self.left += 1
        if self.outside is not None:
            self.map = self.outside
        return self.map


class FakeOW:
    def __init__(self):
        self.waits = []

    def wait_control(self, timeout=25.0, confirm=2):
        self.waits.append(timeout)
        return True


class FakeSvc:
    """heal_at_center that actually tops the fake party up."""

    def __init__(self, reader):
        self.reader = reader
        self.healed = 0

    def heal_at_center(self, city_map=None):
        assert city_map == sp2.VIRIDIAN
        self.healed += 1
        self.reader.hp = (self.reader.hp[1], self.reader.hp[1])
        return True


class Boom:
    """Any use = the resumability contract broke (a gated step acted)."""

    def __getattr__(self, name):
        raise AssertionError(f"gated step touched the world: .{name}")


class Hooks:
    def __init__(self):
        self.phases = []
        self.done = []

    def phase(self, task_id, action):
        self.phases.append((task_id, action))

    def done_task(self, task_id):
        self.done.append(task_id)


# --------------------------------------------------------------------------
# Fact helpers
# --------------------------------------------------------------------------

def test_fact_helpers_read_the_right_ram():
    r = FakeReader(items={sp2.ITEM_OAKS_PARCEL: 1}, hp=(9, 20))
    assert sp2.have_parcel(r)
    assert not sp2.parcel_delivered(r)
    assert not sp2.have_town_map(r)
    assert not sp2.have_teachy_tv(r)
    assert not sp2._party_full(r)

    r2 = FakeReader(items=DONE_ITEMS, flags=DONE_FLAGS, hp=(20, 20))
    assert not sp2.have_parcel(r2)          # delivered = OUT of the bag
    assert sp2.parcel_delivered(r2)
    assert sp2.have_town_map(r2)
    assert sp2.have_teachy_tv(r2)
    assert sp2._party_full(r2)


def test_party_full_requires_a_party():
    # an empty party reading full-HP-of-zero must not skip the heal gate
    assert not sp2._party_full(FakeReader(hp=(0, 0), party=0))


# --------------------------------------------------------------------------
# pending_steps - the resume plan
# --------------------------------------------------------------------------

def test_pending_fresh_start_lists_every_step():
    r = FakeReader(hp=(9, 20))              # post-rival scratches, nothing banked
    assert sp2.pending_steps(r, FakeNav(sp2.ROUTE1)) == list(sp2.STEP_IDS)


def test_pending_after_mart_pickup():
    r = FakeReader(items={sp2.ITEM_OAKS_PARCEL: 1}, hp=(20, 20))
    assert sp2.pending_steps(r, FakeNav(sp2.VIRIDIAN)) == [
        "p2_deliver", "p2_townmap", "p2_teachytv", "p2_route2"]


def test_pending_after_delivery():
    # parcel gone + dex flag set: the whole northbound pickup arc is moot
    r = FakeReader(flags=DONE_FLAGS, hp=(20, 20))
    assert sp2.pending_steps(r, FakeNav(sp2.PALLET)) == [
        "p2_townmap", "p2_teachytv", "p2_route2"]


def test_pending_hurt_resume_reinstates_only_the_heal():
    r = FakeReader(items=DONE_ITEMS, flags=DONE_FLAGS, hp=(3, 20))
    assert sp2.pending_steps(r, FakeNav(sp2.VIRIDIAN)) == ["p2_heal", "p2_route2"]


def test_pending_all_done_is_empty():
    r = FakeReader(items=DONE_ITEMS, flags=DONE_FLAGS, hp=(20, 20))
    assert sp2.pending_steps(r, FakeNav(sp2.ROUTE2)) == []


# --------------------------------------------------------------------------
# run_part2 skip paths - facts held => no world contact
# --------------------------------------------------------------------------

def test_run_part2_all_facts_hold_skips_everything():
    """Everything banked and standing on Route 2: run_part2 must succeed
    without touching the bridge/skills at all (Boom raises on ANY use) and
    must roll every step off the quest board, in story order."""
    r = FakeReader(items=DONE_ITEMS, flags=DONE_FLAGS, hp=(20, 20))
    h = Hooks()
    assert sp2.run_part2(Boom(), r, FakeNav(sp2.ROUTE2), Boom(), Boom(),
                         Boom(), h) is True
    assert h.done == list(sp2.STEP_IDS)
    assert h.phases == []                   # no step ran, no narration


def test_run_part2_heal_gate_runs_only_the_heal(monkeypatch):
    """Hurt resume in Viridian with everything else banked: only the heal
    acts (via Services), then the Route 2 crossing - no other world contact."""
    r = FakeReader(items=DONE_ITEMS, flags=DONE_FLAGS, hp=(5, 20))
    nav = FakeNav(sp2.VIRIDIAN)
    svc = FakeSvc(r)
    crossings = []

    def fake_cross(b, n, ow, reader, policy, want, direction,
                   budget=420.0, narrate=None):
        crossings.append((n.current_map(), want, direction, budget))
        n.map = want
        return True

    monkeypatch.setattr(sp2, "cross_edge", fake_cross)
    h = Hooks()
    assert sp2.run_part2(Boom(), r, nav, Boom(), svc, Boom(), h) is True
    assert svc.healed == 1
    assert crossings == [(sp2.VIRIDIAN, sp2.ROUTE2, "NORTH", 240.0)]
    assert h.done == list(sp2.STEP_IDS)


# --------------------------------------------------------------------------
# run_part2 wiring - a pending step drives the right travel + action
# --------------------------------------------------------------------------

def test_run_part2_route2_crossing_goes_north(monkeypatch):
    r = FakeReader(items=DONE_ITEMS, flags=DONE_FLAGS, hp=(20, 20))
    nav = FakeNav(sp2.VIRIDIAN)
    crossings = []

    def fake_cross(b, n, ow, reader, policy, want, direction,
                   budget=420.0, narrate=None):
        crossings.append((n.current_map(), want, direction, budget))
        n.map = want
        return True

    monkeypatch.setattr(sp2, "cross_edge", fake_cross)
    h = Hooks()
    assert sp2.run_part2(None, r, nav, None, None, None, h) is True
    assert crossings == [(sp2.VIRIDIAN, sp2.ROUTE2, "NORTH", 240.0)]
    assert h.done[-1] == "p2_route2"


def test_run_part2_fails_when_the_crossing_fails(monkeypatch):
    r = FakeReader(items=DONE_ITEMS, flags=DONE_FLAGS, hp=(20, 20))
    nav = FakeNav(sp2.VIRIDIAN)
    monkeypatch.setattr(sp2, "cross_edge", lambda *a, **k: False)
    h = Hooks()
    assert sp2.run_part2(None, r, nav, None, None, None, h) is False
    assert "p2_route2" not in h.done


def test_run_part2_lab_resume_delivers_without_re_trekking(monkeypatch):
    """Resume INSIDE Oak's lab with the parcel (the old slot-7 checkpoint):
    the deliver step must run in place - no Pallet trek, no lab re-entry -
    then the rest of the errand chains through on the rail."""
    r = FakeReader(items={sp2.ITEM_OAKS_PARCEL: 1}, hp=(20, 20))
    nav = FakeNav(sp2.OAKLAB, outside=sp2.PALLET)
    ow = FakeOW()
    deliveries = []
    crossings = []

    def fake_deliver(b, reader, n, ow_, narrate=None):
        deliveries.append(n.current_map())
        reader.items.pop(sp2.ITEM_OAKS_PARCEL)
        reader.flags.add(sp2.FLAG_SYS_POKEDEX_GET)
        return True

    def fake_town_map(reader, n, ow_, narrate=None):
        assert n.current_map() == sp2.PALLET
        reader.items[sp2.ITEM_TOWN_MAP] = 1
        return True

    def fake_teachy_tv(reader, n, ow_, narrate=None):
        assert n.current_map() == sp2.VIRIDIAN
        reader.items[sp2.ITEM_TEACHY_TV] = 1
        return True

    def fake_cross(b, n, ow_, reader, policy, want, direction,
                   budget=420.0, narrate=None):
        crossings.append((n.current_map(), want, direction, budget))
        n.map = want
        return True

    monkeypatch.setattr(sp2, "_deliver_to_oak", fake_deliver)
    monkeypatch.setattr(sp2, "_get_town_map", fake_town_map)
    monkeypatch.setattr(sp2, "_get_teachy_tv", fake_teachy_tv)
    monkeypatch.setattr(sp2, "cross_edge", fake_cross)
    h = Hooks()
    assert sp2.run_part2(None, r, nav, ow, Boom(), None, h) is True
    assert deliveries == [sp2.OAKLAB]       # delivered in place
    # the townmap step's _travel exits the lab (one leave_building, no legs),
    # then the teachy-tv and route-2 steps ride the rail north
    assert nav.left == 1
    assert crossings == [
        (sp2.PALLET, sp2.ROUTE1, "NORTH", 240.0),
        (sp2.ROUTE1, sp2.VIRIDIAN, "NORTH", 420.0),
        (sp2.VIRIDIAN, sp2.ROUTE2, "NORTH", 240.0),
    ]
    assert h.done == list(sp2.STEP_IDS)


# --------------------------------------------------------------------------
# _travel - the rail
# --------------------------------------------------------------------------

def _record_cross(nav, crossings):
    def fake_cross(b, n, ow, reader, policy, want, direction,
                   budget=420.0, narrate=None):
        crossings.append((n.current_map(), want, direction, budget))
        nav.map = want
        return True
    return fake_cross


def test_travel_northbound_legs_and_budgets(monkeypatch):
    nav = FakeNav(sp2.PALLET)
    crossings = []
    monkeypatch.setattr(sp2, "cross_edge", _record_cross(nav, crossings))
    assert sp2._travel(None, FakeReader(), nav, FakeOW(), None, sp2.VIRIDIAN)
    # Route 1 NORTHBOUND keeps the G3 420s grass budget; the rest 240s
    assert crossings == [
        (sp2.PALLET, sp2.ROUTE1, "NORTH", 240.0),
        (sp2.ROUTE1, sp2.VIRIDIAN, "NORTH", 420.0),
    ]


def test_travel_southbound_legs_and_budgets(monkeypatch):
    nav = FakeNav(sp2.VIRIDIAN)
    crossings = []
    monkeypatch.setattr(sp2, "cross_edge", _record_cross(nav, crossings))
    assert sp2._travel(None, FakeReader(), nav, FakeOW(), None, sp2.PALLET)
    assert crossings == [
        (sp2.VIRIDIAN, sp2.ROUTE1, "SOUTH", 240.0),
        (sp2.ROUTE1, sp2.PALLET, "SOUTH", 240.0),
    ]


def test_travel_leaves_a_building_first(monkeypatch):
    """A resume inside an interior (Mart/lab checkpoints) exits the building
    before any leg - the part2_full_test stage-B/C pattern."""
    nav = FakeNav(sp2.MART_MAP, outside=sp2.VIRIDIAN)
    ow = FakeOW()
    crossings = []
    monkeypatch.setattr(sp2, "cross_edge", _record_cross(nav, crossings))
    assert sp2._travel(None, FakeReader(), nav, ow, None, sp2.PALLET)
    assert nav.left == 1
    assert ow.waits[0] == 12
    assert crossings[0][0] == sp2.VIRIDIAN


def test_travel_already_there_is_a_noop(monkeypatch):
    nav = FakeNav(sp2.VIRIDIAN)
    monkeypatch.setattr(
        sp2, "cross_edge",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("crossed")))
    assert sp2._travel(Boom(), FakeReader(), nav, Boom(), Boom(), sp2.VIRIDIAN)


def test_travel_off_the_rail_fails_fast(monkeypatch):
    """Pewter is part 3+ territory: _travel must refuse rather than wander
    (the driver owns anything off the part-2 rail)."""
    crossings = []
    nav = FakeNav((3, 2))
    monkeypatch.setattr(sp2, "cross_edge", _record_cross(nav, crossings))
    assert not sp2._travel(None, FakeReader(), nav, FakeOW(), None, sp2.VIRIDIAN)
    assert crossings == []


def test_travel_failed_leg_propagates(monkeypatch):
    nav = FakeNav(sp2.ROUTE1)
    monkeypatch.setattr(sp2, "cross_edge", lambda *a, **k: False)
    assert not sp2._travel(None, FakeReader(), nav, FakeOW(), None, sp2.VIRIDIAN)
