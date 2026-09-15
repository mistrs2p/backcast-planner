"""Tests for explicit feedback (TASK-077).

"Explicit user statements" (docs/07): recorded verbatim, unclassified
— the domain validates and stores; interpretation is the reasoning
layer's job (ADR-002).
"""

from __future__ import annotations

import uuid
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.backcasting_run import start_run
from backcasting.domain.current_state import capture_current_state
from backcasting.domain.feedback import (
    MAX_STATEMENT_LENGTH,
    Feedback,
    FeedbackError,
    FeedbackKind,
    feedback_for_subject,
    record_feedback,
)
from backcasting.domain.future_state import define_future_state
from backcasting.domain.gap import calculate_gap
from backcasting.domain.goal import create_goal
from backcasting.domain.repositories import FeedbackRepository

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
CAPTURED = datetime(2026, 1, 5, tzinfo=timezone.utc)
CALCULATED = datetime(2026, 1, 6, tzinfo=timezone.utc)
STARTED = datetime(2026, 1, 6, 12, tzinfo=timezone.utc)
SPOKEN = datetime(2026, 6, 2, tzinfo=timezone.utc)
TARGET_DATE = datetime(2026, 10, 11, tzinfo=timezone.utc)
CHECKPOINT = datetime(2026, 6, 1, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


class TestRecordFeedback:
    def test_record_shape(self) -> None:
        feedback = record_feedback(
            "The evening workload is too heavy.", created_at=SPOKEN
        )
        assert isinstance(feedback.feedback_id, uuid.UUID)
        assert feedback.kind is FeedbackKind.EXPLICIT
        assert feedback.statement == "The evening workload is too heavy."
        assert feedback.created_at == SPOKEN
        assert feedback.subject_id is None

    def test_statement_is_stripped(self) -> None:
        feedback = record_feedback("  Too much.  ", created_at=SPOKEN)
        assert feedback.statement == "Too much."

    def test_injectable_id_and_subject(self) -> None:
        feedback_id = uuid.uuid4()
        subject = uuid.uuid4()
        feedback = record_feedback(
            "This milestone feels off.",
            subject_id=subject,
            feedback_id=feedback_id,
            created_at=SPOKEN,
        )
        assert feedback.feedback_id == feedback_id
        assert feedback.subject_id == subject

    def test_is_immutable(self) -> None:
        feedback = record_feedback("Too much.", created_at=SPOKEN)
        with pytest.raises(FrozenInstanceError):
            feedback.statement = "Just right."  # type: ignore[misc]

    def test_rejects_empty_statements(self) -> None:
        with pytest.raises(FeedbackError, match="non-empty"):
            record_feedback("   ", created_at=SPOKEN)

    def test_rejects_overlong_statements(self) -> None:
        with pytest.raises(FeedbackError, match="at most"):
            record_feedback("x" * (MAX_STATEMENT_LENGTH + 1), created_at=SPOKEN)

    def test_rejects_non_string_statements(self) -> None:
        with pytest.raises(FeedbackError, match="non-empty"):
            record_feedback(42, created_at=SPOKEN)

    def test_rejects_naive_created_at(self) -> None:
        with pytest.raises(FeedbackError, match="created_at must be"):
            record_feedback("Too much.", created_at=datetime(2026, 6, 2))

    def test_rejects_bad_subject_id(self) -> None:
        with pytest.raises(FeedbackError, match="subject_id must be a UUID"):
            record_feedback("Too much.", subject_id="goal", created_at=SPOKEN)

    def test_rejects_bad_kind(self) -> None:
        with pytest.raises(FeedbackError, match="kind must be"):
            record_feedback("Too much.", kind="explicit", created_at=SPOKEN)

    def test_kinds_match_the_spec_split(self) -> None:
        assert {k.value for k in FeedbackKind} == {"explicit", "implicit"}

    def test_direct_construction_validates_like_the_factory(self) -> None:
        with pytest.raises(FeedbackError, match="statement must be"):
            Feedback(
                feedback_id=uuid.uuid4(),
                kind=FeedbackKind.EXPLICIT,
                statement="",
                created_at=SPOKEN,
            )
        with pytest.raises(FeedbackError, match="kind must be"):
            Feedback(
                feedback_id=uuid.uuid4(),
                kind="explicit",
                statement="Too much.",
                created_at=SPOKEN,
            )


class TestFeedbackForSubject:
    def test_filters_by_subject_keeping_input_order(self) -> None:
        subject = uuid.uuid4()
        other = uuid.uuid4()
        first = record_feedback("A", subject_id=subject, created_at=SPOKEN)
        elsewhere = record_feedback("B", subject_id=other, created_at=SPOKEN)
        second = record_feedback("C", subject_id=subject, created_at=SPOKEN + HOUR)
        assert feedback_for_subject((first, elsewhere, second), subject) == (
            first,
            second,
        )

    def test_subjectless_feedback_is_not_matched(self) -> None:
        floating = record_feedback("Overall, fine.", created_at=SPOKEN)
        assert feedback_for_subject((floating,), uuid.uuid4()) == ()

    def test_rejects_bad_arguments(self) -> None:
        with pytest.raises(FeedbackError, match="subject_id must be a UUID"):
            feedback_for_subject((), "subject")
        with pytest.raises(FeedbackError, match="feedbacks must be a tuple"):
            feedback_for_subject([], uuid.uuid4())
        with pytest.raises(FeedbackError, match="Feedback instances"):
            feedback_for_subject(("x",), uuid.uuid4())


class TestFeedbackRepositoryPort:
    def test_in_memory_fake_honours_the_contract(self) -> None:
        repo = InMemoryFeedbackRepository()
        subject = uuid.uuid4()
        early = record_feedback("A", subject_id=subject, created_at=SPOKEN + HOUR)
        late = record_feedback("B", subject_id=subject, created_at=SPOKEN)
        general = record_feedback("C", created_at=SPOKEN + 2 * HOUR)
        for feedback in (early, late, general):
            repo.save(feedback)
        assert repo.get(late.feedback_id) is late
        assert repo.get(uuid.uuid4()) is None
        assert repo.list_for_subject(subject) == (late, early)
        assert repo.list_all() == (late, early, general)

    def test_port_shape(self) -> None:
        assert {"save", "get", "list_for_subject", "list_all"} <= set(
            FeedbackRepository.__abstractmethods__
        )


class InMemoryFeedbackRepository(FeedbackRepository):
    """The reference fake: a dict keyed by id, chronological listings."""

    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, Feedback] = {}

    def save(self, feedback: Feedback) -> None:
        self._by_id[feedback.feedback_id] = feedback

    def get(self, feedback_id: uuid.UUID) -> Feedback | None:
        return self._by_id.get(feedback_id)

    def list_for_subject(self, subject_id: uuid.UUID) -> tuple[Feedback, ...]:
        return tuple(
            sorted(
                (f for f in self._by_id.values() if f.subject_id == subject_id),
                key=lambda f: f.created_at,
            )
        )

    def list_all(self) -> tuple[Feedback, ...]:
        return tuple(sorted(self._by_id.values(), key=lambda f: f.created_at))


class TestWiring:
    @pytest.fixture
    def running_run(self):
        goal = create_goal(uuid.uuid4(), "Pass the exam", created_at=CREATED)
        current = capture_current_state(
            goal.goal_id, "60% of the course completed.", captured_at=CAPTURED
        )
        future = define_future_state(
            goal.goal_id, "Course complete, exam passed.", TARGET_DATE,
            created_at=CREATED,
        )
        gap = calculate_gap(goal, current, future, calculated_at=CALCULATED)
        return start_run(goal, current, future, gap, started_at=STARTED)

    def test_statement_scopes_to_a_milestone_and_meets_the_signals(self, running_run) -> None:
        """A statement about a milestone, recorded beside the same
        week's measurements: the adaptation layer's two inputs."""
        from backcasting.domain.measurement import record_measurement
        from backcasting.domain.metric import Metric, MetricDirection, MetricKind
        from backcasting.domain.milestone import define_milestone

        milestone = define_milestone(
            running_run, "Halfway through the course", CHECKPOINT,
            created_at=STARTED,
        )
        percent = Metric(
            "Course completion", MetricKind.PERCENTAGE, MetricDirection.MAXIMIZE
        )
        reading = record_measurement(
            percent, 55, subject_id=milestone.milestone_id, measured_at=SPOKEN
        )
        statement = record_feedback(
            "The evening sessions are wearing me out.",
            subject_id=milestone.milestone_id,
            created_at=SPOKEN,
        )
        assert feedback_for_subject((statement,), milestone.milestone_id) == (statement,)
        assert statement.subject_id == reading.subject_id
