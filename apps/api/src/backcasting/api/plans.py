"""Plan HTTP API (TASK-111).

Exposes the plan use cases (``backcasting.application.plans`` —
docs/04 steps 11–12 and 15) over HTTP, scoped under the goal the
plan executes for. TASK-112 adds task revision: assembly-time
editing of a task on the DRAFT plan.

Status mapping:

- unknown goal, no run to plan from, no plan yet, or a task that is
  not on the goal's plan → 404
- a second plan for a goal, or assembly on a published plan → 409
- domain violations (blank titles, non-positive durations,
  publishing without estimated tasks) → 422
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import AwareDatetime, BaseModel, Field

from backcasting.application.goals import GoalNotFoundError
from backcasting.application.milestones import NoBackcastRunError
from backcasting.application.plans import (
    NoPlanError,
    NoTaskError,
    PlanAlreadyExistsError,
    PlanBundle,
    PlanNotDraftError,
    PlanService,
)
from backcasting.domain.milestone import MilestoneError
from backcasting.domain.outcome import Outcome, OutcomeError
from backcasting.domain.plan import Plan, PlanError
from backcasting.domain.plan_generation import PlanGenerationError
from backcasting.domain.task import Task, TaskError
from backcasting.domain.task_estimation import TaskEstimationError

router = APIRouter(tags=["plans"])


def _service(request: Request) -> PlanService:
    return request.app.state.plan_service


class PlanBegin(BaseModel):
    title: str = ""


class OutcomeCreate(BaseModel):
    title: str
    description: str = ""
    milestone_id: uuid.UUID | None = None


class TaskCreate(BaseModel):
    title: str
    description: str = ""
    duration_hours: float | None = Field(default=None, gt=0)
    deadline: AwareDatetime | None = None
    outcome_ids: list[uuid.UUID] = []


class TaskRevise(BaseModel):
    """A task revision (TASK-112): omitted fields keep their current
    value — the domain's ``revise_task`` semantics."""

    title: str | None = None
    description: str | None = None
    duration_hours: float | None = Field(default=None, gt=0)
    deadline: AwareDatetime | None = None


class PlanResponse(BaseModel):
    plan_id: uuid.UUID
    goal_id: uuid.UUID
    run_id: uuid.UUID | None
    title: str
    status: str
    workload_hours: float
    created_at: str
    updated_at: str


class OutcomeResponse(BaseModel):
    outcome_id: uuid.UUID
    plan_id: uuid.UUID
    title: str
    description: str
    milestone_id: uuid.UUID | None
    created_at: str
    updated_at: str


class TaskResponse(BaseModel):
    task_id: uuid.UUID
    plan_id: uuid.UUID
    title: str
    description: str
    duration_hours: float | None
    deadline: str | None
    outcome_ids: list[uuid.UUID]
    created_at: str
    updated_at: str


class PlanBundleResponse(BaseModel):
    """A plan with its outcomes and tasks — the plan UI's view."""

    plan: PlanResponse
    outcomes: list[OutcomeResponse]
    tasks: list[TaskResponse]


def _hours(delta) -> float:
    return delta.total_seconds() / 3600


def _plan_response(plan: Plan) -> PlanResponse:
    return PlanResponse(
        plan_id=plan.plan_id,
        goal_id=plan.goal_id,
        run_id=plan.run_id,
        title=plan.title,
        status=plan.status.value,
        workload_hours=_hours(plan.workload),
        created_at=plan.created_at.isoformat(),
        updated_at=plan.updated_at.isoformat(),
    )


def _outcome_response(outcome: Outcome) -> OutcomeResponse:
    return OutcomeResponse(
        outcome_id=outcome.outcome_id,
        plan_id=outcome.plan_id,
        title=outcome.title,
        description=outcome.description,
        milestone_id=outcome.milestone_id,
        created_at=outcome.created_at.isoformat(),
        updated_at=outcome.updated_at.isoformat(),
    )


def _task_response(task: Task) -> TaskResponse:
    return TaskResponse(
        task_id=task.task_id,
        plan_id=task.plan_id,
        title=task.title,
        description=task.description,
        duration_hours=(
            _hours(task.duration) if task.duration is not None else None
        ),
        deadline=task.deadline.isoformat() if task.deadline else None,
        outcome_ids=sorted(task.outcome_ids),
        created_at=task.created_at.isoformat(),
        updated_at=task.updated_at.isoformat(),
    )


def _bundle_response(bundle: PlanBundle) -> PlanBundleResponse:
    return PlanBundleResponse(
        plan=_plan_response(bundle.plan),
        outcomes=[_outcome_response(o) for o in bundle.outcomes],
        tasks=[_task_response(t) for t in bundle.tasks],
    )


_NOT_FOUND = (GoalNotFoundError, NoBackcastRunError, NoPlanError, NoTaskError)
_CONFLICT = (PlanAlreadyExistsError, PlanNotDraftError)
_DOMAIN_ERRORS = (
    PlanError,
    PlanGenerationError,
    OutcomeError,
    TaskError,
    TaskEstimationError,
    MilestoneError,
)


@router.post(
    "/goals/{goal_id}/plan",
    status_code=status.HTTP_201_CREATED,
    operation_id="beginPlan",
    response_model=PlanBundleResponse,
)
def begin_plan(
    goal_id: uuid.UUID, payload: PlanBegin, request: Request
) -> PlanBundleResponse:
    """Finish the goal's backcasting run and open a DRAFT plan from
    it (docs/04 steps 11–12)."""
    try:
        bundle = _service(request).begin_plan(
            goal_id=goal_id, title=payload.title
        )
    except _NOT_FOUND as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except _CONFLICT as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except _DOMAIN_ERRORS as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _bundle_response(bundle)


@router.get(
    "/goals/{goal_id}/plan",
    operation_id="getPlan",
    response_model=PlanBundleResponse,
)
def get_plan(goal_id: uuid.UUID, request: Request) -> PlanBundleResponse:
    """The goal's plan with its outcomes and tasks, or 404 while
    none has been begun."""
    bundle = _service(request).get_plan(goal_id)
    if bundle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no plan for goal {goal_id}",
        )
    return _bundle_response(bundle)


@router.post(
    "/goals/{goal_id}/plan/outcomes",
    status_code=status.HTTP_201_CREATED,
    operation_id="addOutcome",
    response_model=OutcomeResponse,
)
def add_outcome(
    goal_id: uuid.UUID, payload: OutcomeCreate, request: Request
) -> OutcomeResponse:
    """Define an outcome on the goal's DRAFT plan (docs/04 step 11),
    optionally bound to one of the goal's milestones."""
    try:
        outcome = _service(request).add_outcome(
            goal_id=goal_id,
            title=payload.title,
            description=payload.description,
            milestone_id=payload.milestone_id,
        )
    except _NOT_FOUND as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except _CONFLICT as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except _DOMAIN_ERRORS as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _outcome_response(outcome)


@router.post(
    "/goals/{goal_id}/plan/tasks",
    status_code=status.HTTP_201_CREATED,
    operation_id="addTask",
    response_model=TaskResponse,
)
def add_task(
    goal_id: uuid.UUID, payload: TaskCreate, request: Request
) -> TaskResponse:
    """Add a task to the goal's DRAFT plan (docs/04 step 12),
    optionally serving outcomes defined on it."""
    try:
        task = _service(request).add_task(
            goal_id=goal_id,
            title=payload.title,
            description=payload.description,
            duration_hours=payload.duration_hours,
            deadline=payload.deadline,
            outcome_ids=tuple(payload.outcome_ids),
        )
    except _NOT_FOUND as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except _CONFLICT as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except _DOMAIN_ERRORS as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _task_response(task)


@router.patch(
    "/goals/{goal_id}/plan/tasks/{task_id}",
    operation_id="reviseTask",
    response_model=TaskResponse,
)
def revise_task(
    goal_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: TaskRevise,
    request: Request,
) -> TaskResponse:
    """Revise a task on the goal's DRAFT plan (TASK-112) —
    assembly-time editing; omitted fields keep their value. Revising
    a published plan's task is the replanning ladder's concern
    (docs/08), not this endpoint's."""
    try:
        task = _service(request).revise_task(
            goal_id=goal_id,
            task_id=task_id,
            title=payload.title,
            description=payload.description,
            duration_hours=payload.duration_hours,
            deadline=payload.deadline,
        )
    except _NOT_FOUND as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except _CONFLICT as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except _DOMAIN_ERRORS as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _task_response(task)


@router.post(
    "/goals/{goal_id}/plan/publish",
    operation_id="publishPlan",
    response_model=PlanBundleResponse,
)
def publish_plan(
    goal_id: uuid.UUID, request: Request
) -> PlanBundleResponse:
    """Close the goal's DRAFT plan into a CANDIDATE with its
    workload computed (docs/04 step 15)."""
    try:
        bundle = _service(request).publish(goal_id)
    except _NOT_FOUND as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except _CONFLICT as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except _DOMAIN_ERRORS as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _bundle_response(bundle)
