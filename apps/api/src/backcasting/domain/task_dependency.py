"""Task dependency domain model.

Dependencies order tasks: a task cannot start until the tasks it
depends on have finished (finish-to-start, the MVP relation).
Dependencies sit third in the scheduling hierarchy — "Hard
constraints → existing commitments → dependencies → …" (docs/05) —
and an unmet one is the ``DEPENDENCY_BLOCKED`` failure reason
(docs/06).

A :class:`TaskDependency` is a single directed link
``task → depends_on`` ("task depends on depends_on"). Links are
created and appended through :func:`add_dependency`, which enforces
the deterministic invariants:

- no self-dependency (a task never waits on itself);
- no duplicate link;
- both tasks belong to the same plan — a task never waits on another
  plan's work;
- no cycle: the new link must not create a path back to its tail.
  Cycles are checked at write time, so a valid dependency collection
  is acyclic by construction (:func:`topological_order` still checks
  defensively — a corrupted collection raises rather than loops).

Collections are plan-scoped by construction and by the repository
that persists them; :func:`topological_order` turns a plan's tasks
into the scheduler's processing order — Kahn's algorithm, stable on
the input order, so the result is deterministic.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Iterable

from backcasting.domain.task import Task


class TaskDependencyError(ValueError):
    """Raised when a task-dependency invariant is violated."""


@dataclass(frozen=True)
class TaskDependency:
    """One finish-to-start link: ``task_id`` waits for ``depends_on_task_id``."""

    task_id: uuid.UUID
    depends_on_task_id: uuid.UUID

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, uuid.UUID):
            raise TaskDependencyError("task_id must be a UUID")
        if not isinstance(self.depends_on_task_id, uuid.UUID):
            raise TaskDependencyError("depends_on_task_id must be a UUID")
        if self.task_id == self.depends_on_task_id:
            raise TaskDependencyError("a task cannot depend on itself")


def _validate_links(dependencies: tuple[TaskDependency, ...]) -> None:
    if not isinstance(dependencies, tuple):
        raise TaskDependencyError("dependencies must be a tuple of TaskDependency")
    for link in dependencies:
        if not isinstance(link, TaskDependency):
            raise TaskDependencyError("dependencies must be TaskDependency instances")


def create_dependency(task: Task, depends_on: Task) -> TaskDependency:
    """Link ``task`` to finish after ``depends_on``.

    Both tasks must belong to the same plan.
    """
    if not isinstance(task, Task):
        raise TypeError("task must be a Task")
    if not isinstance(depends_on, Task):
        raise TypeError("depends_on must be a Task")
    if task.plan_id != depends_on.plan_id:
        raise TaskDependencyError(
            "dependency crosses plans: both tasks must belong to the same plan"
        )
    return TaskDependency(task_id=task.task_id, depends_on_task_id=depends_on.task_id)


def has_path(
    dependencies: tuple[TaskDependency, ...],
    start: uuid.UUID,
    target: uuid.UUID,
) -> bool:
    """Whether a dependency chain leads from ``start`` to ``target``."""
    _validate_links(dependencies)
    if not isinstance(start, uuid.UUID) or not isinstance(target, uuid.UUID):
        raise TaskDependencyError("start and target must be UUIDs")
    successors: dict[uuid.UUID, set[uuid.UUID]] = {}
    for link in dependencies:
        successors.setdefault(link.depends_on_task_id, set()).add(link.task_id)
    queue = [start]
    seen = {start}
    while queue:
        current = queue.pop()
        for follower in successors.get(current, ()):
            if follower == target:
                return True
            if follower not in seen:
                seen.add(follower)
                queue.append(follower)
    return False


def add_dependency(
    dependencies: tuple[TaskDependency, ...],
    task: Task,
    depends_on: Task,
) -> tuple[TaskDependency, ...]:
    """Return ``dependencies`` with a new validated link appended.

    Raises when the link would be a self-dependency, a duplicate, a
    cross-plan link, or the edge that closes a cycle.
    """
    _validate_links(dependencies)
    link = create_dependency(task, depends_on)
    for existing in dependencies:
        if existing == link:
            raise TaskDependencyError("dependency already exists")
    # has_path follows dependents ("waits on" reversed): the new link
    # closes a cycle iff depends_on already waits on task transitively.
    if has_path(dependencies, link.task_id, link.depends_on_task_id):
        raise TaskDependencyError(
            "dependency would create a cycle"
        )
    return dependencies + (link,)


def depends_on(
    dependencies: tuple[TaskDependency, ...], task_id: uuid.UUID
) -> frozenset[uuid.UUID]:
    """The direct prerequisites of ``task_id``."""
    _validate_links(dependencies)
    if not isinstance(task_id, uuid.UUID):
        raise TaskDependencyError("task_id must be a UUID")
    return frozenset(
        link.depends_on_task_id
        for link in dependencies
        if link.task_id == task_id
    )


def blocks(
    dependencies: tuple[TaskDependency, ...], task_id: uuid.UUID
) -> frozenset[uuid.UUID]:
    """The direct dependents waiting on ``task_id``."""
    _validate_links(dependencies)
    if not isinstance(task_id, uuid.UUID):
        raise TaskDependencyError("task_id must be a UUID")
    return frozenset(
        link.task_id for link in dependencies if link.depends_on_task_id == task_id
    )


def topological_order(
    tasks: tuple[Task, ...],
    dependencies: tuple[TaskDependency, ...],
) -> tuple[Task, ...]:
    """Order ``tasks`` so every task follows its prerequisites.

    Kahn's algorithm, stable on the input order: among the tasks
    whose prerequisites are all placed, the earliest input wins — the
    result is deterministic. Raises on a cycle (impossible for
    collections built through :func:`add_dependency`) and on a link
    referencing a task outside ``tasks``.
    """
    if not isinstance(tasks, tuple):
        raise TaskDependencyError("tasks must be a tuple of Task")
    for task in tasks:
        if not isinstance(task, Task):
            raise TaskDependencyError("tasks must be Task instances")
    _validate_links(dependencies)
    by_id = {task.task_id: task for task in tasks}
    if len(by_id) != len(tasks):
        raise TaskDependencyError("tasks must have unique ids")

    waiting: dict[uuid.UUID, set[uuid.UUID]] = {
        task.task_id: set() for task in tasks
    }
    for link in dependencies:
        if link.task_id not in by_id or link.depends_on_task_id not in by_id:
            raise TaskDependencyError(
                "dependency references a task outside the collection"
            )
        waiting[link.task_id].add(link.depends_on_task_id)

    ordered: list[Task] = []
    placed: set[uuid.UUID] = set()
    remaining: list[Task] = list(tasks)
    while remaining:
        ready = [
            task
            for task in remaining
            if waiting[task.task_id] <= placed
        ]
        if not ready:
            raise TaskDependencyError("dependency cycle detected")
        for task in ready:
            ordered.append(task)
            placed.add(task.task_id)
        remaining = [task for task in remaining if task.task_id not in placed]
    return tuple(ordered)


def all_prerequisites(
    dependencies: tuple[TaskDependency, ...], task_id: uuid.UUID
) -> frozenset[uuid.UUID]:
    """Every prerequisite of ``task_id``, direct and transitive."""
    _validate_links(dependencies)
    if not isinstance(task_id, uuid.UUID):
        raise TaskDependencyError("task_id must be a UUID")
    found: set[uuid.UUID] = set()
    frontier: Iterable[uuid.UUID] = {task_id}
    while True:
        next_frontier: set[uuid.UUID] = set()
        for current in frontier:
            for link in dependencies:
                if link.task_id == current and link.depends_on_task_id not in found:
                    next_frontier.add(link.depends_on_task_id)
        if not next_frontier:
            return frozenset(found)
        found |= next_frontier
        frontier = next_frontier
