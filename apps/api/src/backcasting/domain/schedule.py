"""Schedule — the placement of a task in time.

"Schedule: placement of task in time" (docs/02-CONCEPTUAL-MODEL.md);
"Task 1:N Schedules" (docs/03-DOMAIN-MODEL.md) — one task, many
placements: a task split across slots (TASK-063) occupies several
intervals, and rescheduling (a later task) produces new placements.
A Schedule is a *plan* for when work happens, distinct both from the
Calendar Event it may be materialized as and from Execution, which
records what actually happened. "Schedule and Replanning are
distinct" (docs/03): replacing placements never rewrites the Plan.

Rules:

- IDs are UUIDs; ``task_id`` references the placed task.
- ``start``/``end`` are timezone-aware UTC with ``end > start``
  (half-open interval, the codebase-wide convention).
- A placement must respect the task's deadline when one is set:
  ending exactly at the deadline is on time (the same half-open
  semantics the deadline layer, TASK-061, filters by).
- ``created_at`` is timezone-aware UTC.

:func:`place_task` is the placement step's entry point: it turns the
slot allocations of a split (or the single allocation of a whole
placement) into Schedule records, refusing placements that overlap
one another — one task cannot be in two places at once.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from backcasting.domain.task import Task
from backcasting.domain.task_splitting import SlotAllocation
from backcasting.domain.timezone import UTC, require_utc


class ScheduleError(ValueError):
    """Raised when a schedule invariant is violated."""


@dataclass(frozen=True)
class Schedule:
    """A task's placement in time: the half-open ``[start, end)``."""

    schedule_id: uuid.UUID
    task_id: uuid.UUID
    start: datetime
    end: datetime
    created_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.schedule_id, uuid.UUID):
            raise ScheduleError("schedule_id must be a UUID")
        if not isinstance(self.task_id, uuid.UUID):
            raise ScheduleError("task_id must be a UUID")
        require_utc("start", self.start, error=ScheduleError)
        require_utc("end", self.end, error=ScheduleError)
        if self.end <= self.start:
            raise ScheduleError("end must be after start")
        require_utc("created_at", self.created_at, error=ScheduleError)


def create_schedule(
    task: Task,
    start: datetime,
    end: datetime,
    *,
    schedule_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> Schedule:
    """Place ``task`` in ``[start, end)``.

    The placement must finish by ``task.deadline`` when one is set —
    the same rule the deadline layer filters candidate slots by
    (TASK-061), enforced here so a persisted placement can never
    encode a deadline violation.
    """
    if not isinstance(task, Task):
        raise TypeError("task must be a Task")
    schedule = Schedule(
        schedule_id=schedule_id if schedule_id is not None else uuid.uuid4(),
        task_id=task.task_id,
        start=start,
        end=end,
        created_at=created_at if created_at is not None else datetime.now(UTC),
    )
    if task.deadline is not None and schedule.end > task.deadline:
        raise ScheduleError(
            "placement ends after the task's deadline"
            " (finishing exactly at the deadline is on time)"
        )
    return schedule


def place_task(
    task: Task,
    allocations: tuple[SlotAllocation, ...],
    *,
    created_at: datetime | None = None,
) -> tuple[Schedule, ...]:
    """Turn slot allocations into Schedule records for ``task``.

    One Schedule per allocation, in input order; the placements must
    not overlap one another (half-open: back-to-back is fine). An
    empty allocation set places nothing — the ``NO_AVAILABLE_SLOT``
    fact stays upstream, where the caller can act on it.
    """
    if not isinstance(task, Task):
        raise TypeError("task must be a Task")
    if not isinstance(allocations, tuple):
        raise ScheduleError("allocations must be a tuple of SlotAllocation")
    for allocation in allocations:
        if not isinstance(allocation, SlotAllocation):
            raise ScheduleError("allocations must be SlotAllocation instances")
    if not allocations:
        raise ScheduleError("allocations must not be empty")

    stamp = created_at if created_at is not None else datetime.now(UTC)
    schedules = [
        create_schedule(task, allocation.start, allocation.end, created_at=stamp)
        for allocation in allocations
    ]
    ordered = sorted(schedules, key=lambda s: (s.start, s.end))
    for earlier, later in zip(ordered, ordered[1:]):
        if later.start < earlier.end:
            raise ScheduleError("placements must not overlap")
    return tuple(schedules)
