"""Local replan — revise one task in place.

Level 2 of docs/08's ladder at its narrowest scope: modify the
execution plan — here, a single task's content (its estimate,
deadline, title, description) — while the Goal and Future stay
untouched. The archetypal case is the re-estimate: the persistence
chain said the work is not going as planned, the decision engine
chose REPLAN, and the smallest honest response is to correct one
task's estimate rather than touch anything else.

The trace is the plan version (docs/08: "Every meaningful replan
produces a traceable plan version"): :func:`replan_task_locally`
applies the task revision through
:func:`~backcasting.domain.task.revise_task`, moves the plan's
workload by the estimate's delta (the plan keeps whatever basis its
workload was declared on — a local replan shifts it, it does not
recompute it), and records a :class:`~backcasting.domain.plan_version.PlanVersion`
whose change set names the revised task. A revision that changes
nothing is rejected — a replan that does not replan is not one.

Wider scopes — a related group of tasks (regional), the whole plan
(global) — are TASK-086 and TASK-087.
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
from backcasting.domain.task import Task, revise_task
from backcasting.domain.timezone import UTC


class LocalReplanError(ValueError):
    """Raised when a local-replan invariant is violated."""


@dataclass(frozen=True)
class LocalReplan:
    """The outcome of replanning one task: the revised plan value,
    the revised task, and the version tracing the change."""

    scope: ReplanScope
    plan: Plan
    task: Task
    version: PlanVersion

    def __post_init__(self) -> None:
        if self.scope is not ReplanScope.LOCAL:
            raise LocalReplanError("scope must be LOCAL")
        if not isinstance(self.plan, Plan):
            raise LocalReplanError("plan must be a Plan")
        if not isinstance(self.task, Task):
            raise LocalReplanError("task must be a Task")
        if not isinstance(self.version, PlanVersion):
            raise LocalReplanError("version must be a PlanVersion")
        if self.task.plan_id != self.plan.plan_id:
            raise LocalReplanError("task does not belong to this plan")
        if self.version.plan_id != self.plan.plan_id:
            raise LocalReplanError("version does not belong to this plan")


def replan_task_locally(
    plan: Plan,
    history: tuple[PlanVersion, ...],
    task: Task,
    *,
    reason: str,
    updated_at: datetime | None = None,
    title: str | None = None,
    description: str | None = None,
    duration: timedelta | None = None,
    deadline: datetime | None = None,
    source_run_id: uuid.UUID | None = None,
) -> LocalReplan:
    """Revise ``task`` in place, tracing the change as a plan version.

    ``duration`` may move from ``None`` (an unestimated task gaining
    its estimate grows the plan's workload by that estimate); a
    revision that leaves the task unchanged is rejected.
    """
    if not isinstance(plan, Plan):
        raise LocalReplanError("plan must be a Plan")
    if not isinstance(history, tuple):
        raise LocalReplanError("history must be a tuple of PlanVersion")
    if not isinstance(task, Task):
        raise LocalReplanError("task must be a Task")
    if task.plan_id != plan.plan_id:
        raise LocalReplanError("task does not belong to this plan")

    at = updated_at if updated_at is not None else datetime.now(UTC)
    revised = revise_task(
        task,
        updated_at=at,
        title=title,
        description=description,
        duration=duration,
        deadline=deadline,
    )
    if (
        revised.title == task.title
        and revised.description == task.description
        and revised.duration == task.duration
        and revised.deadline == task.deadline
    ):
        raise LocalReplanError(
            "revision changes nothing; a local replan must change the task"
        )

    workload = None
    if revised.duration != task.duration:
        # An unestimated task's previous contribution was zero; the
        # estimate landing grows the workload by its full amount.
        previous = task.duration if task.duration is not None else timedelta(0)
        workload = plan.workload + (revised.duration - previous)

    revised_plan, version = apply_plan_version(
        plan,
        history,
        reason=reason,
        change_set=PlanChangeSet(
            workload=workload, revised_task_id=task.task_id
        ),
        source_run_id=source_run_id,
        at=at,
    )
    return LocalReplan(
        scope=ReplanScope.LOCAL, plan=revised_plan, task=revised, version=version
    )
