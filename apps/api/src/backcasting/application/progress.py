"""Progress use cases (TASK-114) — the Actual side of the triad.

"Planned ≠ Actual ≠ Progress" (docs/07-PROGRESS-FEEDBACK.md): work
happens, gets recorded as :class:`~backcasting.domain.execution.Execution`
sittings (facts — no deadline enforcement, no rounding), and a
snapshot taken at a moment derives progress mechanically from the
plan's estimates and the sittings that ended by then. The domain
holds every rule in ``backcasting.domain.execution`` /
``progress``; this service wires them to the ports.

Executions record on any plan the goal has — a fact is a fact, and
deviation from the plan is the variance layer's material, not this
service's refusal (mirroring the domain's stance).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from backcasting.application.goals import GoalNotFoundError
from backcasting.domain.execution import Execution, create_execution
from backcasting.domain.plan import Plan
from backcasting.domain.progress import (
    ProgressSnapshot,
    take_progress_snapshot,
)
from backcasting.domain.repositories import (
    ExecutionRepository,
    GoalRepository,
    PlanRepository,
    ProgressSnapshotRepository,
    TaskRepository,
)


class NoPlanError(LookupError):
    """Raised when a progress step targets a goal with no plan."""


class NoTaskError(LookupError):
    """Raised when an execution names a task that is not on the
    goal's plan."""


class NoSnapshotError(LookupError):
    """Raised when no progress snapshot has been taken yet."""


@dataclass(frozen=True)
class ProgressBundle:
    """A snapshot with the plan it reads — the progress UI's view."""

    snapshot: ProgressSnapshot
    plan: Plan


class ProgressService:
    """Record work, take snapshots, read the latest progress."""

    def __init__(
        self,
        goals: GoalRepository,
        plans: PlanRepository,
        tasks: TaskRepository,
        executions: ExecutionRepository,
        snapshots: ProgressSnapshotRepository,
    ) -> None:
        self._goals = goals
        self._plans = plans
        self._tasks = tasks
        self._executions = executions
        self._snapshots = snapshots

    def record_execution(
        self,
        *,
        goal_id: uuid.UUID,
        task_id: uuid.UUID,
        start: datetime,
        end: datetime,
    ) -> Execution:
        """Record one sitting of actual work on one of the goal's
        plan's tasks.

        Raises :class:`GoalNotFoundError` /
        :class:`NoPlanError` / :class:`NoTaskError` when there is
        nothing to record against; domain violations (end before
        start) propagate from :func:`~backcasting.domain.execution.create_execution`.
        """
        plan = self._plan_for(goal_id)
        task = self._tasks.get(task_id)
        if task is None or task.plan_id != plan.plan_id:
            raise NoTaskError(f"no task {task_id} on this plan")
        execution = create_execution(task, start, end)
        self._executions.save(execution)
        return execution

    def take_snapshot(self, goal_id: uuid.UUID) -> ProgressBundle:
        """Take one progress snapshot of the goal's plan, now, and
        append it to the history.

        Raises :class:`TaskEstimationError` (as the domain does)
        when the plan has unestimated tasks — unknown workload
        means no derivable progress.
        """
        plan = self._plan_for(goal_id)
        tasks = tuple(self._tasks.list_for_plan(plan.plan_id))
        executions = self._executions_for_plan(plan)
        snapshot = take_progress_snapshot(plan, tasks, executions)
        self._snapshots.save(snapshot)
        return ProgressBundle(snapshot=snapshot, plan=plan)

    def get_latest(self, goal_id: uuid.UUID) -> ProgressBundle | None:
        """The latest snapshot of the goal's plan, or ``None`` when
        none has been taken."""
        plans = self._plans.list_for_goal(goal_id)
        if not plans:
            return None
        plan = plans[-1]
        snapshots = self._snapshots.list_for_plan(plan.plan_id)
        if not snapshots:
            return None
        return ProgressBundle(snapshot=snapshots[-1], plan=plan)

    def _plan_for(self, goal_id: uuid.UUID) -> Plan:
        if self._goals.get(goal_id) is None:
            raise GoalNotFoundError(f"no goal {goal_id}")
        plans = self._plans.list_for_goal(goal_id)
        if not plans:
            raise NoPlanError(f"no plan for goal {goal_id}")
        return plans[-1]

    def _executions_for_plan(self, plan: Plan) -> tuple[Execution, ...]:
        executions: list[Execution] = []
        for task in self._tasks.list_for_plan(plan.plan_id):
            executions.extend(self._executions.list_for_task(task.task_id))
        return tuple(executions)
