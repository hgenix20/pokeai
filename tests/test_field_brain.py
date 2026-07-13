"""Pure-fake unit tests for the Field Brain (agents/field_brain.py):

  * FieldContext.build — RAM facts (half_party_low boundary, fainted_count,
    mart_known, config overlay) through a scripted FakeReader, no emulator.
  * arbiter_with_overrides — the REAL load_roots() drives re-weighted by a
    strategy preset (<= 0 disables, boosts reorder).
  * FieldBrain.run — the decide -> dispatch loop (complete short-circuit,
    executor routing + history, no_executor -> stuck, cycle cap).
"""
from __future__ import annotations

from pokeai.agents.field_brain import (
    ROUTE1,
    VIRIDIAN,
    FieldBrain,
    FieldContext,
    arbiter_with_overrides,
)


def _mon(level: int, hp: int, max_hp: int) -> dict:
    return {"level": level, "hp": hp, "max_hp": max_hp}


class FakeReader:
    """Scripted stand-in for FireRedStateReader (only the surface build() uses).

    `details` stays a mutable attribute so executors can 'heal' mid-run."""

    def __init__(self, details, money=3000, balls=5, heals=0, badges=0,
                 map_id=(ROUTE1[0] << 8) | ROUTE1[1]):
        self.details = list(details)
        self.money = money
        self.balls = balls
        self.heals = heals
        self.badges = badges
        self.map_id = map_id

    def read_party_details(self):
        return [dict(m) for m in self.details]

    def read_current_map(self):
        return self.map_id

    def read_badges(self):
        return self.badges

    def read_money(self):
        return self.money

    def ball_count(self):
        return self.balls

    def count_heal_items(self):
        return self.heals


class FakeNav:
    def __init__(self, cur):
        self.cur = cur

    def current_map(self):
        return self.cur


HEALTHY = [_mon(60, 50, 50), _mon(60, 48, 48)]   # Lv60 clears every gym curve


# --- FieldContext facts ---


def test_context_facts_from_reader():
    reader = FakeReader([_mon(10, 4, 20), _mon(12, 9, 20), _mon(8, 20, 20)],
                        money=3000, balls=5, heals=2, badges=0)
    ctx = FieldContext(reader, None,
                       {"party_target": 6, "wild_available": True}).build()
    assert ctx["party_count"] == 3
    assert ctx["party_hp_fraction"] == 33 / 60
    assert ctx["fainted_count"] == 0
    assert ctx["half_party_low"] is True         # 2 of 3 under half HP
    assert ctx["party_top_level"] == 12
    assert ctx["money"] == 3000
    assert ctx["ball_count"] == 5
    assert ctx["healing_items"] == 2
    assert ctx["badges"] == 0
    assert ctx["current_map"] == ROUTE1          # divmod of (group<<8)|num
    assert ctx["mart_known"] is False            # Route 1 has no mart landmark
    assert ctx["always"] is True
    assert ctx["party_target"] == 6 and ctx["wild_available"] is True


def test_half_party_low_boundary_one_of_three():
    # 1 hurt of 3 < ceil(3/2)=2 -> False; exactly-half HP (0.5) is NOT hurt.
    reader = FakeReader([_mon(10, 4, 20), _mon(12, 10, 20), _mon(8, 20, 20)])
    ctx = FieldContext(reader, None).build()
    assert ctx["half_party_low"] is False


def test_fainted_count_and_mart_known_from_map():
    reader = FakeReader(
        [_mon(10, 0, 20), _mon(12, 20, 20), _mon(9, 20, 20), _mon(11, 20, 20)],
        map_id=(VIRIDIAN[0] << 8) | VIRIDIAN[1])
    ctx = FieldContext(reader, None).build()
    assert ctx["fainted_count"] == 1
    assert ctx["current_map"] == VIRIDIAN
    assert ctx["mart_known"] is True             # Viridian is a mart landmark


def test_nav_current_map_wins_over_reader():
    reader = FakeReader(HEALTHY)                 # reader says Route 1...
    ctx = FieldContext(reader, FakeNav(VIRIDIAN)).build()
    assert ctx["current_map"] == VIRIDIAN        # ...but nav is authoritative
    assert ctx["mart_known"] is True


def test_config_overlays_last():
    reader = FakeReader(HEALTHY, money=3000)
    ctx = FieldContext(reader, None,
                       {"money": 150, "mart_known": True}).build()
    assert ctx["money"] == 150                   # preset pins a computed fact
    assert ctx["mart_known"] is True             # config flag despite Route 1


# --- real load_roots() drives through the context ---


def _decide(reader, config=None, overrides=None):
    ctx = FieldContext(reader, None, config).build()
    return arbiter_with_overrides(overrides).decide(ctx)


def test_survive_wins_when_party_hurt():
    d = _decide(FakeReader([_mon(10, 3, 20)], money=100))   # 15% HP
    assert d.drive == "survive" and d.goal == "heal"


def test_survive_wins_on_a_fainted_mon_alone():
    # 75% aggregate HP and only 1 of 4 hurt: only fainted_count trips survive.
    d = _decide(FakeReader(
        [_mon(10, 0, 20), _mon(12, 20, 20), _mon(9, 20, 20), _mon(11, 20, 20)]))
    assert d.drive == "survive" and d.goal == "heal"


def test_restock_beats_fill_party_when_low_on_balls():
    reader = FakeReader(HEALTHY, money=400, balls=1, heals=5,
                        map_id=(VIRIDIAN[0] << 8) | VIRIDIAN[1])
    d = _decide(reader, config={"party_target": 6, "wild_available": True})
    assert d.drive == "restock_balls" and d.goal == "restock"


def test_fill_party_fires_when_healthy_with_balls():
    reader = FakeReader(HEALTHY, money=100, balls=5, heals=5)
    d = _decide(reader, config={"party_target": 6, "wild_available": True})
    assert d.drive == "fill_party" and d.goal == "catch"


# --- arbiter_with_overrides ---


def test_zero_priority_overrides_remove_drives():
    a = arbiter_with_overrides({"prepare": 0, "grow": 0, "progress": 0,
                                "explore": 0})
    names = [d.name for d in a.roots.drives]
    assert not {"prepare", "grow", "progress", "explore"} & set(names)
    assert {"survive", "restock_balls", "fill_party"} <= set(names)
    prios = [d.priority for d in a.roots.drives]
    assert prios == sorted(prios, reverse=True)  # still sorted desc


def test_priority_boost_reorders_drives():
    a = arbiter_with_overrides({"explore": 95})
    names = [d.name for d in a.roots.drives]
    assert names.index("survive") < names.index("explore") < names.index("restock_balls")
    # A boosted explore now outranks a firing restock (95 > 90).
    reader = FakeReader(HEALTHY, money=1000, balls=0,
                        map_id=(VIRIDIAN[0] << 8) | VIRIDIAN[1])
    d = _decide(reader, overrides={"explore": 95})
    assert d.drive == "explore"


# --- FieldBrain.run ---


def _brain(reader, executors, config=None, **kw) -> FieldBrain:
    return FieldBrain(arbiter_with_overrides(), FieldContext(reader, None, config),
                      executors, **kw)


def test_run_complete_short_circuits_before_dispatch():
    calls = []
    brain = _brain(FakeReader(HEALTHY),
                   {"heal": lambda ctx: calls.append(ctx) or "healed"},
                   complete_when=lambda ctx: True)
    res = brain.run()
    assert res["status"] == "complete"
    assert res["cycles"] == 0 and res["history"] == []
    assert calls == []                           # executor never invoked


def test_run_dispatches_executor_and_records_history():
    reader = FakeReader([_mon(60, 5, 50)], money=100)   # hurt -> survive/heal

    def ex_heal(ctx) -> str:
        reader.details = [_mon(60, 50, 50)]
        return "healed"

    brain = _brain(reader, {"heal": ex_heal},
                   complete_when=lambda ctx: ctx["party_hp_fraction"] >= 0.9)
    res = brain.run()
    assert res["status"] == "complete" and res["cycles"] == 1
    assert res["history"] == [("survive", "heal", "healed")]


def test_run_stuck_after_three_unknown_goals():
    res = _brain(FakeReader([_mon(60, 5, 50)], money=100), {}).run()
    assert res["status"] == "stuck" and res["cycles"] == 2
    assert [h[2] for h in res["history"]] == ["no_executor"] * 3


def test_run_hits_cycle_cap():
    reader = FakeReader([_mon(60, 5, 50)], money=100)    # stays hurt forever
    res = _brain(reader, {"heal": lambda ctx: "tried"}).run(max_cycles=4)
    assert res["status"] == "cycle_cap" and res["cycles"] == 4
    assert res["history"] == [("survive", "heal", "tried")] * 4
