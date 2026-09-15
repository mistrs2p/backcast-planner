"""Rolling horizon — the operational window and what it exacts.

docs/06-PLANNING-SCHEDULING.md fixes the shape: "Long-term:
milestones/approximate allocation. Short-term: exact tasks and
slots. Default operational horizon: next 2 weeks." The horizon
rolls: at each instant the window is ``[now, now + duration)`` and
everything due inside it moves from approximate allocation to exact
scheduling.

What the window exacts (the deterministic classification):

- A task is *due* when its deadline is set and falls no later than
  the horizon's end — overdue counts as due; the work is not less
  operational for being late.
- A milestone is *near* when its target date falls no later than the
  horizon's end; a task is *anchored* when it serves an outcome of a
  near milestone (long-term milestones keep approximate allocation,
  near ones pull their outcome tasks into the exact zone).
- Due and anchored tasks are exact — and so are their transitive
  prerequisites: an exact task is unplaceable while its prerequisites
  are unplaced (docs/05 puts dependencies above deadline), so the
  chain crosses into the exact zone with it.

Everything else stays approximate — placed roughly against the
remaining capacity until the window rolls far enough to exact it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from backcasting.domain.milestone import Milestone
from backcasting.domain.outcome import Outcome
from backcasting.domain.task import Task
from backcasting.domain.task_dependency import (
    TaskDependency,
    all_prerequisites,
)
from backcasting.domain.timezone import require_utc

DEFAULT_HORIZON = timedelta(weeks=2)  # docs/06: "next 2 weeks"


class RollingHorizonError(ValueError):
    """Raised when a rolling-horizon invariant is violated."""


@dataclass(frozen=True)
class Horizon:
    """The operational window: half-open ``[start, end)``."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        require_utc("start", self.start, error=RollingHorizonError)
        require_utc("end", self.end, error=RollingHorizonError)
        if self.end <= self.start:
            raise RollingHorizonError("end must be after start")

    @property
    def duration(self) -> timedelta:
        return self.end - self.start

    def contains(self, moment: datetime) -> bool:
        """Whether ``moment`` falls inside ``[start, end)``."""
        require_utc("moment", moment, error=RollingHorizonError)
        return self.start <= moment < self.end


def operational_horizon(
    now: datetime,
    *,
    duration: timedelta = DEFAULT_HORIZON,
) -> Horizon:
    """The rolling operational window at ``now``.

    Half-open ``[now, now + duration)``; the default duration is two
    weeks (docs/06). Each call re-derives the window from the
    current instant — that re-derivation *is* the rolling.
    """
    require_utc("now", now, error=RollingHorizonError)
    if not isinstance(duration, timedelta) or duration <= timedelta(0):
        raise RollingHorizonError("duration must be a strictly positive timedelta")
    return Horizon(start=now, end=now + duration)


@dataclass(frozen=True)
class HorizonSplit:
    """Tasks partitioned by what the horizon exacts.

    ``exact`` — short-term: placed into concrete slots (deadlines,
    near-milestone outcomes, and their prerequisite chains).
    ``approximate`` — long-term: rough allocation until the window
    rolls over them. Both tuples preserve input order.
    """

    exact: tuple[Task, ...]
    approximate: tuple[Task, ...]


def split_tasks_by_horizon(
    tasks: tuple[Task, ...],
    dependencies: tuple[TaskDependency, ...],
    milestones: tuple[Milestone, ...],
    outcomes: tuple[Outcome, ...],
    *,
    horizon: Horizon,
) -> HorizonSplit:
    """Partition ``tasks`` into the exact and the approximate.

    See the module docstring for the classification. Input order is
    preserved in both partitions.
    """
    if not isinstance(horizon, Horizon):
        raise RollingHorizonError("horizon must be a Horizon")
    if not isinstance(tasks, tuple):
        raise RollingHorizonError("tasks must be a tuple of Task")
    seen: set = set()
    for task in tasks:
        if not isinstance(task, Task):
            raise RollingHorizonError("tasks must be Task instances")
        if task.task_id in seen:
            raise RollingHorizonError("tasks must have unique ids")
        seen.add(task.task_id)
    if not isinstance(milestones, tuple):
        raise RollingHorizonError("milestones must be a tuple of Milestone")
    for milestone in milestones:
        if not isinstance(milestone, Milestone):
            raise RollingHorizonError("milestones must be Milestone instances")
    if not isinstance(outcomes, tuple):
        raise RollingHorizonError("outcomes must be a tuple of Outcome")
    for outcome in outcomes:
        if not isinstance(outcome, Outcome):
            raise RollingHorizonError("outcomes must be Outcome instances")

    due_ids = {
        task.task_id
        for task in tasks
        if task.deadline is not None and task.deadline <= horizon.end
    }
    near_milestone_ids = {
        milestone.milestone_id
        for milestone in milestones
        if milestone.target_date <= horizon.end
    }
    anchored_outcome_ids = {
        outcome.outcome_id
        for outcome in outcomes
        if outcome.milestone_id is not None
        and outcome.milestone_id in near_milestone_ids
    }
    seed_ids = due_ids | {
        task.task_id
        for task in tasks
        if anchored_outcome_ids and task.outcome_ids & anchored_outcome_ids
    }
    exact_ids = set(seed_ids)
    for task_id in seed_ids:
        exact_ids |= all_prerequisites(dependencies, task_id)

    exact = tuple(task for task in tasks if task.task_id in exact_ids)
    approximate = tuple(task for task in tasks if task.task_id not in exact_ids)
    return HorizonSplit(exact=exact, approximate=approximate)
