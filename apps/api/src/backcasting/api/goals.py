"""Goal HTTP API.

Exposes the goal use cases (``backcasting.application.goals``) over
HTTP. Transport concerns live here and nowhere else: request/
response DTOs, HTTP status mapping, and wiring the service from
``app.state``. Domain rules stay in the domain; this layer
translates.

Status mapping:

- unknown goal → 404
- domain violations (blank or oversized title, non-UUID ids) → 422
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel

from backcasting.application.goals import GoalNotFoundError, GoalService
from backcasting.domain.goal import Goal, GoalError

router = APIRouter(tags=["goals"])


def _service(request: Request) -> GoalService:
    return request.app.state.goal_service


class GoalCreate(BaseModel):
    user_id: uuid.UUID
    title: str
    description: str = ""


class GoalResponse(BaseModel):
    goal_id: uuid.UUID
    user_id: uuid.UUID
    title: str
    description: str
    status: str
    created_at: str
    updated_at: str


def _goal_response(goal: Goal) -> GoalResponse:
    return GoalResponse(
        goal_id=goal.goal_id,
        user_id=goal.user_id,
        title=goal.title,
        description=goal.description,
        status=goal.status.value,
        created_at=goal.created_at.isoformat(),
        updated_at=goal.updated_at.isoformat(),
    )


@router.post(
    "/goals",
    status_code=status.HTTP_201_CREATED,
    operation_id="createGoal",
    response_model=GoalResponse,
)
def create_goal(payload: GoalCreate, request: Request) -> GoalResponse:
    """Create a goal (pipeline step 1, docs/04)."""
    service = _service(request)
    try:
        goal = service.create_goal(
            user_id=payload.user_id,
            title=payload.title,
            description=payload.description,
        )
    except GoalError as exc:
        raise HTTPException(
            status_code=422, detail=str(exc)
        ) from exc
    return _goal_response(goal)


@router.get(
    "/goals/{goal_id}",
    operation_id="getGoal",
    response_model=GoalResponse,
)
def get_goal(goal_id: uuid.UUID, request: Request) -> GoalResponse:
    """Return one goal."""
    try:
        goal = _service(request).get_goal(goal_id)
    except GoalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return _goal_response(goal)


@router.get(
    "/goals",
    operation_id="listGoals",
    response_model=list[GoalResponse],
)
def list_goals(
    request: Request,
    user_id: uuid.UUID = Query(
        ..., description="The user whose goals to list."
    ),
) -> list[GoalResponse]:
    """The user's goals, oldest first."""
    goals = _service(request).list_for_user(user_id)
    return [_goal_response(goal) for goal in goals]
