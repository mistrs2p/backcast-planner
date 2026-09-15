"""Rescheduling — moving work in time without touching the Plan.

Level 1 of the adaptation ladder (docs/08-REPLANNING-MODEL.md):
"Reschedule — move time only." Distinct from replanning (level 2) in
every dimension the spec fixes: the Goal, the Future, the Plan, the
tasks and their workload are untouched — only *when* the work happens
changes. "Schedule and Replanning are distinct" (docs/03).

:func:`reschedule_task` performs the move for one task: the displaced
placements (from :mod:`~backcasting.domain.conflict_resolution`,
TASK-065) are withdrawn, the same work re-places into fresh slot
allocations, and the untouched placements stay exactly where they
are — the minimum-change principle (docs/08) made structural: only
displaced time moves.

Invariants:

- Every schedule given belongs to the task; the replaced ones are a
  subset of its placements.
- The re-placed work equals the withdrawn work to the tick — "move
  time only": a reschedule neither creates nor destroys workload. A
  change in amount is a re-estimation, and that belongs to replanning.
- The new placements respect the task's deadline and do not overlap
  one another (via :func:`~backcasting.domain.schedule.place_task`)
  nor the placements being kept — one task, one place at a time.
- All new placements share ``at`` as their ``created_at``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from backcasting.domain.schedule import Schedule, place_task
from backcasting.domain.task import Task
from backcasting.domain.task_splitting import SlotAllocation
from backcasting.domain.timezone import require_utc


class ReschedulingError(ValueError):
    """Raised when a rescheduling invariant is violated."""


@dataclass(frozen=True)
class RescheduleResult:
    """The outcome of one task's reschedule — a pure time move.

    ``removed`` are the withdrawn placements (delete by id), ``kept``
    the untouched ones, ``placed`` the fresh replacements (save).
    """

    removed: tuple[Schedule, ...]
    kept: tuple[Schedule, ...]
    placed: tuple[Schedule, ...]


def _total(schedules: tuple[Schedule, ...]) -> timedelta:
    return sum(
        (schedule.end - schedule.start for schedule in schedules), timedelta(0)
    )


def _overlaps(a: Schedule, b: Schedule) -> bool:
    return a.start < b.end and b.start < a.end


def reschedule_task(
    task: Task,
    schedules: tuple[Schedule, ...],
    replacing: tuple[Schedule, ...],
    allocations: tuple[SlotAllocation, ...],
    *,
    at: datetime,
) -> RescheduleResult:
    """Move the displaced placements of ``task`` to ``allocations``.

    ``schedules`` is the task's full current placement set;
    ``replacing`` the subset being withdrawn (the displacements);
    ``allocations`` where the withdrawn work goes now.
    """
    if not isinstance(task, Task):
        raise TypeError("task must be a Task")
    if not isinstance(schedules, tuple):
        raise ReschedulingError("schedules must be a tuple of Schedule")
    for schedule in schedules:
        if not isinstance(schedule, Schedule):
            raise ReschedulingError("schedules must be Schedule instances")
        if schedule.task_id != task.task_id:
            raise ReschedulingError(
                "schedules must belong to the task being rescheduled"
            )
    if not isinstance(replacing, tuple):
        raise ReschedulingError("replacing must be a tuple of Schedule")
    for schedule in replacing:
        if not isinstance(schedule, Schedule):
            raise ReschedulingError("replacing must be Schedule instances")
        if schedule not in schedules:
            raise ReschedulingError(
                "replacing must be a subset of the task's placements"
            )
    if not replacing:
        raise ReschedulingError(
            "rescheduling requires displaced placements to move"
        )
    if not isinstance(allocations, tuple):
        raise ReschedulingError("allocations must be a tuple of SlotAllocation")
    for allocation in allocations:
        if not isinstance(allocation, SlotAllocation):
            raise ReschedulingError(
                "allocations must be SlotAllocation instances"
            )
    if not allocations:
        raise ReschedulingError(
            "rescheduling requires new placements"
            " (withdrawing work without re-placing it is not a reschedule)"
        )
    require_utc("at", at, error=ReschedulingError)

    if _total(replacing) != _total_allocations(allocations):
        raise ReschedulingError(
            "a reschedule moves time only: the re-placed workload must"
            " equal the withdrawn workload (docs/08)"
        )

    kept = tuple(schedule for schedule in schedules if schedule not in replacing)
    placed = place_task(task, allocations, created_at=at)
    for new in placed:
        for kept_schedule in kept:
            if _overlaps(new, kept_schedule):
                raise ReschedulingError(
                    "new placements must not overlap the kept placements"
                )
    return RescheduleResult(removed=replacing, kept=kept, placed=placed)


def _total_allocations(allocations: tuple[SlotAllocation, ...]) -> timedelta:
    return sum(
        (allocation.end - allocation.start for allocation in allocations),
        timedelta(0),
    )
