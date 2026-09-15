"""Plan generation.

The assembly half of the planning pipeline's tail (docs/04): steps
11–12 accept proposed outcomes and tasks onto a plan, and "Publish
plan" (step 15) turns the assembled draft into a CANDIDATE — the
lifecycle's staging state before validation (TASK-056) can promote it
to ACTIVE ("DRAFT/CANDIDATE → ACTIVE", docs/03).

Generation is a two-phase contract:

- :func:`begin_plan` opens a DRAFT plan from a COMPLETED backcasting
  run — the run is the provenance: its selected strategy, milestone
  path, and gap analysis are what the plan executes, and ``run_id``
  records where the plan was born (docs/08 plan versioning reads this
  provenance back as ``source_run_id``).
- :func:`publish_plan` closes the draft: it computes the workload as
  the sum of the tasks' estimates (:func:`estimate_workload` — every
  task must carry one), stamps it onto the plan, and moves DRAFT →
  CANDIDATE. A draft with no tasks cannot publish: a plan with nothing
  to execute is not a plan, and an outcome without tasks stays
  outcome-level state (docs/03), never a plan.

:func:`generate_plan` composes the accept and publish phases over a
begun draft — the step-11/12/15 path. Per ADR-002 nothing here
generates content: the proposals arrive from outside, and the domain
only assembles, computes, and enforces.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from backcasting.domain.backcasting_run import BackcastingRun, BackcastingRunStatus
from backcasting.domain.goal import Goal
from backcasting.domain.outcome import Outcome
from backcasting.domain.plan import (
    Plan,
    PlanStatus,
    create_plan,
    revise_plan,
    transition_plan,
)
from backcasting.domain.task import Task, TaskProposal, accept_proposed_tasks
from backcasting.domain.task_estimation import estimate_workload


class PlanGenerationError(ValueError):
    """Raised when a plan-generation invariant is violated."""


def begin_plan(
    run: BackcastingRun,
    goal: Goal,
    *,
    title: str = "",
    plan_id: uuid.UUID | None = None,
    at: datetime | None = None,
) -> Plan:
    """Open a DRAFT plan executing ``run``'s products for ``goal``.

    The run must be COMPLETED — plans are published from finished
    backcasting, not mid-flight — and the goal must be the run's own.
    """
    if not isinstance(run, BackcastingRun):
        raise TypeError("run must be a BackcastingRun")
    if not isinstance(goal, Goal):
        raise TypeError("goal must be a Goal")
    if run.status is not BackcastingRunStatus.COMPLETED:
        raise PlanGenerationError(
            f"cannot begin a plan from a run with status {run.status.value}"
        )
    if run.goal_id != goal.goal_id:
        raise PlanGenerationError("run does not belong to this goal")
    return create_plan(
        goal,
        workload=timedelta(0),
        title=title,
        run_id=run.run_id,
        plan_id=plan_id,
        created_at=at,
    )


def publish_plan(
    plan: Plan,
    tasks: tuple[Task, ...],
    *,
    at: datetime | None = None,
) -> Plan:
    """Close ``plan`` into a CANDIDATE with its workload computed.

    Deterministic rules:

    - The plan must still be a DRAFT — a CANDIDATE is already
      published, and later lifecycle states cannot re-publish.
    - Every task must belong to the plan.
    - At least one task must be supplied — an empty plan executes
      nothing.
    - Every task must carry a duration estimate; the published
      workload is the sum (:func:`estimate_workload` refuses to sum
      over unestimated tasks).
    """
    if not isinstance(plan, Plan):
        raise TypeError("plan must be a Plan")
    if not isinstance(tasks, tuple):
        raise PlanGenerationError("tasks must be a tuple of Task")
    for task in tasks:
        if not isinstance(task, Task):
            raise PlanGenerationError("tasks must be Task instances")
        if task.plan_id != plan.plan_id:
            raise PlanGenerationError("task does not belong to this plan")
    if plan.status is not PlanStatus.DRAFT:
        raise PlanGenerationError(
            f"cannot publish a plan with status {plan.status.value}"
        )
    if not tasks:
        raise PlanGenerationError("a published plan needs at least one task")
    now = at if at is not None else datetime.now(timezone.utc)
    workload = estimate_workload(tasks)
    stamped = revise_plan(plan, workload=workload, updated_at=now)
    return transition_plan(stamped, PlanStatus.CANDIDATE, at=now)


def generate_plan(
    draft: Plan,
    outcomes: tuple[Outcome, ...],
    proposals: tuple[TaskProposal, ...],
    *,
    at: datetime | None = None,
) -> Plan:
    """Assemble and publish a CANDIDATE plan from a begun draft.

    The step-11/12/15 composition over one draft: accept the proposed
    tasks (bound to their outcomes — themselves defined on the draft),
    then publish. Nothing is generated here — the proposals arrive
    from outside (ADR-002); use :func:`begin_plan` to open the draft
    with run provenance first.
    """
    if not isinstance(draft, Plan):
        raise TypeError("draft must be a Plan")
    tasks = accept_proposed_tasks(draft, outcomes, proposals, at=at)
    return publish_plan(draft, tasks, at=at)
