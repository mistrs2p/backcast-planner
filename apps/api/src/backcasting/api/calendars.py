"""Calendar HTTP API.

Exposes the calendar use cases (``backcasting.application.calendars``)
over HTTP. Transport concerns live here and nowhere else: request/
response DTOs, HTTP status mapping, and wiring the service from
``app.state``. Domain rules stay in the domain; this layer translates.

Status mapping:

- unknown calendar → 404
- a user's second calendar → 409 (one per user in the MVP)
- domain violations (invalid title, end before start, naive datetime,
  unknown timezone) → 422
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import AwareDatetime, BaseModel, ConfigDict

from backcasting.application.calendars import (
    CalendarAlreadyExistsError,
    CalendarNotFoundError,
    CalendarService,
    InvalidTimezoneError,
)
from backcasting.domain.calendar import Calendar
from backcasting.domain.calendar_event import CalendarEvent
from backcasting.domain.conflict import Conflict

router = APIRouter(tags=["calendars"])


def _service(request: Request) -> CalendarService:
    return request.app.state.calendar_service


class CalendarCreate(BaseModel):
    user_id: uuid.UUID
    timezone: str | None = None


class CalendarResponse(BaseModel):
    calendar_id: uuid.UUID
    user_id: uuid.UUID
    timezone: str
    created_at: datetime
    updated_at: datetime


class EventCreate(BaseModel):
    title: str
    start: AwareDatetime
    end: AwareDatetime
    description: str = ""


class EventResponse(BaseModel):
    event_id: uuid.UUID
    calendar_id: uuid.UUID
    title: str
    start: datetime
    end: datetime
    description: str
    created_at: datetime
    updated_at: datetime


class ConflictResponse(BaseModel):
    first: EventResponse
    second: EventResponse
    start: datetime
    end: datetime


def _calendar_response(calendar: Calendar) -> CalendarResponse:
    return CalendarResponse(
        calendar_id=calendar.calendar_id,
        user_id=calendar.user_id,
        timezone=str(calendar.timezone),
        created_at=calendar.created_at,
        updated_at=calendar.updated_at,
    )


def _event_response(event: CalendarEvent) -> EventResponse:
    return EventResponse(
        event_id=event.event_id,
        calendar_id=event.calendar_id,
        title=event.title,
        start=event.start,
        end=event.end,
        description=event.description,
        created_at=event.created_at,
        updated_at=event.updated_at,
    )


def _conflict_response(conflict: Conflict) -> ConflictResponse:
    return ConflictResponse(
        first=_event_response(conflict.first),
        second=_event_response(conflict.second),
        start=conflict.start,
        end=conflict.end,
    )


@router.post(
    "/calendars",
    response_model=CalendarResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createCalendar",
)
def create_calendar(payload: CalendarCreate, request: Request) -> CalendarResponse:
    """Create the user's calendar (one per user in the MVP)."""
    try:
        calendar = _service(request).create_calendar(
            user_id=payload.user_id, timezone=payload.timezone
        )
    except CalendarAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (InvalidTimezoneError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _calendar_response(calendar)


@router.get(
    "/users/{user_id}/calendar",
    response_model=CalendarResponse,
    operation_id="getCalendarForUser",
)
def get_calendar_for_user(
    user_id: uuid.UUID, request: Request
) -> CalendarResponse:
    """The user's calendar (TASK-113's read path — the browser holds
    the user id), or 404 while they own none."""
    calendar = _service(request).get_for_user(user_id)
    if calendar is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no calendar for user {user_id}",
        )
    return _calendar_response(calendar)


@router.get(
    "/calendars/{calendar_id}",
    response_model=CalendarResponse,
    operation_id="getCalendar",
)
def get_calendar(calendar_id: uuid.UUID, request: Request) -> CalendarResponse:
    """Return the calendar."""
    try:
        calendar = _service(request).get_calendar(calendar_id)
    except CalendarNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _calendar_response(calendar)


@router.post(
    "/calendars/{calendar_id}/events",
    response_model=EventResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createCalendarEvent",
)
def create_event(
    calendar_id: uuid.UUID, payload: EventCreate, request: Request
) -> EventResponse:
    """Place an event on the calendar (normalized to UTC)."""
    try:
        event = _service(request).add_event(
            calendar_id,
            title=payload.title,
            start=payload.start,
            end=payload.end,
            description=payload.description,
        )
    except CalendarNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _event_response(event)


@router.get(
    "/calendars/{calendar_id}/events",
    response_model=list[EventResponse],
    operation_id="listCalendarEvents",
)
def list_events(calendar_id: uuid.UUID, request: Request) -> list[EventResponse]:
    """Return the calendar's events, earliest start first."""
    try:
        events = _service(request).list_events(calendar_id)
    except CalendarNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [_event_response(e) for e in events]


@router.get(
    "/calendars/{calendar_id}/conflicts",
    response_model=list[ConflictResponse],
    operation_id="listCalendarConflicts",
)
def list_conflicts(calendar_id: uuid.UUID, request: Request) -> list[ConflictResponse]:
    """Report the overlapping event pairs on the calendar."""
    try:
        conflicts = _service(request).detect_conflicts(calendar_id)
    except CalendarNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [_conflict_response(c) for c in conflicts]
