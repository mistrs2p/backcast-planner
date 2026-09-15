"""Plan validation.

Pipeline step 14, "Validate" (docs/04), closes the planning loop:
before a CANDIDATE plan can be promoted to ACTIVE ("DRAFT/CANDIDATE
→ ACTIVE", docs/03), the domain checks the plan as a *whole* — the
cross-entity rules no single constructor can see, in the style of
:mod:`backcasting.domain.validation` (every issue is returned
together; an empty list means valid).

Checks performed by :func:`validate_plan`:

- ``task_owner_mismatch`` — every task must belong to the plan.
- ``empty_plan`` — a plan with no tasks cannot be activated.
- ``unestimated_task`` — every task must carry a duration estimate;
  an unestimated task is not schedulable.
- ``workload_mismatch`` — the plan's recorded workload must equal the
  sum of its tasks' estimates; drift means the tasks changed after
  publication.
- ``dependency_reference_outside`` — a dependency link must reference
  tasks in the collection.
- ``dependency_cycle`` — the dependency graph must be acyclic.
- ``infeasible`` — the spec rule "Required Workload + Buffer ≤ usable
  Capacity" (docs/04) must hold against the supplied usable capacity.

:func:`activate_plan` then applies the promotion gate: only a
CANDIDATE can activate, and the "Goal max 1 Active Plan" rule
(docs/03) must hold — another active plan must be superseded or
archived first.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from backcasting.domain.feasibility import evaluate_feasibility
from backcasting.domain.plan import Plan, PlanStatus, transition_plan
from backcasting.domain.task import Task
from backcasting.domain.task_dependency import (
    TaskDependency,
    TaskDependencyError,
    topological_order,
)
from backcasting.domain.validation import ValidationIssue

TASK_OWNER_MISMATCH = "task_owner_mismatch"
EMPTY_PLAN = "empty_plan"
UNESTIMATED_TASK = "unestimated_task"
WORKLOAD_MISMATCH = "workload_mismatch"
DEPENDENCY_REFERENCE_OUTSIDE = "dependency_reference_outside"
DEPENDENCY_CYCLE = "dependency_cycle"
INFEASIBLE = "infeasible"


class PlanValidationError(ValueError):
    """Raised by :func:`activate_plan` when the promotion gate fails."""


def validate_plan(
    plan: Plan,
    tasks: tuple[Task, ...],
    dependencies: tuple[TaskDependency, ...],
    *,
    usable_capacity: timedelta,
    buffer: timedelta = timedelta(0),
) -> list[ValidationIssue]:
    """Validate a plan as a whole (pipeline step 14).

    Returns all issues found; an empty list means the plan is valid to
    activate. ``usable_capacity`` is the capacity the plan must fit
    into (the ``usable_amount`` of a capacity analysis), and
    ``buffer`` the reserve kept aside — together they feed the spec's
    feasibility rule.
    """
    if not isinstance(plan, Plan):
        raise TypeError("plan must be a Plan")
    if not isinstance(tasks, tuple):
        raise PlanValidationError("tasks must be a tuple of Task")
    for task in tasks:
        if not isinstance(task, Task):
            raise PlanValidationError("tasks must be Task instances")
    if not isinstance(dependencies, tuple):
        raise PlanValidationError("dependencies must be a tuple of TaskDependency")

    issues: list[ValidationIssue] = []
    for task in tasks:
        if task.plan_id != plan.plan_id:
            issues.append(
                ValidationIssue(
                    TASK_OWNER_MISMATCH,
                    f"task {task.task_id} ({task.title!r}) belongs to plan "
                    f"{task.plan_id}, not {plan.plan_id}",
                )
            )
    if not tasks:
        issues.append(
            ValidationIssue(EMPTY_PLAN, "a plan with no tasks cannot be activated")
        )
    else:
        for task in tasks:
            if task.duration is None:
                issues.append(
                    ValidationIssue(
                        UNESTIMATED_TASK,
                        f"task {task.task_id} ({task.title!r}) has no duration "
                        "estimate",
                    )
                )
        workload = sum(
            (task.duration for task in tasks if task.duration is not None),
            start=timedelta(0),
        )
        if workload != plan.workload:
            issues.append(
                ValidationIssue(
                    WORKLOAD_MISMATCH,
                    f"plan workload {plan.workload} does not match the sum of "
                    f"its tasks' estimates {workload}",
                )
            )
    if dependencies:
        try:
            topological_order(tasks, dependencies)
        except TaskDependencyError as error:
            code = (
                DEPENDENCY_CYCLE
                if "cycle" in str(error)
                else DEPENDENCY_REFERENCE_OUTSIDE
            )
            issues.append(ValidationIssue(code, str(error)))
    feasibility = evaluate_feasibility(plan.workload, buffer, usable_capacity)
    if not feasibility.feasible:
        issues.append(
            ValidationIssue(
                INFEASIBLE,
                f"required {feasibility.total_required} (workload "
                f"{plan.workload} + buffer {buffer}) exceeds usable capacity "
                f"{usable_capacity}; slack {feasibility.slack}",
            )
        )
    return issues


def activate_plan(
    plan: Plan,
    other_plans: tuple[Plan, ...],
    *,
    at: datetime | None = None,
) -> Plan:
    """Promote a CANDIDATE plan to ACTIVE (the step-14/15 gate).

    Deterministic rules:

    - The plan must be a CANDIDATE — validation is what a candidate is
      for; a DRAFT must publish first, and an ACTIVE plan is already
      active.
    - "Goal max 1 Active Plan" (docs/03): no other plan of the same
      goal may be ACTIVE — supersede or archive it first.

    Whether the plan *passed* validation is the caller's contract:
    run :func:`validate_plan` (and act on its issues) before calling
    this. The gate here enforces lifecycle and exclusivity, not the
    content rules.
    """
    if not isinstance(plan, Plan):
        raise TypeError("plan must be a Plan")
    if not isinstance(other_plans, tuple):
        raise PlanValidationError("other_plans must be a tuple of Plan")
    for other in other_plans:
        if not isinstance(other, Plan):
            raise PlanValidationError("other_plans must be Plan instances")
    if plan.status is not PlanStatus.CANDIDATE:
        raise PlanValidationError(
            f"cannot activate a plan with status {plan.status.value}"
        )
    for other in other_plans:
        if other.plan_id == plan.plan_id:
            continue
        if other.goal_id == plan.goal_id and other.status is PlanStatus.ACTIVE:
            raise PlanValidationError(
                f"goal {plan.goal_id} already has an active plan "
                f"({other.plan_id}); supersede or archive it first"
            )
    return transition_plan(plan, PlanStatus.ACTIVE, at=at)
