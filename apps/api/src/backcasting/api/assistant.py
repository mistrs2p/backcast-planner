"""AI assistant HTTP API (TASK-116).

Exposes the assistant's use cases
(``backcasting.application.assistant`` — docs/09's operations) over
HTTP, scoped under the goal being read. The LLM proposes and the
domain validates (ADR-002): these endpoints carry *proposals* with
their provenance, never conclusions the system acts on by
themselves.

Status mapping:

- unknown goal, or a goal with no current state to read against → 404
- no LLM wired on this server → 503
- the vendor call itself failing (network, auth, quota) → 502
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from backcasting.application.assistant import (
    AssistantService,
    NoCurrentStateError,
    NoProviderError,
)
from backcasting.application.goals import GoalNotFoundError
from backcasting.domain.goal_interpretation import GoalInterpretation
from backcasting.domain.llm_provider import ProviderCallError

router = APIRouter(tags=["assistant"])


def _service(request: Request) -> AssistantService:
    return request.app.state.assistant_service


class InterpretationResponse(BaseModel):
    """One AI proposal reading a goal, with its provenance — the
    provider and the model that actually answered."""

    interpretation_id: uuid.UUID
    goal_id: uuid.UUID
    proposal: str
    provider: str
    model: str
    created_at: str


def _response(record: GoalInterpretation) -> InterpretationResponse:
    return InterpretationResponse(
        interpretation_id=record.interpretation_id,
        goal_id=record.goal_id,
        proposal=record.proposal,
        provider=record.provider,
        model=record.model,
        created_at=record.created_at.isoformat(),
    )


@router.post(
    "/goals/{goal_id}/assistant/interpretations",
    status_code=status.HTTP_201_CREATED,
    operation_id="interpretGoal",
    response_model=InterpretationResponse,
)
def interpret_goal(
    goal_id: uuid.UUID, request: Request
) -> InterpretationResponse:
    """Ask the wired AI provider to read the goal against its
    current state (docs/09's first operation), recording the
    proposal verbatim with its provenance."""
    try:
        record = _service(request).interpret(goal_id)
    except (GoalNotFoundError, NoCurrentStateError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except NoProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except ProviderCallError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    return _response(record)


@router.get(
    "/goals/{goal_id}/assistant/interpretations",
    operation_id="listGoalInterpretations",
    response_model=list[InterpretationResponse],
)
def list_interpretations(
    goal_id: uuid.UUID, request: Request
) -> list[InterpretationResponse]:
    """The goal's reading history — every recorded proposal with its
    provenance, earliest first."""
    try:
        records = _service(request).list_interpretations(goal_id)
    except GoalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return [_response(record) for record in records]
