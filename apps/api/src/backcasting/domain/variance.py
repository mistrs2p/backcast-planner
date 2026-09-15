"""Variance — the planned-vs-actual difference, as a time signal.

docs/02-CONCEPTUAL-MODEL.md: "Variance: planned vs actual
difference". docs/07-PROGRESS-FEEDBACK.md names four time-denominated
instances of it — progress variance, time variance, capacity
variance, schedule variance — each a comparison of what was planned
against what actually happened, in hours and minutes.

This module is the timedelta sibling of
:func:`~backcasting.domain.metric.interpret_variance` (TASK-015),
which interprets *metric-typed* values according to the metric's
direction. Here the direction is inherent in the signal itself:

- **progress** — actual workload vs planned workload; more work
  done than planned is favorable (the plan is being outrun).
- **time** — how long a task actually took vs its estimate; taking
  less than estimated is favorable (the estimate was safe).
- **capacity** — how much workable time materialized vs how much
  was planned for the same period; more observed capacity is
  favorable.
- **schedule** — how much of the placed time was actually worked;
  fully worked placements are favorable.

``delta`` is ``actual - planned`` everywhere, one sign convention
for all four; ``favorable`` applies the direction above. The
judgment of what to *do* about a variance (docs/08's ladder:
reschedule, replan, goal revision) lives upstream — these records
only state the difference.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import Enum

from backcasting.domain.availability import AvailabilityWindow
from backcasting.domain.calendar_event import CalendarEvent
from backcasting.domain.execution import Execution
from backcasting.domain.observed_capacity import (
    ObservedCapacity,
    ObservedCapacityError,
)
from backcasting.domain.planned_capacity import workable_time
from backcasting.domain.progress import ProgressSnapshot
from backcasting.domain.schedule import Schedule
from backcasting.domain.task import Task


class VarianceError(ValueError):
    """Raised when a variance invariant is violated."""


class VarianceKind(str, Enum):
    """The four time-denominated variance signals (docs/07)."""

    PROGRESS = "progress"
    TIME = "time"
    CAPACITY = "capacity"
    SCHEDULE = "schedule"


def _non_negative(name: str, amount: timedelta) -> None:
    if not isinstance(amount, timedelta) or amount < timedelta(0):
        raise VarianceError(f"{name} must be a non-negative timedelta")


@dataclass(frozen=True)
class Variance:
    """One planned-vs-actual difference, in time.

    ``delta`` is ``actual - planned`` for every kind; ``favorable``
    applies the kind's inherent direction (see module docstring).
    """

    kind: VarianceKind
    planned: timedelta
    actual: timedelta
    delta: timedelta
    favorable: bool

    def __post_init__(self) -> None:
        if not isinstance(self.kind, VarianceKind):
            raise VarianceError("kind must be a VarianceKind")
        _non_negative("planned", self.planned)
        _non_negative("actual", self.actual)
        if not isinstance(self.delta, timedelta):
            raise VarianceError("delta must be a timedelta")
        if self.delta != self.actual - self.planned:
            raise VarianceError("delta must equal actual - planned")
        if not isinstance(self.favorable, bool):
            raise VarianceError("favorable must be a bool")


def _build(
    kind: VarianceKind,
    planned: timedelta,
    actual: timedelta,
    favorable: bool,
) -> Variance:
    return Variance(
        kind=kind,
        planned=planned,
        actual=actual,
        delta=actual - planned,
        favorable=favorable,
    )


def progress_variance(snapshot: ProgressSnapshot) -> Variance:
    """Workload done vs workload planned, from a progress snapshot."""
    if not isinstance(snapshot, ProgressSnapshot):
        raise VarianceError("snapshot must be a ProgressSnapshot")
    return _build(
        VarianceKind.PROGRESS,
        snapshot.planned,
        snapshot.actual,
        snapshot.actual >= snapshot.planned,
    )


def time_variance(task: Task, executions: tuple[Execution, ...]) -> Variance:
    """How long ``task`` actually took vs its estimate.

    ``executions`` are the task's recorded sittings (others are
    ignored). The task must carry a duration — without an estimate
    there is no planned side to differ from.
    """
    if not isinstance(task, Task):
        raise TypeError("task must be a Task")
    if not isinstance(executions, tuple):
        raise VarianceError("executions must be a tuple of Execution")
    for execution in executions:
        if not isinstance(execution, Execution):
            raise VarianceError("executions must be Execution instances")
    if task.duration is None:
        raise VarianceError(
            f"task {task.task_id} ({task.title!r}) has no estimate"
        )
    actual = sum(
        (
            execution.duration
            for execution in executions
            if execution.task_id == task.task_id
        ),
        timedelta(0),
    )
    return _build(VarianceKind.TIME, task.duration, actual, actual <= task.duration)


def capacity_variance(
    windows: tuple[AvailabilityWindow, ...],
    events: tuple[CalendarEvent, ...],
    observed: ObservedCapacity,
) -> Variance:
    """Workable time that materialized vs what was planned.

    The planned side is recomputed with the same semantics
    (:func:`workable_time`) over the observed record's own period, so
    both sides always describe the same range. More observed capacity
    than planned is favorable.
    """
    if not isinstance(observed, ObservedCapacity):
        raise VarianceError("observed must be an ObservedCapacity")
    try:
        planned = workable_time(
            windows,
            events,
            range_start=observed.period_start,
            range_end=observed.period_end,
        )
    except (ObservedCapacityError, ValueError) as exc:
        # workable_time raises the planned-capacity error for bad
        # windows/events; restate it in this module's type.
        raise VarianceError(str(exc)) from exc
    return _build(
        VarianceKind.CAPACITY, planned, observed.amount, observed.amount >= planned
    )


def _overlap(a_start, a_end, b_start, b_end) -> timedelta:
    start = max(a_start, b_start)
    end = min(a_end, b_end)
    return end - start if end > start else timedelta(0)


def schedule_variance(
    schedules: tuple[Schedule, ...],
    executions: tuple[Execution, ...],
) -> Variance:
    """Placed time vs the part of it that was actually worked.

    ``actual`` is the executed time lying inside the placements (per
    matching task): work outside the placed intervals is a timing
    fact the progress and time variances already carry; this signal
    measures adherence to the placement itself. Fully worked
    placements are favorable; with no placements both sides are zero
    and the (vacuous) adherence is favorable.
    """
    if not isinstance(schedules, tuple):
        raise VarianceError("schedules must be a tuple of Schedule")
    for schedule in schedules:
        if not isinstance(schedule, Schedule):
            raise VarianceError("schedules must be Schedule instances")
    if not isinstance(executions, tuple):
        raise VarianceError("executions must be a tuple of Execution")
    for execution in executions:
        if not isinstance(execution, Execution):
            raise VarianceError("executions must be Execution instances")

    planned = sum(
        (schedule.end - schedule.start for schedule in schedules), timedelta(0)
    )
    actual = timedelta(0)
    for schedule in schedules:
        for execution in executions:
            if execution.task_id == schedule.task_id:
                actual += _overlap(
                    schedule.start, schedule.end, execution.start, execution.end
                )
    return _build(
        VarianceKind.SCHEDULE, planned, actual, actual >= planned
    )
