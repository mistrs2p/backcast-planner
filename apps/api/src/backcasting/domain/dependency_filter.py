"""Dependency filtering of candidate slots.

The dependency layer of the scheduling hierarchy (docs/05): a task
cannot start until the tasks it depends on have finished
(finish-to-start, :mod:`backcasting.domain.task_dependency`). The
filter turns that rule into slot arithmetic: given the finish times
of the already-placed tasks, a slot's usable part begins no earlier
than the last prerequisite's finish — slots are clipped, not
destroyed, because free time after the gate is still free time.

Only *direct* prerequisites gate the start: a transitive
prerequisite's constraint is already embodied in its dependent's own
placement (B waited on A, so B's finish respects A), so chaining the
gate through the whole graph would double-count and could block on
an unplaced ancestor whose constraint is already satisfied.

A prerequisite with no finish time has not been placed yet — the
task is ``DEPENDENCY_BLOCKED`` (docs/06) and the result is empty:
an unplaced prerequisite is a fact to resolve upstream, not a
constraint to quietly route around.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Mapping

from backcasting.domain.candidate_slot import CandidateSlot
from backcasting.domain.task_dependency import (
    TaskDependency,
    _validate_links,
    depends_on,
)
from backcasting.domain.timezone import require_utc


class DependencyFilterError(ValueError):
    """Raised when a dependency-filtering invariant is violated."""


def filter_slots_by_dependencies(
    slots: tuple[CandidateSlot, ...],
    dependencies: tuple[TaskDependency, ...],
    *,
    task_id: uuid.UUID,
    duration: timedelta,
    finishes: Mapping[uuid.UUID, datetime],
) -> tuple[CandidateSlot, ...]:
    """Clip ``slots`` to start no earlier than the prerequisites finish.

    ``finishes`` maps already-placed task ids to their finish times.
    Every direct prerequisite of ``task_id`` must appear in it — a
    missing prerequisite means the task is ``DEPENDENCY_BLOCKED``
    (docs/06) and the result is empty. Slots whose post-gate remainder
    is shorter than ``duration`` are dropped; the rest keep input
    order.
    """
    if not isinstance(slots, tuple):
        raise DependencyFilterError("slots must be a tuple of CandidateSlot")
    for slot in slots:
        if not isinstance(slot, CandidateSlot):
            raise DependencyFilterError("slots must be CandidateSlot instances")
    _validate_links(dependencies)
    if not isinstance(task_id, uuid.UUID):
        raise DependencyFilterError("task_id must be a UUID")
    if not isinstance(duration, timedelta) or duration <= timedelta(0):
        raise DependencyFilterError("duration must be a strictly positive timedelta")
    if not isinstance(finishes, Mapping):
        raise DependencyFilterError("finishes must be a mapping of UUID to datetime")
    for finished_id, finish in finishes.items():
        if not isinstance(finished_id, uuid.UUID):
            raise DependencyFilterError("finishes keys must be UUIDs")
        require_utc("finish", finish, error=DependencyFilterError)

    prerequisites = depends_on(dependencies, task_id)
    if prerequisites:
        for prerequisite in prerequisites:
            if prerequisite not in finishes:
                return ()
        ready = max(finishes[prerequisite] for prerequisite in prerequisites)
    else:
        ready = None

    filtered: list[CandidateSlot] = []
    for slot in slots:
        start = slot.start if ready is None else max(slot.start, ready)
        if slot.end - start >= duration:
            filtered.append(CandidateSlot(start=start, end=slot.end))
    return tuple(filtered)
