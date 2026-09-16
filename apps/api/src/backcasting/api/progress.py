"""Progress HTTP API (TASK-114).

Exposes the Actual side of docs/07's triad over HTTP, scoped under
the goal whose plan is being executed: recording sittings of work
and reading/taking progress snapshots.

Status mapping:

- unknown goal, no plan, no task on the plan, or no snapshot yet
  → 404
- domain violations (end before start, naive datetimes, snapshot
  over unestimated tasks) → 422
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import AwareDatetime, BaseModel

from backcasting.application.goals import GoalNotFoundError
from backcasting.application.progress import (
    NoPlanError,
    NoSnapshotError,
    NoTaskError,
    ProgressBundle,
    ProgressService,
)
from backcasting.domain.execution import Execution, ExecutionError
from backcasting.domain.plan import Plan
from backcasting.domain.progress import ProgressSnapshot
from backcasting.domain.task_estimation import TaskEstimationError

router = APIRouter(tags=["progress"])


def _service(request: Request) -> ProgressService:
    return request.app.state.progress_service


class ExecutionCreate(BaseModel):
    task_id: uuid.UUID
    start: AwareDatetime
    end: AwareDatetime


class ExecutionResponse(BaseModel):
    execution_id: uuid.UUID
    task_id: uuid.UUID
    start: str
    end: str
    created_at: str


class ProgressResponse(BaseModel):
    """A snapshot plus the plan's workload basis (hours)."""

    snapshot_id: uuid.UUID
    plan_id: uuid.UUID
    taken_at: str
    task_count: int
    completed_task_count: int
    planned_hours: float
    actual_hours: float
    remaining_hours: float
    progress: float
    completion_rate: float
    plan_status: str
    plan_workload_hours: float


def _hours(delta) -> float:
    return delta.total_seconds() / 3600


def _execution_response(execution: Execution) -> ExecutionResponse:
    return ExecutionResponse(
        execution_id=execution.execution_id,
        task_id=execution.task_id,
        start=execution.start.isoformat(),
        end=execution.end.isoformat(),
        created_at=execution.created_at.isoformat(),
    )


def _progress_response(bundle: ProgressBundle) -> ProgressResponse:
    snapshot: ProgressSnapshot = bundle.snapshot
    plan: Plan = bundle.plan
    return ProgressResponse(
        snapshot_id=snapshot.snapshot_id,
        plan_id=snapshot.plan_id,
        taken_at=snapshot.taken_at.isoformat(),
        task_count=snapshot.task_count,
        completed_task_count=snapshot.completed_task_count,
        planned_hours=_hours(snapshot.planned),
        actual_hours=_hours(snapshot.actual),
        remaining_hours=_hours(snapshot.remaining),
        progress=snapshot.progress,
        completion_rate=snapshot.completion_rate,
        plan_status=plan.status.value,
        plan_workload_hours=_hours(plan.workload),
    )


_NOT_FOUND = (GoalNotFoundError, NoPlanError, NoTaskError, NoSnapshotError)
_DOMAIN_ERRORS = (ExecutionError, TaskEstimationError)


@router.post(
    "/goals/{goal_id}/executions",
    status_code=status.HTTP_201_CREATED,
    operation_id="recordExecution",
    response_model=ExecutionResponse,
)
def record_execution(
    goal_id: uuid.UUID, payload: ExecutionCreate, request: Request
) -> ExecutionResponse:
    """Record one sitting of actual work on one of the goal's plan's
    tasks — the Actual of docs/07's triad, recorded as given."""
    try:
        execution = _service(request).record_execution(
            goal_id=goal_id,
            task_id=payload.task_id,
            start=payload.start,
            end=payload.end,
        )
    except _NOT_FOUND as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except _DOMAIN_ERRORS as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _execution_response(execution)


@router.post(
    "/goals/{goal_id}/progress",
    status_code=status.HTTP_201_CREATED,
    operation_id="takeProgressSnapshot",
    response_model=ProgressResponse,
)
def take_snapshot(
    goal_id: uuid.UUID, request: Request
) -> ProgressResponse:
    """Take one progress snapshot of the goal's plan, now."""
    try:
        bundle = _service(request).take_snapshot(goal_id)
    except _NOT_FOUND as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except _DOMAIN_ERRORS as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _progress_response(bundle)


@router.get(
    "/goals/{goal_id}/progress",
    operation_id="getProgress",
    response_model=ProgressResponse,
)
def get_progress(goal_id: uuid.UUID, request: Request) -> ProgressResponse:
    """The latest progress snapshot of the goal's plan, or 404 while
    none has been taken."""
    try:
        bundle = _service(request).get_latest(goal_id)
    except GoalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    if bundle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no progress snapshot for goal {goal_id}",
        )
    return _progress_response(bundle)
