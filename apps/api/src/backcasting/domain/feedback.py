"""Feedback — the adaptation layer's other input.

"Feedback: explicit or implicit signals" (docs/02-CONCEPTUAL-MODEL.md,
Adaptation Layer); docs/07-PROGRESS-FEEDBACK.md splits it into
"explicit user statements and implicit behavioral signals".

This module holds the shared record. An explicit feedback
(:func:`record_feedback`, the default kind) is a user statement,
recorded verbatim: what the user said, when, and optionally what it
is about. The domain does not interpret the statement — "the LLM
proposes and reasons; the Domain validates and enforces"
(ADR-002, docs/09) — so there is deliberately no sentiment, no
category, no parsed intent here: a statement the domain has
pre-classified is a statement the reasoning layer can no longer see
honestly. Interpretation happens upstream of replanning (docs/08),
where the statement and the signals meet.

Like every observation in this domain (see
:mod:`~backcasting.domain.measurement`), feedback is an immutable
fact of history: no ``updated_at``, no revision path.

The ``subject_id`` (a goal, plan, task, milestone, or outcome id)
scopes the statement to what it is about; a subjectless statement
speaks to the whole situation. Implicit behavioral signals
(TASK-078) join this record's kind as the other half of docs/02's
split.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from backcasting.domain.timezone import UTC, require_utc

MAX_STATEMENT_LENGTH = 5000


class FeedbackError(ValueError):
    """Raised when a feedback invariant is violated."""


class FeedbackKind(str, Enum):
    """docs/02's split: explicit user statements, implicit
    behavioral signals."""

    EXPLICIT = "explicit"
    IMPLICIT = "implicit"


@dataclass(frozen=True)
class Feedback:
    """One recorded signal: what was said, when, about what."""

    feedback_id: uuid.UUID
    kind: FeedbackKind
    statement: str
    created_at: datetime
    subject_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.feedback_id, uuid.UUID):
            raise FeedbackError("feedback_id must be a UUID")
        if not isinstance(self.kind, FeedbackKind):
            raise FeedbackError("kind must be a FeedbackKind")
        statement = self.statement
        if not isinstance(statement, str) or not statement.strip():
            raise FeedbackError("statement must be a non-empty string")
        if len(statement.strip()) > MAX_STATEMENT_LENGTH:
            raise FeedbackError(
                f"statement must be at most {MAX_STATEMENT_LENGTH} characters"
            )
        object.__setattr__(self, "statement", statement.strip())
        require_utc("created_at", self.created_at, error=FeedbackError)
        if self.subject_id is not None and not isinstance(self.subject_id, uuid.UUID):
            raise FeedbackError("subject_id must be a UUID or None")


def record_feedback(
    statement: str,
    *,
    subject_id: uuid.UUID | None = None,
    feedback_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
    kind: FeedbackKind = FeedbackKind.EXPLICIT,
) -> Feedback:
    """Record one user statement (or, with ``kind``, another signal).

    The statement is kept verbatim (stripped, bounded): the domain
    records what was said and leaves the reading of it to the
    reasoning layer (ADR-002).
    """
    if not isinstance(kind, FeedbackKind):
        raise FeedbackError("kind must be a FeedbackKind")
    return Feedback(
        feedback_id=feedback_id if feedback_id is not None else uuid.uuid4(),
        kind=kind,
        statement=statement,
        created_at=created_at if created_at is not None else datetime.now(UTC),
        subject_id=subject_id,
    )


def feedback_for_subject(
    feedbacks: tuple[Feedback, ...],
    subject_id: uuid.UUID,
) -> tuple[Feedback, ...]:
    """The signals about one subject, in input order."""
    if not isinstance(subject_id, uuid.UUID):
        raise FeedbackError("subject_id must be a UUID")
    if not isinstance(feedbacks, tuple):
        raise FeedbackError("feedbacks must be a tuple of Feedback")
    for feedback in feedbacks:
        if not isinstance(feedback, Feedback):
            raise FeedbackError("feedbacks must be Feedback instances")
    return tuple(
        feedback for feedback in feedbacks if feedback.subject_id == subject_id
    )
