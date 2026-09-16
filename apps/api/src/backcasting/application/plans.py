"""Plan use cases (TASK-111) — the planning pipeline's tail.

``docs/04-BACKCASTING-MODEL.md`` steps 11–12 and 15: a plan is
begun from a *finished* backcasting run (the run is the
provenance), outcomes are defined on the draft (optionally bound to
milestones), tasks are added to execute them, and publishing closes
the draft into a CANDIDATE with its workload computed as the sum of
the task estimates. The deterministic rules live in
``backcasting.domain.plan_generation`` / ``plan`` / ``outcome`` /
``task``; this service wires them to the ports.

Beginning a plan finishes the goal's RUNNING run first — declaring
the backcast complete is what "now we plan" means in the MVP (the
AI-driven pipeline, TASK-116, will drive the same transition with
generated content). One plan per goal; versioned successors arrive
with replanning (docs/08).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from backcasting.application.goals import GoalNotFoundError
from backcasting.application.milestones import NoBackcastRunError
from backcasting.domain.backcasting_run import (
    BackcastingRunStatus,
    complete_run,
)
from backcasting.domain.milestone import MilestoneError
from backcasting.domain.outcome import Outcome, define_outcome
from backcasting.domain.plan import Plan, PlanStatus
from backcasting.domain.plan_generation import (
    PlanGenerationError,
    begin_plan,
    publish_plan,
)
from backcasting.domain.repositories import (
    BackcastingRunRepository,
    GoalRepository,
    MilestoneRepository,
    OutcomeRepository,
    PlanRepository,
    TaskRepository,
)
from backcasting.domain.task import (
    Task,
    create_task,
    revise_task,
    serve_outcomes,
)


class PlanAlreadyExistsError(Exception):
    """Raised when a goal already has a plan (one per goal in the
    MVP; versioned successors arrive with replanning)."""


class NoPlanError(LookupError):
    """Raised when a goal has no plan to work on (begin one first)."""


class PlanNotDraftError(Exception):
    """Raised when an assembly step targets a plan that is no longer
    a DRAFT — a published plan is frozen; changes arrive as a new
    plan version."""


class NoTaskError(LookupError):
    """Raised when a task revision names a task that is not on the
    goal's plan."""


@dataclass(frozen=True)
class PlanBundle:
    """A plan with its outcomes and tasks — the plan UI's view."""

    plan: Plan
    outcomes: tuple[Outcome, ...]
    tasks: tuple[Task, ...]


class PlanService:
    """Begin, assemble, publish, and read a goal's plan."""

    def __init__(
        self,
        goals: GoalRepository,
        runs: BackcastingRunRepository,
        plans: PlanRepository,
        outcomes: OutcomeRepository,
        tasks: TaskRepository,
        milestones: MilestoneRepository,
    ) -> None:
        self._goals = goals
        self._runs = runs
        self._plans = plans
        self._outcomes = outcomes
        self._tasks = tasks
        self._milestones = milestones

    def begin_plan(
        self, *, goal_id: uuid.UUID, title: str = ""
    ) -> PlanBundle:
        """Finish the goal's run and open a DRAFT plan from it.

        Raises :class:`GoalNotFoundError` /
        :class:`NoBackcastRunError` when there is nothing to plan
        from, :class:`PlanAlreadyExistsError` when the goal already
        has a plan, and :class:`PlanGenerationError` when the domain
        refuses.
        """
        goal = self._goals.get(goal_id)
        if goal is None:
            raise GoalNotFoundError(f"no goal {goal_id}")
        run = self._runs.latest_for_goal(goal_id)
        if run is None:
            raise NoBackcastRunError(f"no backcasting run for goal {goal_id}")
        if self._plans.list_for_goal(goal_id):
            raise PlanAlreadyExistsError(
                "goal already has a plan (one per goal in the MVP)"
            )
        if run.status is BackcastingRunStatus.RUNNING:
            finished = complete_run(
                run, completed_at=datetime.now(timezone.utc)
            )
            self._runs.save(finished)
            run = finished
        plan = begin_plan(run, goal, title=title)
        self._plans.save(plan)
        return self._bundle(plan)

    def add_outcome(
        self,
        *,
        goal_id: uuid.UUID,
        title: str,
        description: str = "",
        milestone_id: uuid.UUID | None = None,
    ) -> Outcome:
        """Define an outcome on the goal's DRAFT plan, optionally
        bound to one of the goal's milestones."""
        plan = self._draft_for(goal_id)
        milestone = None
        if milestone_id is not None:
            milestone = self._milestones.get(milestone_id)
            if milestone is None or milestone.goal_id != goal_id:
                raise MilestoneError(
                    f"no milestone {milestone_id} for goal {goal_id}"
                )
        outcome = define_outcome(
            plan, title, description=description, milestone=milestone
        )
        self._outcomes.save(outcome)
        return outcome

    def add_task(
        self,
        *,
        goal_id: uuid.UUID,
        title: str,
        description: str = "",
        duration_hours: float | None = None,
        deadline: datetime | None = None,
        outcome_ids: tuple[uuid.UUID, ...] = (),
    ) -> Task:
        """Add a task to the goal's DRAFT plan, optionally serving
        outcomes already defined on it."""
        plan = self._draft_for(goal_id)
        duration = (
            timedelta(hours=duration_hours)
            if duration_hours is not None
            else None
        )
        task = create_task(
            plan,
            title,
            description=description,
            duration=duration,
            deadline=deadline,
        )
        if outcome_ids:
            outcomes = []
            for outcome_id in outcome_ids:
                outcome = self._outcomes.get(outcome_id)
                if outcome is None or outcome.plan_id != plan.plan_id:
                    raise PlanGenerationError(
                        f"no outcome {outcome_id} on this plan"
                    )
                outcomes.append(outcome)
            task = serve_outcomes(
                task,
                tuple(outcomes),
                updated_at=task.created_at,
            )
        self._tasks.save(task)
        return task

    def revise_task(
        self,
        *,
        goal_id: uuid.UUID,
        task_id: uuid.UUID,
        title: str | None = None,
        description: str | None = None,
        duration_hours: float | None = None,
        deadline: datetime | None = None,
    ) -> Task:
        """Revise a task on the goal's DRAFT plan (TASK-112).

        Assembly-time editing: ``None`` fields keep their current
        value (the domain's :func:`~backcasting.domain.task.revise_task`
        semantics — clearing a duration or deadline is an explicit
        reset the domain does not offer). The plan's workload is
        untouched here; it is (re)computed at publish. Revising a
        published plan's task is the replanning ladder's LOCAL scope
        (docs/08) with a traced version — a different use case, not
        this one.

        Raises :class:`NoTaskError` when the task is not on this
        goal's plan and :class:`PlanNotDraftError` when the plan is
        no longer a draft.
        """
        plan = self._draft_for(goal_id)
        task = self._tasks.get(task_id)
        if task is None or task.plan_id != plan.plan_id:
            raise NoTaskError(f"no task {task_id} on this plan")
        duration = (
            timedelta(hours=duration_hours)
            if duration_hours is not None
            else None
        )
        revised = revise_task(
            task,
            updated_at=datetime.now(timezone.utc),
            title=title,
            description=description,
            duration=duration,
            deadline=deadline,
        )
        self._tasks.save(revised)
        return revised

    def publish(self, goal_id: uuid.UUID) -> PlanBundle:
        """Close the goal's DRAFT plan into a CANDIDATE with its
        workload computed (every task estimated, at least one)."""
        plan = self._draft_for(goal_id)
        tasks = tuple(self._tasks.list_for_plan(plan.plan_id))
        published = publish_plan(plan, tasks)
        self._plans.save(published)
        return PlanBundle(
            plan=published,
            outcomes=tuple(self._outcomes.list_for_plan(plan.plan_id)),
            tasks=tasks,
        )

    def get_plan(self, goal_id: uuid.UUID) -> PlanBundle | None:
        """The goal's plan with its outcomes and tasks, or ``None``
        when none has been begun."""
        plans = self._plans.list_for_goal(goal_id)
        if not plans:
            return None
        plan = plans[-1]
        return self._bundle(plan)

    def _bundle(self, plan: Plan) -> PlanBundle:
        return PlanBundle(
            plan=plan,
            outcomes=tuple(self._outcomes.list_for_plan(plan.plan_id)),
            tasks=tuple(self._tasks.list_for_plan(plan.plan_id)),
        )

    def _draft_for(self, goal_id: uuid.UUID) -> Plan:
        if self._goals.get(goal_id) is None:
            raise GoalNotFoundError(f"no goal {goal_id}")
        plans = self._plans.list_for_goal(goal_id)
        if not plans:
            raise NoPlanError(f"no plan for goal {goal_id}")
        plan = plans[-1]
        if plan.status is not PlanStatus.DRAFT:
            raise PlanNotDraftError(
                f"plan is {plan.status.value}, not a draft"
            )
        return plan
