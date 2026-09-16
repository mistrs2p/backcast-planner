"""Global replan — the whole plan, re-derived.

Level 2 at its widest scope (docs/08): the execution plan changes
as a whole, while the Goal and Future stay untouched. The local and
regional replans shift the plan's workload by their estimate deltas
— they preserve whatever basis the workload was declared on,
because they change one task or one group and the rest of the
declaration still stands. A global replan changes *everything*, so
there is nothing left to preserve: the workload is recomputed from
the plan's task set (:func:`~backcasting.domain.task_estimation.estimate_workload`,
which refuses to sum over unestimated tasks — a missing estimate is
a fact to surface, and a global replan that cannot face its own
task set's estimates cannot re-derive the plan).

The trace is the same plan version every replan produces; its
change set carries the recomputed workload and the optional new
title. A global replan whose recomputation lands on the same
workload and title changes nothing, and is rejected — re-deriving
an identical plan is not a replan.

What a global replan deliberately does *not* do: revise individual
tasks (local, TASK-085), move a dependency-connected group
(regional, TASK-086), or touch the Goal/Future — that is level 3,
the user's. Comparing candidate plans is TASK-088.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from backcasting.domain.plan import Plan
from backcasting.domain.plan_version import (
    PlanChangeSet,
    PlanVersion,
    apply_plan_version,
)
from backcasting.domain.replanning_policy import ReplanScope
from backcasting.domain.task import Task
from backcasting.domain.task_estimation import estimate_workload
from backcasting.domain.timezone import UTC


class GlobalReplanError(ValueError):
    """Raised when a global-replan invariant is violated."""


@dataclass(frozen=True)
class GlobalReplan:
    """The outcome of replanning the whole plan: the re-derived plan
    value and the version tracing the change."""

    scope: ReplanScope
    plan: Plan
    version: PlanVersion

    def __post_init__(self) -> None:
        if self.scope is not ReplanScope.GLOBAL:
            raise GlobalReplanError("scope must be GLOBAL")
        if not isinstance(self.plan, Plan):
            raise GlobalReplanError("plan must be a Plan")
        if not isinstance(self.version, PlanVersion):
            raise GlobalReplanError("version must be a PlanVersion")
        if self.version.plan_id != self.plan.plan_id:
            raise GlobalReplanError("version does not belong to this plan")


def replan_plan_globally(
    plan: Plan,
    history: tuple[PlanVersion, ...],
    tasks: tuple[Task, ...],
    *,
    reason: str,
    title: str | None = None,
    source_run_id: uuid.UUID | None = None,
    at: datetime | None = None,
) -> GlobalReplan:
    """Re-derive ``plan`` from its ``tasks``: workload recomputed,
    title optionally revised, one version tracing the change.

    Every task must belong to the plan; every task must carry an
    estimate (the aggregation's own rule). A re-derivation that
    lands where the plan already stands is rejected — it changed
    nothing.
    """
    if not isinstance(plan, Plan):
        raise GlobalReplanError("plan must be a Plan")
    if not isinstance(history, tuple):
        raise GlobalReplanError("history must be a tuple of PlanVersion")
    if not isinstance(tasks, tuple):
        raise GlobalReplanError("tasks must be a tuple of Task")
    for task in tasks:
        if not isinstance(task, Task):
            raise GlobalReplanError("tasks must be Task instances")
        if task.plan_id != plan.plan_id:
            raise GlobalReplanError("task does not belong to this plan")

    workload = estimate_workload(tasks)
    revised_plan, version = apply_plan_version(
        plan,
        history,
        reason=reason,
        change_set=PlanChangeSet(title=title, workload=workload),
        source_run_id=source_run_id,
        at=at if at is not None else datetime.now(UTC),
    )
    return GlobalReplan(
        scope=ReplanScope.GLOBAL, plan=revised_plan, version=version
    )
