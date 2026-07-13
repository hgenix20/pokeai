"""ROM-free tests for the item-ball pickup skill (skills/pickup.py).

A fake world models the two things a pickup needs: item objects that grow
the bag when interacted with, and NPC objects that do not. The skill must
verify pickups by bag delta, never re-poke a visited object, and stop when
candidates run out - the failure modes the FIXLIST item-pickup defects name.
"""
from __future__ import annotations

from pokeai.skills.pickup import Pickup


class FakeVision:
    def __init__(self, xy, objects):
        self.xy = xy
        self.objects = set(objects)

    def player_xy(self):
        return self.xy

    def object_tiles(self):
        return set(self.objects)


class FakeNav:
    def __init__(self, xy, objects):
        self.vision = FakeVision(xy, objects)


class FakeReader:
    """Bag reads come from a dict the fake overworld mutates on pickup."""
    def __init__(self, bag):
        self.bag = bag

    def read_bag_pocket(self, pocket):
        # everything lives in the 'items' pocket for the test
        return list(self.bag.items()) if pocket == "items" else []


class FakeOverworld:
    """interact() grows the bag iff the target is an item tile."""
    def __init__(self, reader, item_tiles):
        self.reader = reader
        self.item_tiles = dict(item_tiles)   # tile -> item_id
        self.interacted: list = []

    def interact(self, target, rounds=6):
        self.interacted.append(target)
        item = self.item_tiles.get(target)
        if item is not None:
            self.reader.bag[item] = self.reader.bag.get(item, 0) + 1
            return True
        return False


def _make(xy=(5, 5), objects=(), item_tiles=(), bag=None):
    reader = FakeReader(dict(bag or {}))
    nav = FakeNav(xy, objects)
    ow = FakeOverworld(reader, item_tiles)
    return Pickup(None, reader, nav, ow), ow


def test_grab_at_returns_item_id_on_bag_growth():
    p, ow = _make(item_tiles={(6, 5): 13})
    assert p.grab_at((6, 5)) == 13
    assert ow.interacted == [(6, 5)]


def test_grab_at_returns_none_when_bag_unchanged():
    p, ow = _make(item_tiles={})   # target is not an item -> no growth
    assert p.grab_at((6, 5)) is None


def test_grab_at_marks_visited_only_on_success():
    p, _ = _make(item_tiles={(6, 5): 13})
    p.grab_at((6, 5))
    assert (6, 5) in p._grabbed
    p2, _ = _make(item_tiles={})
    p2.grab_at((6, 5))
    assert (6, 5) not in p2._grabbed   # a miss is retryable


def test_sweep_collects_item_objects_skips_npcs():
    # two item balls + one NPC among the objects
    p, ow = _make(
        xy=(5, 5),
        objects=[(6, 5), (5, 6), (4, 5)],
        item_tiles={(6, 5): 13, (5, 6): 86},   # (4,5) is an NPC
    )
    got = p.sweep()
    assert sorted(got) == [13, 86]
    # every object was interacted with at most once
    assert len(ow.interacted) == len(set(ow.interacted)) == 3


def test_sweep_never_repokes_a_visited_object():
    p, ow = _make(objects=[(4, 5)], item_tiles={})   # a lone NPC
    p.sweep()
    p.sweep()   # second sweep: (4,5) already visited -> no new interact
    assert ow.interacted == [(4, 5)]


def test_sweep_respects_radius():
    p, ow = _make(xy=(0, 0), objects=[(20, 20)], item_tiles={(20, 20): 13},
                  bag={})
    got = p.sweep(radius=8)
    assert got == []
    assert ow.interacted == []   # object is out of radius


def test_sweep_stops_at_max_tiles():
    p, ow = _make(
        xy=(5, 5),
        objects=[(6, 5), (5, 6), (4, 5), (5, 4)],
        item_tiles={(6, 5): 1, (5, 6): 2, (4, 5): 3, (5, 4): 4},
    )
    got = p.sweep(max_tiles=2)
    assert len(got) == 2
    assert len(ow.interacted) == 2


def test_delta_reports_first_grown_item():
    assert Pickup._delta({1: 5}, {1: 6}) == 1
    assert Pickup._delta({1: 5}, {1: 5}) is None
    assert Pickup._delta({}, {349: 1}) == 349
