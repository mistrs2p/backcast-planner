"""Regional replan — a related group of tasks, revised together.

Level 2 at middle scope (docs/08): the execution plan changes in a
region — several tasks at once — while the Goal and Future stay
untouched. The archetypal case: one task's estimate was wrong, and
the correction ripples — everything that waits on it, and
everything it waits on, belongs to the same region and moves in the
same replan, as *one* meaningful change with *one* reason and *one*
plan version. Revising the region task-by-task through local
replans instead would leave the plan telling a story in several
versions of what is one decision.

The region is defined mechanically, not picked by hand:
:func:`dependency_region` is the seed task plus every task
connected to it through the dependency graph — prerequisites and
dependents alike, since a re-estimate moves work on both sides —
returned in topological order. Whether the proposed revisions
actually cover the region is the reasoning layer's judgement
(ADR-002); the domain provides the boundary and enforces the trace.

The workload moves by the sum of the estimate deltas, the same
shift-not-recompute rule as the local replan (TASK-085). The whole
plan at once is the global replan (TASK-087).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from backcasting.domain.plan import Plan
from backcasting.domain.plan_version import (
    PlanChangeSet,
    PlanVersion,
    apply_plan_version,
)
from backcasting.domain.replanning_policy import ReplanScope
from backcasting.domain.task import Task
from backcasting.domain.task_dependency import (
    TaskDependency,
    all_prerequisites,
    blocks,
    topological_order,
)
from backcasting.domain.timezone import UTC


class RegionalReplanError(ValueError):
    """Raised when a regional-replan invariant is violated."""


@dataclass(frozen=True)
class TaskRevision:
    """One task's before and after, as a unit of a regional replan."""

    before: Task
    after: Task

    def __post_init__(self) -> None:
        if not isinstance(self.before, Task):
            raise RegionalReplanError("before must be a Task")
        if not isinstance(self.after, Task):
            raise RegionalReplanError("after must be a Task")
        if self.after.task_id != self.before.task_id:
            raise RegionalReplanError(
                "a revision keeps the task's identity; these are two tasks"
            )
        if (
            self.after.title == self.before.title
            and self.after.description == self.before.description
            and self.after.duration == self.before.duration
            and self.after.deadline == self.before.deadline
        ):
            raise RegionalReplanError(
                "revision changes nothing; every regional revision must change its task"
            )


@dataclass(frozen=True)
class RegionalReplan:
    """The outcome of replanning a region: the revised plan value,
    the revised tasks, and the version tracing the change."""

    scope: ReplanScope
    plan: Plan
    tasks: tuple[Task, ...]
    version: PlanVersion

    def __post_init__(self) -> None:
        if self.scope is not ReplanScope.REGIONAL:
            raise RegionalReplanError("scope must be REGIONAL")
        if not isinstance(self.plan, Plan):
            raise RegionalReplanError("plan must be a Plan")
        if not isinstance(self.tasks, tuple):
            raise RegionalReplanError("tasks must be a tuple of Task")
        for task in self.tasks:
            if not isinstance(task, Task):
                raise RegionalReplanError("tasks must be Task instances")
            if task.plan_id != self.plan.plan_id:
                raise RegionalReplanError("task does not belong to this plan")
        if not isinstance(self.version, PlanVersion):
            raise RegionalReplanError("version must be a PlanVersion")
        if self.version.plan_id != self.plan.plan_id:
            raise RegionalReplanError("version does not belong to this plan")


def dependency_region(
    seed: Task,
    tasks: tuple[Task, ...],
    dependencies: tuple[TaskDependency, ...],
) -> tuple[Task, ...]:
    """The seed plus every task connected to it through the
    dependency graph, in topological order.

    Connection runs both ways — a re-estimate moves work for the
    task's prerequisites and its dependents alike. Tasks not linked
    to the seed stay out: the region is the ripple, not the plan.
    """
    if not isinstance(seed, Task):
        raise RegionalReplanError("seed must be a Task")
    if not isinstance(tasks, tuple):
        raise RegionalReplanError("tasks must be a tuple of Task")
    for task in tasks:
        if not isinstance(task, Task):
            raise RegionalReplanError("tasks must be Task instances")
    if not isinstance(dependencies, tuple):
        raise RegionalReplanError("dependencies must be a tuple of TaskDependency")
    for link in dependencies:
        if not isinstance(link, TaskDependency):
            raise RegionalReplanError("dependencies must be TaskDependency instances")

    by_id = {task.task_id: task for task in tasks}
    if seed.task_id not in by_id:
        raise RegionalReplanError("seed must be among the tasks")

    # all_prerequisites validates the links; the dependents walk then
    # reuses the same collection.
    connected: set[uuid.UUID] = {seed.task_id}
    connected |= all_prerequisites(dependencies, seed.task_id)
    frontier = {seed.task_id}
    while frontier:
        next_frontier: set[uuid.UUID] = set()
        for current in frontier:
            for dependent in blocks(dependencies, current):
                if dependent not in connected:
                    connected.add(dependent)
                    next_frontier.add(dependent)
        frontier = next_frontier

    region = tuple(task for task in tasks if task.task_id in connected)
    region_links = tuple(
        link
        for link in dependencies
        if link.task_id in connected and link.depends_on_task_id in connected
    )
    return topological_order(region, region_links)


def replan_tasks_regionally(
    plan: Plan,
    history: tuple[PlanVersion, ...],
    revisions: tuple[TaskRevision, ...],
    *,
    reason: str,
    source_run_id: uuid.UUID | None = None,
    at: datetime | None = None,
) -> RegionalReplan:
    """Apply a group of task revisions as one meaningful replan.

    Each revision must belong to the plan and revise a distinct
    task; the plan's workload moves by the sum of the estimate
    deltas (an estimate landing on an unestimated task counts as its
    full amount); the trace is one plan version naming every revised
    task.
    """
    if not isinstance(plan, Plan):
        raise RegionalReplanError("plan must be a Plan")
    if not isinstance(history, tuple):
        raise RegionalReplanError("history must be a tuple of PlanVersion")
    if not isinstance(revisions, tuple):
        raise RegionalReplanError("revisions must be a tuple of TaskRevision")
    if not revisions:
        raise RegionalReplanError(
            "a regional replan revises at least one task"
        )

    seen: set[uuid.UUID] = set()
    delta = timedelta(0)
    for revision in revisions:
        if not isinstance(revision, TaskRevision):
            raise RegionalReplanError("revisions must be TaskRevision instances")
        if revision.before.plan_id != plan.plan_id:
            raise RegionalReplanError("task does not belong to this plan")
        if revision.after.plan_id != plan.plan_id:
            raise RegionalReplanError("task does not belong to this plan")
        if revision.before.task_id in seen:
            raise RegionalReplanError("a task is revised twice in one region")
        seen.add(revision.before.task_id)
        before = revision.before.duration
        after = revision.after.duration
        if before != after:
            previous = before if before is not None else timedelta(0)
            current = after if after is not None else timedelta(0)
            delta += current - previous

    workload = plan.workload + delta if delta != timedelta(0) else None
    revised_plan, version = apply_plan_version(
        plan,
        history,
        reason=reason,
        change_set=PlanChangeSet(
            workload=workload,
            revised_task_ids=tuple(
                revision.after.task_id for revision in revisions
            ),
        ),
        source_run_id=source_run_id,
        at=at if at is not None else datetime.now(UTC),
    )
    return RegionalReplan(
        scope=ReplanScope.REGIONAL,
        plan=revised_plan,
        tasks=tuple(revision.after for revision in revisions),
        version=version,
    )
