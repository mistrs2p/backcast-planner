"""Replanning HTTP API (TASK-115).

Exposes the manual replanning use cases
(``backcasting.application.replanning`` — docs/08 level 2, Manual
mode) over HTTP, scoped under the goal whose plan is replanned.
Level 1 (rescheduling) and level 3 (goal revision) are different
surfaces; Suggest and Automatic modes route through the decision
engine, not these endpoints.

Status mapping:

- unknown goal, no plan, or a task not on the goal's plan → 404
- replanning a plan still in assembly (DRAFT) → 409
- domain violations (a revision that changes nothing, an
  unestimated task set, blank or over-long reasons) → 422
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import AwareDatetime, BaseModel, Field

from backcasting.api.plans import (
    PlanResponse,
    TaskResponse,
    _plan_response,
    _task_response,
)
from backcasting.application.goals import GoalNotFoundError
from backcasting.application.plans import NoPlanError, NoTaskError
from backcasting.application.replanning import (
    GlobalReplanBundle,
    LocalReplanBundle,
    PlanIsDraftError,
    ReplanningService,
)
from backcasting.domain.global_replan import GlobalReplanError
from backcasting.domain.local_replan import LocalReplanError
from backcasting.domain.plan_version import (
    PlanVersion,
    PlanVersionError,
)
from backcasting.domain.task import TaskError
from backcasting.domain.task_estimation import TaskEstimationError

router = APIRouter(tags=["replanning"])


def _service(request: Request) -> ReplanningService:
    return request.app.state.replanning_service


class LocalReplanCreate(BaseModel):
    """A local replan (one task revised in place): the task, the
    reason the plan changed, and the revision itself — omitted
    fields keep their current value."""

    task_id: uuid.UUID
    reason: str = Field(min_length=1, max_length=500)
    title: str | None = None
    description: str | None = None
    duration_hours: float | None = Field(default=None, gt=0)
    deadline: AwareDatetime | None = None


class GlobalReplanCreate(BaseModel):
    """A global replan (the whole plan re-derived): the reason, and
    optionally the re-derived plan's new title."""

    reason: str = Field(min_length=1, max_length=500)
    title: str | None = Field(default=None, max_length=200)


class PlanVersionResponse(BaseModel):
    """One traceable version of a plan: why it changed, from which
    run (if any), and what changed."""

    version_id: uuid.UUID
    plan_id: uuid.UUID
    version: int
    reason: str
    title: str | None
    workload_hours: float | None
    revised_task_ids: list[uuid.UUID]
    source_run_id: uuid.UUID | None
    created_at: str


class LocalReplanResponse(BaseModel):
    plan: PlanResponse
    task: TaskResponse
    version: PlanVersionResponse


class GlobalReplanResponse(BaseModel):
    plan: PlanResponse
    version: PlanVersionResponse


def _version_response(version: PlanVersion) -> PlanVersionResponse:
    change = version.change_set
    return PlanVersionResponse(
        version_id=version.version_id,
        plan_id=version.plan_id,
        version=version.version,
        reason=version.reason,
        title=change.title,
        workload_hours=(
            change.workload.total_seconds() / 3600
            if change.workload is not None
            else None
        ),
        revised_task_ids=sorted(change.revised_task_ids),
        source_run_id=version.source_run_id,
        created_at=version.created_at.isoformat(),
    )


def _local_response(bundle: LocalReplanBundle) -> LocalReplanResponse:
    return LocalReplanResponse(
        plan=_plan_response(bundle.plan),
        task=_task_response(bundle.task),
        version=_version_response(bundle.version),
    )


def _global_response(bundle: GlobalReplanBundle) -> GlobalReplanResponse:
    return GlobalReplanResponse(
        plan=_plan_response(bundle.plan),
        version=_version_response(bundle.version),
    )


_NOT_FOUND = (GoalNotFoundError, NoPlanError, NoTaskError)
_CONFLICT = (PlanIsDraftError,)
_DOMAIN_ERRORS = (
    LocalReplanError,
    GlobalReplanError,
    PlanVersionError,
    TaskError,
    TaskEstimationError,
)


@router.post(
    "/goals/{goal_id}/plan/replan/local",
    status_code=status.HTTP_201_CREATED,
    operation_id="replanTaskLocally",
    response_model=LocalReplanResponse,
)
def replan_task_locally(
    goal_id: uuid.UUID, payload: LocalReplanCreate, request: Request
) -> LocalReplanResponse:
    """Revise one task of the goal's plan in place (LOCAL scope,
    docs/08) — the archetypal re-estimate — traced as a plan
    version."""
    try:
        bundle = _service(request).replan_task(
            goal_id=goal_id,
            task_id=payload.task_id,
            reason=payload.reason,
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
    return _local_response(bundle)


@router.post(
    "/goals/{goal_id}/plan/replan/global",
    status_code=status.HTTP_201_CREATED,
    operation_id="replanPlanGlobally",
    response_model=GlobalReplanResponse,
)
def replan_plan_globally(
    goal_id: uuid.UUID, payload: GlobalReplanCreate, request: Request
) -> GlobalReplanResponse:
    """Re-derive the goal's plan from its task set (GLOBAL scope,
    docs/08): workload recomputed, title optionally revised, traced
    as a plan version."""
    try:
        bundle = _service(request).replan_globally(
            goal_id=goal_id,
            reason=payload.reason,
            title=payload.title,
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
    return _global_response(bundle)


@router.get(
    "/goals/{goal_id}/plan/versions",
    operation_id="listPlanVersions",
    response_model=list[PlanVersionResponse],
)
def list_plan_versions(
    goal_id: uuid.UUID, request: Request
) -> list[PlanVersionResponse]:
    """The goal's plan's version trail — every meaningful replan,
    earliest version first."""
    try:
        versions = _service(request).list_versions(goal_id)
    except _NOT_FOUND as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return [_version_response(version) for version in versions]
