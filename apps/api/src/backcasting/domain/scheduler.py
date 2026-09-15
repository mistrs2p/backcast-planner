"""Scheduler integration — the composed placement pipeline.

EPIC-007's chain wired end to end, the deterministic core of
pipeline step "Places schedulable tasks into feasible time slots"
(docs/06). For each task of the exact partition (the rolling
horizon, TASK-067, decides which those are), in dependency order
(:func:`~backcasting.domain.task_dependency.topological_order` — a
prerequisite places before its dependents, so its finish can gate
them):

1. generate candidate slots — availability minus commitments
   (TASK-057);
2. subtract hard constraints (TASK-058);
3. gate on the goal's remaining capacity share and clip to the
   horizon period (TASK-059) — each placement consumes from the
   budget the next task sees;
4. clip to the placed prerequisites' finishes (TASK-060);
5. clip to the task's deadline (TASK-061);
6. rank the survivors by soft preferences (TASK-062);
7. split the duration across the ranked slots (TASK-063);
8. persist the placements as Schedules (TASK-064).

The layer order follows the epic's construction (capacity gates
before dependencies and deadlines clip); docs/05's hierarchy line
fixes the *priority* of the concerns, and every layer here is
subtractive — each only narrows what the previous layers allowed.

One composition decision (documented, within latitude): the
subtractive layers receive the *granularity* — the smallest chunk a
split can use, TASK-063's quantum — as their minimum piece, not the
task's full duration. A layer handed the full duration keeps only
pieces that could host the whole task, which would starve the
splitter: a 10-hour task against 8-hour days would find no slot at
all instead of flowing 8 + 2 across two days. The budget gate stays
on the task's full duration (a placement consumes its whole estimate
from the pool) and is enforced here, before the capacity layer's
period window is applied.

A task that empties out at a layer fails with that layer's docs/06
reason (:class:`FailureReason`); scheduling continues with the rest.
A failed task leaves no finish time, so its dependents fail as
``DEPENDENCY_BLOCKED`` — the failure propagates down the chain
without retry loops. An unestimated task fails as
``UNESTIMATED_TASK`` (the plan-validation issue code, TASK-056); an
off-granularity estimate raises instead — the estimate is wrong,
not the schedule (docs/05's 15-minute quantum, TASK-063).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from backcasting.domain.availability import AvailabilityWindow
from backcasting.domain.calendar_event import CalendarEvent
from backcasting.domain.candidate_slot import generate_candidate_slots
from backcasting.domain.capacity_filter import filter_slots_by_capacity
from backcasting.domain.constraint import Constraint
from backcasting.domain.constraint_filter import filter_slots_by_constraints
from backcasting.domain.deadline_filter import filter_slots_by_deadline
from backcasting.domain.dependency_filter import filter_slots_by_dependencies
from backcasting.domain.preference import Preference
from backcasting.domain.preference_scoring import rank_slots_by_preferences
from backcasting.domain.rolling_horizon import Horizon
from backcasting.domain.schedule import Schedule, place_task
from backcasting.domain.task import Task
from backcasting.domain.task_dependency import (
    TaskDependency,
    topological_order,
)
from backcasting.domain.task_estimation import (
    TaskEstimation,
    latest_estimation,
)
from backcasting.domain.task_splitting import (
    DEFAULT_GRANULARITY,
    split_task_across_slots,
)
from backcasting.domain.timezone import require_utc


class SchedulerError(ValueError):
    """Raised when a scheduling invariant is violated."""


class FailureReason(str, Enum):
    """Why a task could not be placed (docs/06)."""

    NO_CAPACITY = "no_capacity"
    NO_AVAILABLE_SLOT = "no_available_slot"
    HARD_CONSTRAINT = "hard_constraint"
    DEPENDENCY_BLOCKED = "dependency_blocked"
    DEADLINE_CONFLICT = "deadline_conflict"
    UNESTIMATED_TASK = "unestimated_task"


@dataclass(frozen=True)
class TaskPlacement:
    """One task's persisted placements."""

    task: Task
    schedules: tuple[Schedule, ...]


@dataclass(frozen=True)
class TaskFailure:
    """One task's scheduling failure."""

    task: Task
    reason: FailureReason
    detail: str


@dataclass(frozen=True)
class SchedulingResult:
    """The outcome of scheduling a task set.

    ``placements`` and ``failures`` are in scheduling (dependency)
    order and together account for every task given.
    """

    placements: tuple[TaskPlacement, ...] = ()
    failures: tuple[TaskFailure, ...] = ()
    remaining_budget: timedelta | None = None

    @property
    def placed_task_ids(self) -> frozenset[uuid.UUID]:
        return frozenset(
            placement.task.task_id for placement in self.placements
        )

    @property
    def failure_reasons(self) -> frozenset[FailureReason]:
        return frozenset(failure.reason for failure in self.failures)


def schedule_tasks(
    tasks: tuple[Task, ...],
    *,
    horizon: Horizon,
    at: datetime,
    dependencies: tuple[TaskDependency, ...] = (),
    windows: tuple[AvailabilityWindow, ...] = (),
    events: tuple[CalendarEvent, ...] = (),
    constraints: tuple[Constraint, ...] = (),
    preferences: tuple[Preference, ...] = (),
    estimations: tuple[TaskEstimation, ...] = (),
    budget: timedelta | None = None,
    granularity: timedelta = DEFAULT_GRANULARITY,
) -> SchedulingResult:
    """Schedule ``tasks`` into the operational ``horizon``.

    ``budget`` is the goal's remaining capacity share for the
    horizon period (the pool allocation minus what earlier placement
    rounds consumed); ``None`` skips the capacity layer. Every task
    must be estimated; every dependency link must reference tasks in
    the set. Placements consume the budget in scheduling order.
    """
    if not isinstance(tasks, tuple):
        raise SchedulerError("tasks must be a tuple of Task")
    for task in tasks:
        if not isinstance(task, Task):
            raise SchedulerError("tasks must be Task instances")
    if not isinstance(horizon, Horizon):
        raise SchedulerError("horizon must be a Horizon")
    require_utc("at", at, error=SchedulerError)
    if budget is not None and (
        not isinstance(budget, timedelta) or budget < timedelta(0)
    ):
        raise SchedulerError("budget must be a non-negative timedelta or None")

    ordered = topological_order(tasks, dependencies)

    placements: list[TaskPlacement] = []
    failures: list[TaskFailure] = []
    finishes: dict[uuid.UUID, datetime] = {}
    remaining = budget
    # The smallest piece any layer may keep: the splitter's quantum.
    min_piece = granularity

    for task in ordered:
        estimation = latest_estimation(estimations, task.task_id)
        if estimation is None:
            failures.append(
                TaskFailure(
                    task=task,
                    reason=FailureReason.UNESTIMATED_TASK,
                    detail="no estimate recorded for the task",
                )
            )
            continue
        duration = estimation.duration

        slots = generate_candidate_slots(
            windows,
            events,
            duration=min_piece,
            range_start=horizon.start,
            range_end=horizon.end,
        )
        if not slots:
            failures.append(
                TaskFailure(
                    task=task,
                    reason=FailureReason.NO_AVAILABLE_SLOT,
                    detail="no free time in the horizon",
                )
            )
            continue

        constrained = filter_slots_by_constraints(
            slots, constraints, duration=min_piece
        )
        if not constrained:
            failures.append(
                TaskFailure(
                    task=task,
                    reason=FailureReason.HARD_CONSTRAINT,
                    detail="hard constraints exclude every candidate",
                )
            )
            continue

        if remaining is not None:
            if remaining < duration:
                failures.append(
                    TaskFailure(
                        task=task,
                        reason=FailureReason.NO_CAPACITY,
                        detail="the remaining capacity share cannot hold the task",
                    )
                )
                continue
            affordable = filter_slots_by_capacity(
                constrained,
                period_start=horizon.start,
                period_end=horizon.end,
                budget=remaining,
                duration=min_piece,
            )
            if not affordable:
                failures.append(
                    TaskFailure(
                        task=task,
                        reason=FailureReason.NO_CAPACITY,
                        detail="no candidate lies inside the capacity period",
                    )
                )
                continue
        else:
            affordable = constrained

        gated = filter_slots_by_dependencies(
            affordable,
            dependencies,
            task_id=task.task_id,
            duration=min_piece,
            finishes=finishes,
        )
        if not gated:
            failures.append(
                TaskFailure(
                    task=task,
                    reason=FailureReason.DEPENDENCY_BLOCKED,
                    detail="a prerequisite is unplaced or finishes too late",
                )
            )
            continue

        timely = filter_slots_by_deadline(gated, task=task, duration=min_piece)
        if not timely:
            failures.append(
                TaskFailure(
                    task=task,
                    reason=FailureReason.DEADLINE_CONFLICT,
                    detail="no candidate finishes by the task's deadline",
                )
            )
            continue

        ranked = rank_slots_by_preferences(timely, preferences)
        allocations = split_task_across_slots(
            ranked, duration=duration, granularity=granularity
        )
        if not allocations:
            failures.append(
                TaskFailure(
                    task=task,
                    reason=FailureReason.NO_AVAILABLE_SLOT,
                    detail="the surviving candidates cannot absorb the duration",
                )
            )
            continue

        schedules = place_task(task, allocations, created_at=at)
        placements.append(TaskPlacement(task=task, schedules=schedules))
        finishes[task.task_id] = max(schedule.end for schedule in schedules)
        if remaining is not None:
            remaining -= duration

    return SchedulingResult(
        placements=tuple(placements),
        failures=tuple(failures),
        remaining_budget=remaining,
    )
