"""Tests for the trigger model (TASK-079).

"Triggers" (docs/08-REPLANNING-MODEL.md): progress, capacity, time,
calendar, constraint, resource, dependency, behavior, goal, system —
the observed conditions adaptation may respond to. A trigger states
what was seen and when; thresholds, cooldown, and hysteresis
(TASK-080 through TASK-082) decide what it means.
"""

from __future__ import annotations

import uuid
from dataclasses import FrozenInstanceError
from datetime import datetime, time, timedelta, timezone

import pytest

from backcasting.domain.trigger import (
    MAX_DETAIL_LENGTH,
    Trigger,
    TriggerError,
    TriggerKind,
    raise_trigger,
    triggers_of_kind,
)
from backcasting.domain.repositories import TriggerRepository

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
MONDAY = datetime(2026, 6, 1, tzinfo=timezone.utc)  # a Monday
HOUR = timedelta(hours=1)


class TestRaiseTrigger:
    def test_record_shape(self) -> None:
        trigger = raise_trigger(
            TriggerKind.PROGRESS,
            "Progress variance unfavorable for two consecutive weeks.",
            observed_at=MONDAY,
        )
        assert isinstance(trigger.trigger_id, uuid.UUID)
        assert trigger.kind is TriggerKind.PROGRESS
        assert (
            trigger.detail
            == "Progress variance unfavorable for two consecutive weeks."
        )
        assert trigger.observed_at == MONDAY

    def test_detail_is_stripped(self) -> None:
        trigger = raise_trigger(TriggerKind.TIME, "  Deadline moved up.  ", observed_at=MONDAY)
        assert trigger.detail == "Deadline moved up."

    def test_injectable_id(self) -> None:
        trigger_id = uuid.uuid4()
        trigger = raise_trigger(
            TriggerKind.SYSTEM, "Clock skew detected.", trigger_id=trigger_id, observed_at=MONDAY
        )
        assert trigger.trigger_id == trigger_id

    def test_observed_at_defaults_to_now(self) -> None:
        trigger = raise_trigger(TriggerKind.CALENDAR, "Holiday removed a workday.")
        assert trigger.observed_at.tzinfo is not None
        assert trigger.observed_at <= datetime.now(timezone.utc)

    def test_is_immutable(self) -> None:
        trigger = raise_trigger(TriggerKind.GOAL, "Destination changed.", observed_at=MONDAY)
        with pytest.raises(FrozenInstanceError):
            trigger.detail = "Never mind."  # type: ignore[misc]

    def test_rejects_empty_detail(self) -> None:
        with pytest.raises(TriggerError, match="non-empty"):
            raise_trigger(TriggerKind.PROGRESS, "   ", observed_at=MONDAY)

    def test_rejects_overlong_detail(self) -> None:
        with pytest.raises(TriggerError, match="at most"):
            raise_trigger(
                TriggerKind.PROGRESS, "x" * (MAX_DETAIL_LENGTH + 1), observed_at=MONDAY
            )

    def test_rejects_non_string_detail(self) -> None:
        with pytest.raises(TriggerError, match="non-empty"):
            raise_trigger(TriggerKind.PROGRESS, 42, observed_at=MONDAY)

    def test_rejects_naive_observed_at(self) -> None:
        with pytest.raises(TriggerError, match="observed_at must be"):
            raise_trigger(TriggerKind.PROGRESS, "Behind.", observed_at=datetime(2026, 6, 1))

    def test_rejects_bad_kind(self) -> None:
        with pytest.raises(TriggerError, match="kind must be"):
            raise_trigger("progress", "Behind.", observed_at=MONDAY)  # type: ignore[arg-type]

    def test_kinds_match_the_spec_list(self) -> None:
        assert {k.value for k in TriggerKind} == {
            "progress",
            "capacity",
            "time",
            "calendar",
            "constraint",
            "resource",
            "dependency",
            "behavior",
            "goal",
            "system",
        }

    def test_direct_construction_validates_like_the_factory(self) -> None:
        with pytest.raises(TriggerError, match="detail must be"):
            Trigger(
                trigger_id=uuid.uuid4(),
                kind=TriggerKind.PROGRESS,
                detail="",
                observed_at=MONDAY,
            )
        with pytest.raises(TriggerError, match="kind must be"):
            Trigger(
                trigger_id=uuid.uuid4(),
                kind="progress",
                detail="Behind.",
                observed_at=MONDAY,
            )
        with pytest.raises(TriggerError, match="trigger_id must be"):
            Trigger(
                trigger_id="trigger",
                kind=TriggerKind.PROGRESS,
                detail="Behind.",
                observed_at=MONDAY,
            )


class TestTriggersOfKind:
    def test_filters_by_kind_keeping_input_order(self) -> None:
        first = raise_trigger(TriggerKind.PROGRESS, "Behind.", observed_at=MONDAY)
        other = raise_trigger(TriggerKind.CAPACITY, "Overloaded.", observed_at=MONDAY)
        second = raise_trigger(
            TriggerKind.PROGRESS, "Still behind.", observed_at=MONDAY + HOUR
        )
        assert triggers_of_kind((first, other, second), TriggerKind.PROGRESS) == (
            first,
            second,
        )

    def test_no_match_is_empty(self) -> None:
        trigger = raise_trigger(TriggerKind.SYSTEM, "Restart.", observed_at=MONDAY)
        assert triggers_of_kind((trigger,), TriggerKind.PROGRESS) == ()

    def test_rejects_bad_arguments(self) -> None:
        trigger = raise_trigger(TriggerKind.PROGRESS, "Behind.", observed_at=MONDAY)
        with pytest.raises(TriggerError, match="kind must be"):
            triggers_of_kind((trigger,), "progress")
        with pytest.raises(TriggerError, match="triggers must be a tuple"):
            triggers_of_kind([], TriggerKind.PROGRESS)
        with pytest.raises(TriggerError, match="Trigger instances"):
            triggers_of_kind(("x",), TriggerKind.PROGRESS)


class TestTriggerRepositoryPort:
    def test_in_memory_fake_honours_the_contract(self) -> None:
        repo = InMemoryTriggerRepository()
        early = raise_trigger(
            TriggerKind.PROGRESS, "Behind.", observed_at=MONDAY + HOUR
        )
        late = raise_trigger(TriggerKind.PROGRESS, "Still behind.", observed_at=MONDAY)
        for trigger in (early, late):
            repo.save(trigger)
        assert repo.get(late.trigger_id) is late
        assert repo.get(uuid.uuid4()) is None
        assert repo.list_all() == (late, early)

    def test_port_shape(self) -> None:
        assert {"save", "get", "list_all"} <= set(
            TriggerRepository.__abstractmethods__
        )


class InMemoryTriggerRepository(TriggerRepository):
    """The reference fake: a dict keyed by id, chronological listing."""

    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, Trigger] = {}

    def save(self, trigger: Trigger) -> None:
        self._by_id[trigger.trigger_id] = trigger

    def get(self, trigger_id: uuid.UUID) -> Trigger | None:
        return self._by_id.get(trigger_id)

    def list_all(self) -> tuple[Trigger, ...]:
        return tuple(sorted(self._by_id.values(), key=lambda t: t.observed_at))


class TestWiring:
    def test_signals_become_triggers(self) -> None:
        """The chain docs/08 implies: a behavioral signal (TASK-078)
        becomes a behavior trigger — the record the stability
        controls will judge."""
        from backcasting.domain.availability import create_availability_window
        from backcasting.domain.calendar import create_calendar
        from backcasting.domain.execution import create_execution
        from backcasting.domain.feedback import (
            FeedbackKind,
            detect_work_outside_availability,
        )
        from backcasting.domain.goal import create_goal
        from backcasting.domain.plan import create_plan
        from backcasting.domain.task import create_task

        goal = create_goal(uuid.uuid4(), "Ship v2", created_at=CREATED)
        plan = create_plan(goal, 20 * HOUR, created_at=CREATED)
        task = create_task(plan, "Task", created_at=CREATED)
        calendar = create_calendar(uuid.uuid4(), created_at=CREATED)
        window = create_availability_window(
            calendar, frozenset({0}), time(9), time(17), created_at=CREATED,
        )
        evening = create_execution(
            task,
            MONDAY.replace(hour=20),
            MONDAY.replace(hour=22),
            created_at=CREATED,
        )
        at = MONDAY + timedelta(days=1)

        signal = detect_work_outside_availability((evening,), (window,), at=at)
        assert signal is not None and signal.kind is FeedbackKind.IMPLICIT

        trigger = raise_trigger(
            TriggerKind.BEHAVIOR, signal.statement, observed_at=at
        )
        repo = InMemoryTriggerRepository()
        repo.save(trigger)
        assert triggers_of_kind(repo.list_all(), TriggerKind.BEHAVIOR) == (trigger,)
        assert triggers_of_kind(repo.list_all(), TriggerKind.PROGRESS) == ()

    def test_one_replan_judgement_many_trigger_kinds(self) -> None:
        """The ten kinds are one list: a single observation period can
        raise several, and they carry no decision — only what was seen."""
        observed = MONDAY
        triggers = (
            raise_trigger(
                TriggerKind.PROGRESS, "Actual 4h behind planned.", observed_at=observed
            ),
            raise_trigger(
                TriggerKind.CAPACITY, "Utilization 1.25 over the ceiling.", observed_at=observed
            ),
            raise_trigger(
                TriggerKind.TIME, "Milestone due before its estimate allows.", observed_at=observed
            ),
        )
        repo = InMemoryTriggerRepository()
        for trigger in triggers:
            repo.save(trigger)
        assert repo.list_all() == triggers
        assert len(repo.list_all()) == 3
