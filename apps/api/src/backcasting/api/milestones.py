"""Milestone HTTP API (TASK-110).

Exposes the milestone use cases (``backcasting.application.milestones``)
over HTTP, scoped under the goal whose run the checkpoints attach
to.

Status mapping:

- unknown goal → 404
- no backcasting run yet → 404 (define the backcast first)
- domain violations (blank title, target at or before now, a
  finished run) → 422
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import AwareDatetime, BaseModel

from backcasting.application.goals import GoalNotFoundError
from backcasting.application.milestones import (
    MilestoneService,
    NoBackcastRunError,
)
from backcasting.domain.milestone import Milestone, MilestoneError

router = APIRouter(tags=["milestones"])


def _service(request: Request) -> MilestoneService:
    return request.app.state.milestone_service


class MilestoneCreate(BaseModel):
    title: str
    target_date: AwareDatetime
    description: str = ""


class MilestoneResponse(BaseModel):
    milestone_id: uuid.UUID
    run_id: uuid.UUID
    goal_id: uuid.UUID
    title: str
    description: str
    target_date: str
    created_at: str
    updated_at: str


def _milestone_response(milestone: Milestone) -> MilestoneResponse:
    return MilestoneResponse(
        milestone_id=milestone.milestone_id,
        run_id=milestone.run_id,
        goal_id=milestone.goal_id,
        title=milestone.title,
        description=milestone.description,
        target_date=milestone.target_date.isoformat(),
        created_at=milestone.created_at.isoformat(),
        updated_at=milestone.updated_at.isoformat(),
    )


@router.post(
    "/goals/{goal_id}/milestones",
    status_code=status.HTTP_201_CREATED,
    operation_id="defineMilestone",
    response_model=MilestoneResponse,
)
def define_milestone(
    goal_id: uuid.UUID, payload: MilestoneCreate, request: Request
) -> MilestoneResponse:
    """Pin a checkpoint on the goal's current backcasting run
    (docs/04 step 10)."""
    try:
        milestone = _service(request).define_milestone(
            goal_id=goal_id,
            title=payload.title,
            target_date=payload.target_date,
            description=payload.description,
        )
    except (GoalNotFoundError, NoBackcastRunError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except MilestoneError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _milestone_response(milestone)


@router.get(
    "/goals/{goal_id}/milestones",
    operation_id="listMilestones",
    response_model=list[MilestoneResponse],
)
def list_milestones(
    goal_id: uuid.UUID, request: Request
) -> list[MilestoneResponse]:
    """The goal's checkpoints on its current run, earliest target
    first. Empty while no run exists."""
    milestones = _service(request).list_for_goal(goal_id)
    return [_milestone_response(milestone) for milestone in milestones]
