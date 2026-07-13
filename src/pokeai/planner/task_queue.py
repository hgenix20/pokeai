"""TaskQueue — the prioritized agenda with dependencies (F4, §6.2/§6.3).

Holds Tasks keyed by their canonical id (so the same kind+params dedupes). Each
step the agent:
  * `tick(state)` — auto-complete satisfied tasks (cascade-unblocking their
    dependents), auto-abandon irrelevant ones, and unblock tasks whose deps are
    now done.
  * `active(state)` — the highest-priority runnable task (PENDING/ACTIVE, all
    deps DONE, still relevant) to execute this step.

Dependency expansion (§6.3): when a task needs a precondition, `block_with_deps`
enqueues the dependency tasks and parks the parent as BLOCKED until they finish
(e.g. UseFieldMove(cut) -> [ObtainHM(cut), TeachMove(cut)]; BuyItem -> [EarnMoney,
NavigateTo]). Pure logic, fully unit-testable.
"""
from __future__ import annotations

from collections.abc import Callable

from pokeai.planner.task import CLOSED, OPEN, Task, TaskStatus


class TaskQueue:
    def __init__(self):
        self._tasks: dict[str, Task] = {}
        self._seq = 0

    # --- inspection ---

    def __len__(self) -> int:
        return sum(1 for t in self._tasks.values() if t.status in OPEN)

    def all(self) -> list[Task]:
        return list(self._tasks.values())

    def open_tasks(self) -> list[Task]:
        return [t for t in self._tasks.values() if t.status in OPEN]

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    # --- mutation ---

    def enqueue(self, task: Task) -> Task:
        """Add a task, or merge into the existing one with the same id (dedupe):
        raise its priority and revive it if it had been closed."""
        existing = self._tasks.get(task.id)
        if existing is not None:
            existing.base_priority = max(existing.base_priority, task.base_priority)
            existing.priority = max(existing.priority, task.priority, existing.base_priority)
            for d in task.depends_on:
                if d not in existing.depends_on:
                    existing.depends_on.append(d)
            if existing.status in CLOSED:
                existing.status = TaskStatus.PENDING
                existing.progress = 0.0
            return existing
        task.seq = self._seq
        self._seq += 1
        self._tasks[task.id] = task
        return task

    def block_with_deps(self, task: Task, deps: list[Task]) -> Task:
        """Enqueue `task` and its dependency tasks, and park `task` as BLOCKED
        until every dep is DONE. Returns the (possibly merged) parent task."""
        task = self.enqueue(task)
        for d in deps:
            d = self.enqueue(d)
            if d.id not in task.depends_on:
                task.depends_on.append(d.id)
        task.status = TaskStatus.BLOCKED
        return task

    # --- dependency helpers ---

    def _deps_done(self, task: Task) -> bool:
        for did in task.depends_on:
            d = self._tasks.get(did)
            if d is None or d.status != TaskStatus.DONE:
                return False
        return True

    # --- per-step maintenance ---

    def tick(self, state) -> None:
        # 1) complete satisfied tasks; repeat so a dep completing can let a parent
        #    (whose own predicate then holds) complete in the same tick.
        changed = True
        while changed:
            changed = False
            for t in self._tasks.values():
                if t.status in OPEN and t.is_satisfied(state):
                    t.status = TaskStatus.DONE
                    t.progress = 1.0
                    changed = True
        # 2) abandon tasks that are no longer relevant
        for t in self._tasks.values():
            if t.status in OPEN and not t.is_relevant(state):
                t.status = TaskStatus.ABANDONED
        # 3) unblock BLOCKED tasks whose dependencies are all DONE
        for t in self._tasks.values():
            if t.status == TaskStatus.BLOCKED and self._deps_done(t):
                t.status = TaskStatus.PENDING

    def reprioritize(self, fn: Callable[[Task], float]) -> None:
        """Set each task's live priority from fn(task) (e.g. the meta-policy)."""
        for t in self._tasks.values():
            t.priority = float(fn(t))

    # --- selection ---

    def active(self, state=None) -> Task | None:
        """The highest-priority runnable task, or None. Runnable = PENDING/ACTIVE,
        all deps DONE, and still relevant. Ties break toward the earlier task.
        Pure query (no mutation); the executor sets the chosen task ACTIVE."""
        runnable = [
            t for t in self._tasks.values()
            if t.status in (TaskStatus.PENDING, TaskStatus.ACTIVE)
            and self._deps_done(t)
            and (state is None or t.is_relevant(state))
        ]
        if not runnable:
            return None
        return max(runnable, key=lambda t: (t.priority, -t.seq))

    def set_active(self, task: Task) -> None:
        """Mark `task` ACTIVE and demote any other ACTIVE task back to PENDING."""
        for t in self._tasks.values():
            if t.status == TaskStatus.ACTIVE and t.id != task.id:
                t.status = TaskStatus.PENDING
        if task.status in (TaskStatus.PENDING, TaskStatus.ACTIVE):
            task.status = TaskStatus.ACTIVE
