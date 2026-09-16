"""Backcast HTTP API (TASK-109).

Exposes the backcast use cases
(``backcasting.application.backcast`` — pipeline steps 1–4 of
docs/04) over HTTP, scoped under the goal they belong to.

Status mapping:

- unknown goal, or no backcast yet → 404
- a second backcast for a goal → 409 (one per goal in the MVP)
- domain violations (blank narratives, target date not after the
  snapshot, naive datetime) → 422
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import AwareDatetime, BaseModel

from backcasting.application.backcast import (
    BackcastAlreadyExistsError,
    BackcastBundle,
    BackcastService,
)
from backcasting.application.goals import GoalNotFoundError
from backcasting.domain.backcasting_run import BackcastingRun
from backcasting.domain.current_state import CurrentStateError
from backcasting.domain.future_state import FutureStateError
from backcasting.domain.gap import Gap, GapDimension, GapError

router = APIRouter(tags=["backcast"])

_DOMAIN_ERRORS = (CurrentStateError, FutureStateError, GapError)


def _service(request: Request) -> BackcastService:
    return request.app.state.backcast_service


class GapDimensionResponse(BaseModel):
    metric_name: str
    current_value: object
    target_value: object


class CurrentStateResponse(BaseModel):
    state_id: uuid.UUID
    goal_id: uuid.UUID
    narrative: str
    captured_at: str


class FutureStateResponse(BaseModel):
    state_id: uuid.UUID
    goal_id: uuid.UUID
    description: str
    target_date: str
    created_at: str
    updated_at: str


class GapResponse(BaseModel):
    gap_id: uuid.UUID
    goal_id: uuid.UUID
    current_state_id: uuid.UUID
    future_state_id: uuid.UUID
    calculated_at: str
    dimensions: list[GapDimensionResponse]
    narrative: str


class RunResponse(BaseModel):
    run_id: uuid.UUID
    goal_id: uuid.UUID
    current_state_id: uuid.UUID
    future_state_id: uuid.UUID
    gap_id: uuid.UUID
    status: str
    started_at: str
    completed_at: str | None


class BackcastResponse(BaseModel):
    """The intent layer of one goal's backcast, as the UI
    visualizes it: current → gap → future, and the pipeline run
    executing over that context."""

    current: CurrentStateResponse
    future: FutureStateResponse
    gap: GapResponse
    run: RunResponse


class BackcastCreate(BaseModel):
    current_narrative: str
    future_description: str
    target_date: AwareDatetime
    gap_narrative: str = ""


def _dimension_response(dimension: GapDimension) -> GapDimensionResponse:
    return GapDimensionResponse(
        metric_name=dimension.metric.name,
        current_value=dimension.current_value,
        target_value=dimension.target_value,
    )


def _gap_response(gap: Gap) -> GapResponse:
    return GapResponse(
        gap_id=gap.gap_id,
        goal_id=gap.goal_id,
        current_state_id=gap.current_state_id,
        future_state_id=gap.future_state_id,
        calculated_at=gap.calculated_at.isoformat(),
        dimensions=[
            _dimension_response(dimension) for dimension in gap.dimensions
        ],
        narrative=gap.narrative,
    )


def _run_response(run: BackcastingRun) -> RunResponse:
    return RunResponse(
        run_id=run.run_id,
        goal_id=run.goal_id,
        current_state_id=run.current_state_id,
        future_state_id=run.future_state_id,
        gap_id=run.gap_id,
        status=run.status.value,
        started_at=run.started_at.isoformat(),
        completed_at=(
            run.completed_at.isoformat() if run.completed_at else None
        ),
    )


def _backcast_response(bundle: BackcastBundle) -> BackcastResponse:
    return BackcastResponse(
        current=CurrentStateResponse(
            state_id=bundle.current.state_id,
            goal_id=bundle.current.goal_id,
            narrative=bundle.current.narrative,
            captured_at=bundle.current.captured_at.isoformat(),
        ),
        future=FutureStateResponse(
            state_id=bundle.future.state_id,
            goal_id=bundle.future.goal_id,
            description=bundle.future.description,
            target_date=bundle.future.target_date.isoformat(),
            created_at=bundle.future.created_at.isoformat(),
            updated_at=bundle.future.updated_at.isoformat(),
        ),
        gap=_gap_response(bundle.gap),
        run=_run_response(bundle.run),
    )


@router.post(
    "/goals/{goal_id}/backcast",
    status_code=status.HTTP_201_CREATED,
    operation_id="defineBackcast",
    response_model=BackcastResponse,
)
def define_backcast(
    goal_id: uuid.UUID, payload: BackcastCreate, request: Request
) -> BackcastResponse:
    """Define a goal's backcast context: capture the current state,
    define the desired future, calculate the gap (pipeline steps
    1–4, docs/04)."""
    try:
        bundle = _service(request).define_backcast(
            goal_id=goal_id,
            current_narrative=payload.current_narrative,
            future_description=payload.future_description,
            target_date=payload.target_date,
            gap_narrative=payload.gap_narrative,
        )
    except GoalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except BackcastAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except _DOMAIN_ERRORS as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _backcast_response(bundle)


@router.get(
    "/goals/{goal_id}/backcast",
    operation_id="getBackcast",
    response_model=BackcastResponse,
)
def get_backcast(
    goal_id: uuid.UUID, request: Request
) -> BackcastResponse:
    """The goal's backcast context, or 404 while none is defined."""
    bundle = _service(request).get_backcast(goal_id)
    if bundle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no backcast for goal {goal_id}",
        )
    return _backcast_response(bundle)
