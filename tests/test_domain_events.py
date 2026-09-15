"""Tests for domain events (TASK-018).

Covers the event envelope invariants (typed, UTC, immutable payload with a
read-only view), the in-memory collector, and the convenience constructors
for the operations the core domain supports.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from backcasting.domain.events import (
    DomainEvent,
    DomainEventError,
    DomainEventType,
    EventCollector,
    current_state_captured,
    future_state_defined,
    future_state_revised,
    goal_created,
    goal_revised,
    goal_status_changed,
)

OCCURRED = datetime(2026, 1, 1, tzinfo=timezone.utc)


class TestDomainEvent:
    def test_valid_event_round_trips(self) -> None:
        event = DomainEvent(
            DomainEventType.GOAL_CREATED,
            OCCURRED,
            {"goal_id": uuid.uuid4()},
        )
        assert event.event_type is DomainEventType.GOAL_CREATED
        assert event.occurred_at == OCCURRED
        assert isinstance(event.event_id, uuid.UUID)

    def test_event_types_are_dotted_names(self) -> None:
        for event_type in DomainEventType:
            assert "." in event_type.value
            assert event_type.value == event_type.value.lower()

    def test_event_is_immutable(self) -> None:
        event = DomainEvent(DomainEventType.GOAL_CREATED, OCCURRED)
        with pytest.raises(AttributeError):
            event.event_type = DomainEventType.GOAL_REVISED  # type: ignore[misc]

    def test_payload_is_a_read_only_view(self) -> None:
        payload = {"goal_id": uuid.uuid4()}
        event = DomainEvent(DomainEventType.GOAL_CREATED, OCCURRED, payload)
        payload["injected"] = True  # mutating the source must not leak in
        assert "injected" not in event.payload
        with pytest.raises(TypeError):
            event.payload["injected"] = True  # type: ignore[index]

    def test_default_payload_is_empty(self) -> None:
        event = DomainEvent(DomainEventType.GOAL_CREATED, OCCURRED)
        assert dict(event.payload) == {}

    def test_naive_occurred_at_is_rejected(self) -> None:
        with pytest.raises(DomainEventError):
            DomainEvent(DomainEventType.GOAL_CREATED, datetime(2026, 1, 1))

    def test_non_utc_occurred_at_is_rejected(self) -> None:
        # Europe/Berlin is UTC+1 on 2026-01-01.
        local = datetime(2026, 1, 1, 12, tzinfo=ZoneInfo("Europe/Berlin"))
        with pytest.raises(DomainEventError):
            DomainEvent(DomainEventType.GOAL_CREATED, local)

    def test_non_enum_type_is_rejected(self) -> None:
        with pytest.raises(DomainEventError):
            DomainEvent("goal.created", OCCURRED)  # type: ignore[arg-type]

    def test_non_mapping_payload_is_rejected(self) -> None:
        with pytest.raises(DomainEventError):
            DomainEvent(DomainEventType.GOAL_CREATED, OCCURRED, ["not", "a", "map"])  # type: ignore[arg-type]

    def test_non_uuid_event_id_is_rejected(self) -> None:
        with pytest.raises(DomainEventError):
            DomainEvent(
                DomainEventType.GOAL_CREATED, OCCURRED, event_id="not-a-uuid"  # type: ignore[arg-type]
            )


class TestEventCollector:
    def test_records_in_order(self) -> None:
        collector = EventCollector()
        first = goal_created(uuid.uuid4(), occurred_at=OCCURRED)
        second = goal_status_changed(
            uuid.uuid4(),
            from_status="draft",
            to_status="active",
            occurred_at=OCCURRED,
        )
        collector.record(first)
        collector.record(second)
        assert collector.events == (first, second)
        assert len(collector) == 2

    def test_empty_collector_is_empty(self) -> None:
        collector = EventCollector()
        assert collector.events == ()
        assert len(collector) == 0

    def test_record_returns_the_event_for_chaining(self) -> None:
        collector = EventCollector()
        event = goal_created(uuid.uuid4(), occurred_at=OCCURRED)
        assert collector.record(event) is event

    def test_events_tuple_is_immutable(self) -> None:
        collector = EventCollector()
        collector.record(goal_created(uuid.uuid4(), occurred_at=OCCURRED))
        with pytest.raises(AttributeError):
            collector.events.append(goal_created(uuid.uuid4(), occurred_at=OCCURRED))  # type: ignore[attr-defined]

    def test_non_event_is_rejected(self) -> None:
        with pytest.raises(DomainEventError):
            EventCollector().record("not an event")  # type: ignore[arg-type]


class TestEventConstructors:
    def test_goal_created(self) -> None:
        goal_id = uuid.uuid4()
        event = goal_created(goal_id, occurred_at=OCCURRED)
        assert event.event_type is DomainEventType.GOAL_CREATED
        assert event.payload == {"goal_id": goal_id}

    def test_goal_revised(self) -> None:
        goal_id = uuid.uuid4()
        event = goal_revised(goal_id, occurred_at=OCCURRED)
        assert event.event_type is DomainEventType.GOAL_REVISED

    def test_goal_status_changed_carries_transition(self) -> None:
        goal_id = uuid.uuid4()
        event = goal_status_changed(
            goal_id, from_status="draft", to_status="active", occurred_at=OCCURRED
        )
        assert event.event_type is DomainEventType.GOAL_STATUS_CHANGED
        assert event.payload == {
            "goal_id": goal_id,
            "from_status": "draft",
            "to_status": "active",
        }

    def test_current_state_captured(self) -> None:
        goal_id, state_id = uuid.uuid4(), uuid.uuid4()
        event = current_state_captured(goal_id, state_id, occurred_at=OCCURRED)
        assert event.event_type is DomainEventType.CURRENT_STATE_CAPTURED
        assert event.payload == {"goal_id": goal_id, "state_id": state_id}

    def test_future_state_defined(self) -> None:
        goal_id, state_id = uuid.uuid4(), uuid.uuid4()
        event = future_state_defined(goal_id, state_id, occurred_at=OCCURRED)
        assert event.event_type is DomainEventType.FUTURE_STATE_DEFINED

    def test_future_state_revised(self) -> None:
        goal_id, state_id = uuid.uuid4(), uuid.uuid4()
        event = future_state_revised(goal_id, state_id, occurred_at=OCCURRED)
        assert event.event_type is DomainEventType.FUTURE_STATE_REVISED

    def test_events_from_distinct_operations_are_distinct(self) -> None:
        goal_id = uuid.uuid4()
        first = goal_created(goal_id, occurred_at=OCCURRED)
        second = goal_created(goal_id, occurred_at=OCCURRED)
        assert first.event_id != second.event_id
