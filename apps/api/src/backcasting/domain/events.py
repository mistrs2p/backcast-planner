"""Domain events.

An event records something that already happened in the domain — as opposed
to a command, which asks for something to happen. Events are the seam the
future application layer (and the deferred worker/queue infrastructure)
will use to react to domain changes without coupling the domain to any
delivery mechanism: the domain only produces immutable records.

Rules:

- ``occurred_at`` is timezone-aware UTC (``AGENTS.md`` §7).
- ``payload`` is a mapping converted to a read-only view; the event is
  frozen. Event consumers must not attempt to mutate events.
- ``event_id`` is a UUID, generated when omitted.

:class:`EventCollector` is the in-memory accumulator services hand around;
persistence and publication are infrastructure concerns that arrive with
the repository and worker tasks.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class DomainEventType(str, Enum):
    """Types of events the core domain can emit."""

    GOAL_CREATED = "goal.created"
    GOAL_REVISED = "goal.revised"
    GOAL_STATUS_CHANGED = "goal.status_changed"
    CURRENT_STATE_CAPTURED = "current_state.captured"
    FUTURE_STATE_DEFINED = "future_state.defined"
    FUTURE_STATE_REVISED = "future_state.revised"


class DomainEventError(ValueError):
    """Raised when a DomainEvent invariant is violated."""


@dataclass(frozen=True)
class DomainEvent:
    """An immutable record of something that happened in the domain."""

    event_type: DomainEventType
    occurred_at: datetime
    payload: Mapping[str, object] = field(default_factory=dict)
    event_id: uuid.UUID = field(default_factory=uuid.uuid4)

    def __post_init__(self) -> None:
        if not isinstance(self.event_type, DomainEventType):
            raise DomainEventError("event_type must be a DomainEventType")
        if not isinstance(self.occurred_at, datetime):
            raise DomainEventError("occurred_at must be a datetime")
        if self.occurred_at.tzinfo is None:
            raise DomainEventError("occurred_at must be timezone-aware")
        if self.occurred_at.utcoffset() != timezone.utc.utcoffset(self.occurred_at):
            raise DomainEventError("occurred_at must be in UTC")
        if not isinstance(self.payload, Mapping):
            raise DomainEventError("payload must be a mapping")
        if not isinstance(self.event_id, uuid.UUID):
            raise DomainEventError("event_id must be a UUID")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


class EventCollector:
    """Accumulates domain events in memory, in the order recorded."""

    def __init__(self) -> None:
        self._events: list[DomainEvent] = []

    def record(self, event: DomainEvent) -> DomainEvent:
        """Record ``event`` and return it for call-chaining."""
        if not isinstance(event, DomainEvent):
            raise DomainEventError("can only record DomainEvent instances")
        self._events.append(event)
        return event

    @property
    def events(self) -> tuple[DomainEvent, ...]:
        """The recorded events, oldest first, as an immutable tuple."""
        return tuple(self._events)

    def __len__(self) -> int:
        return len(self._events)


# ---------------------------------------------------------------------------
# Convenience constructors for the operations the core domain supports so
# far. Services call these *after* an operation succeeds — an event is a
# fact, never a request.
# ---------------------------------------------------------------------------


def goal_created(goal_id: uuid.UUID, *, occurred_at: datetime) -> DomainEvent:
    return DomainEvent(
        DomainEventType.GOAL_CREATED,
        occurred_at,
        {"goal_id": goal_id},
    )


def goal_revised(goal_id: uuid.UUID, *, occurred_at: datetime) -> DomainEvent:
    return DomainEvent(
        DomainEventType.GOAL_REVISED,
        occurred_at,
        {"goal_id": goal_id},
    )


def goal_status_changed(
    goal_id: uuid.UUID,
    *,
    from_status: str,
    to_status: str,
    occurred_at: datetime,
) -> DomainEvent:
    return DomainEvent(
        DomainEventType.GOAL_STATUS_CHANGED,
        occurred_at,
        {
            "goal_id": goal_id,
            "from_status": from_status,
            "to_status": to_status,
        },
    )


def current_state_captured(
    goal_id: uuid.UUID, state_id: uuid.UUID, *, occurred_at: datetime
) -> DomainEvent:
    return DomainEvent(
        DomainEventType.CURRENT_STATE_CAPTURED,
        occurred_at,
        {"goal_id": goal_id, "state_id": state_id},
    )


def future_state_defined(
    goal_id: uuid.UUID, state_id: uuid.UUID, *, occurred_at: datetime
) -> DomainEvent:
    return DomainEvent(
        DomainEventType.FUTURE_STATE_DEFINED,
        occurred_at,
        {"goal_id": goal_id, "state_id": state_id},
    )


def future_state_revised(
    goal_id: uuid.UUID, state_id: uuid.UUID, *, occurred_at: datetime
) -> DomainEvent:
    return DomainEvent(
        DomainEventType.FUTURE_STATE_REVISED,
        occurred_at,
        {"goal_id": goal_id, "state_id": state_id},
    )


def now_utc() -> datetime:
    """Current UTC time — the default clock for event constructors."""
    return datetime.now(timezone.utc)
