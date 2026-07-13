"""ROM-free unit tests for the planner task queue (F4)."""
from __future__ import annotations

from pokeai.planner import Task, TaskKind, TaskQueue, TaskStatus


class S:
    """Fake game state for predicates."""
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_enqueue_dedupes_and_raises_priority():
    q = TaskQueue()
    q.enqueue(Task(TaskKind.BUY_ITEM, {"item": "antidote", "qty": 2}, base_priority=5))
    q.enqueue(Task(TaskKind.BUY_ITEM, {"item": "antidote", "qty": 2}, base_priority=8))
    assert len(q) == 1
    t = q.all()[0]
    assert t.priority == 8 and t.base_priority == 8


def test_active_picks_highest_priority():
    q = TaskQueue()
    q.enqueue(Task(TaskKind.HEAL, base_priority=2))
    q.enqueue(Task(TaskKind.ADVANCE_STORY, {"step": "oak"}, base_priority=9))
    q.enqueue(Task(TaskKind.NAVIGATE_TO, {"map": "route1"}, base_priority=4))
    assert q.active().kind == TaskKind.ADVANCE_STORY


def test_active_skips_irrelevant():
    q = TaskQueue()
    q.enqueue(Task(TaskKind.HEAL, base_priority=9,
                   still_relevant=lambda s: s.hurt))
    q.enqueue(Task(TaskKind.NAVIGATE_TO, {"map": "x"}, base_priority=3))
    assert q.active(S(hurt=False)).kind == TaskKind.NAVIGATE_TO
    assert q.active(S(hurt=True)).kind == TaskKind.HEAL


def test_tick_completes_satisfied():
    q = TaskQueue()
    q.enqueue(Task(TaskKind.EARN_MONEY, {"amount": 500}, base_priority=5,
                   satisfied=lambda s: s.money >= 500))
    q.tick(S(money=200))
    assert q.all()[0].status == TaskStatus.PENDING
    q.tick(S(money=600))
    assert q.all()[0].status == TaskStatus.DONE
    assert q.active(S(money=600)) is None  # nothing runnable left


def test_tick_abandons_irrelevant():
    q = TaskQueue()
    t = q.enqueue(Task(TaskKind.FIND_POKEMON, {"species": "pidgey"}, base_priority=5,
                       still_relevant=lambda s: not s.caught))
    q.tick(S(caught=True))
    assert t.status == TaskStatus.ABANDONED


def test_dependency_expansion_blocks_then_unblocks():
    q = TaskQueue()
    parent = Task(TaskKind.BUY_ITEM, {"item": "antidote"}, base_priority=5)
    dep_money = Task(TaskKind.EARN_MONEY, {"amount": 500}, base_priority=3,
                     satisfied=lambda s: s.money >= 500)
    dep_nav = Task(TaskKind.NAVIGATE_TO, {"map": "mart"}, base_priority=3,
                   satisfied=lambda s: s.at_mart)
    q.block_with_deps(parent, [dep_money, dep_nav])

    assert q.get(parent.id).status == TaskStatus.BLOCKED
    # while blocked, the parent is NOT runnable; a dependency is chosen instead
    chosen = q.active(S(money=0, at_mart=False))
    assert chosen.kind in (TaskKind.EARN_MONEY, TaskKind.NAVIGATE_TO)

    # satisfy both deps -> they complete and the parent unblocks
    q.tick(S(money=500, at_mart=True))
    assert q.get(dep_money.id).status == TaskStatus.DONE
    assert q.get(dep_nav.id).status == TaskStatus.DONE
    assert q.get(parent.id).status == TaskStatus.PENDING
    assert q.active(S(money=500, at_mart=True)).id == parent.id


def test_partial_deps_keep_parent_blocked():
    q = TaskQueue()
    parent = Task(TaskKind.USE_FIELD_MOVE, {"move": "cut"}, base_priority=6)
    hm = Task(TaskKind.OBTAIN_HM, {"hm": "cut"}, base_priority=4,
              satisfied=lambda s: s.has_hm)
    teach = Task(TaskKind.TEACH_MOVE, {"move": "cut"}, base_priority=4,
                 satisfied=lambda s: s.taught)
    q.block_with_deps(parent, [hm, teach])
    q.tick(S(has_hm=True, taught=False))   # only one dep done
    assert q.get(parent.id).status == TaskStatus.BLOCKED
    assert q.active(S(has_hm=True, taught=False)).kind == TaskKind.TEACH_MOVE


def test_reprioritize():
    q = TaskQueue()
    a = q.enqueue(Task(TaskKind.HEAL, base_priority=2))
    b = q.enqueue(Task(TaskKind.ADVANCE_STORY, {"s": "1"}, base_priority=5))
    # meta-policy bumps HEAL above story
    q.reprioritize(lambda t: 100 if t.kind == TaskKind.HEAL else t.base_priority)
    assert q.active().id == a.id
    assert b.priority == 5
