"""Replanning use cases (TASK-115) — docs/08's level 2, driven by hand.

The replanning ladder's middle level: modify the execution plan while
the Goal and Future stay untouched. The deterministic scopes live in
``backcasting.domain.local_replan`` / ``global_replan`` (regional
needs the dependency graph, which the product does not surface yet);
this service wires them to the ports and records the trace every
meaningful replan owes (``plan_version``, TASK-048).

Replanning targets a plan *past assembly*: while a plan is a DRAFT
its content is still freely editable (TASK-112) — there is nothing
to trace yet, so the service refuses and points at revision. The
workload rules are the domain's: a local replan *shifts* the
declared workload by the estimate's delta, a global replan
*recomputes* it from the task set.

Modes (docs/08) are Manual here: Suggest and Automatic route through
the decision engine (TASK-084) — the reasoning pipeline, not this
surface. Goal revision is level 3 and stays the user's.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from backcasting.application.goals import GoalNotFoundError
from backcasting.application.plans import NoPlanError, NoTaskError
from backcasting.domain.global_replan import replan_plan_globally
from backcasting.domain.local_replan import replan_task_locally
from backcasting.domain.plan import Plan, PlanStatus
from backcasting.domain.plan_version import PlanVersion
from backcasting.domain.repositories import (
    GoalRepository,
    PlanRepository,
    PlanVersionRepository,
    TaskRepository,
)
from backcasting.domain.task import Task
from backcasting.domain.timezone import UTC


class PlanIsDraftError(Exception):
    """Raised when a replan targets a plan still in assembly — a
    DRAFT's content is editable outright (TASK-112); there is nothing
    to trace yet."""


@dataclass(frozen=True)
class LocalReplanBundle:
    """The outcome of one local replan: the plan after the revision,
    the revised task, and the version tracing it."""

    plan: Plan
    task: Task
    version: PlanVersion


@dataclass(frozen=True)
class GlobalReplanBundle:
    """The outcome of one global replan: the re-derived plan and the
    version tracing it."""

    plan: Plan
    version: PlanVersion


class ReplanningService:
    """Replan a goal's plan by hand, with the trace kept."""

    def __init__(
        self,
        goals: GoalRepository,
        plans: PlanRepository,
        tasks: TaskRepository,
        versions: PlanVersionRepository,
    ) -> None:
        self._goals = goals
        self._plans = plans
        self._tasks = tasks
        self._versions = versions

    def replan_task(
        self,
        *,
        goal_id: uuid.UUID,
        task_id: uuid.UUID,
        reason: str,
        title: str | None = None,
        description: str | None = None,
        duration_hours: float | None = None,
        deadline: datetime | None = None,
    ) -> LocalReplanBundle:
        """Revise one task of the goal's plan in place (LOCAL scope).

        ``None`` fields keep their current value (the domain's
        ``revise_task`` semantics). The plan's workload shifts by the
        estimate's delta; the change is traced as a plan version
        naming the revised task.

        Raises :class:`GoalNotFoundError` / :class:`NoPlanError` /
        :class:`NoTaskError` when there is nothing to replan,
        :class:`PlanIsDraftError` while the plan is still a DRAFT,
        and the domain's :class:`~backcasting.domain.local_replan.LocalReplanError`
        when the revision changes nothing.
        """
        plan = self._planned_for(goal_id)
        task = self._tasks.get(task_id)
        if task is None or task.plan_id != plan.plan_id:
            raise NoTaskError(f"no task {task_id} on this plan")
        duration = (
            timedelta(hours=duration_hours)
            if duration_hours is not None
            else None
        )
        outcome = replan_task_locally(
            plan,
            tuple(self._versions.list_for_plan(plan.plan_id)),
            task,
            reason=reason,
            updated_at=datetime.now(UTC),
            title=title,
            description=description,
            duration=duration,
            deadline=deadline,
        )
        self._plans.save(outcome.plan)
        self._tasks.save(outcome.task)
        self._versions.save(outcome.version)
        return LocalReplanBundle(
            plan=outcome.plan, task=outcome.task, version=outcome.version
        )

    def replan_globally(
        self,
        *,
        goal_id: uuid.UUID,
        reason: str,
        title: str | None = None,
    ) -> GlobalReplanBundle:
        """Re-derive the goal's plan from its task set (GLOBAL scope).

        The workload is recomputed — every task must carry an
        estimate (:class:`~backcasting.domain.task_estimation.TaskEstimationError`
        otherwise) — and the plan may take a new title. A
        re-derivation that lands where the plan already stands is
        rejected by the domain.
        """
        plan = self._planned_for(goal_id)
        tasks = tuple(self._tasks.list_for_plan(plan.plan_id))
        outcome = replan_plan_globally(
            plan,
            tuple(self._versions.list_for_plan(plan.plan_id)),
            tasks,
            reason=reason,
            title=title,
        )
        self._plans.save(outcome.plan)
        self._versions.save(outcome.version)
        return GlobalReplanBundle(
            plan=outcome.plan, version=outcome.version
        )

    def list_versions(
        self, goal_id: uuid.UUID
    ) -> tuple[PlanVersion, ...]:
        """The goal's plan's version trail — how the plan got where it
        stands. Empty while no replan has happened; the plan's own
        publication is not a version (it is assembly, not a replan)."""
        plan = self._plan_for(goal_id)
        return tuple(self._versions.list_for_plan(plan.plan_id))

    def _planned_for(self, goal_id: uuid.UUID) -> Plan:
        """The goal's latest plan, required to be past assembly."""
        plan = self._plan_for(goal_id)
        if plan.status is PlanStatus.DRAFT:
            raise PlanIsDraftError(
                "plan is a draft — revise it in assembly, or publish first"
            )
        return plan

    def _plan_for(self, goal_id: uuid.UUID) -> Plan:
        if self._goals.get(goal_id) is None:
            raise GoalNotFoundError(f"no goal {goal_id}")
        plans = self._plans.list_for_goal(goal_id)
        if not plans:
            raise NoPlanError(f"no plan for goal {goal_id}")
        return plans[-1]
