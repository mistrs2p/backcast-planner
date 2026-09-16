"""Trigger — an observed condition that may initiate adaptation.

docs/08-REPLANNING-MODEL.md names the trigger sources — progress,
capacity, time, calendar, constraint, resource, dependency,
behavior, goal, system — and the stability controls (persistence
thresholds, cooldown, hysteresis; TASK-080 through TASK-082) that
decide when a trigger has *persisted* enough to act on.

This module is the record those decisions are made about: what was
observed (``kind`` + ``detail``), and when. A Trigger states a
condition; it does not decide anything — whether it persists
(thresholds), is still cooling down (cooldown), or warrants a
reschedule, a replan, or a goal revision (the adaptation ladder) is
upstream. Detection (which signal raises which trigger) is
likewise upstream: the signals modules
(:mod:`~backcasting.domain.variance`, :mod:`~backcasting.domain.goal_health`,
:mod:`~backcasting.domain.feedback`) state their readings, and the
detection layer turns noteworthy ones into triggers.

Like every observation in this domain, a trigger is an immutable
fact of history.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from backcasting.domain.timezone import UTC, require_utc

MAX_DETAIL_LENGTH = 2000


class TriggerError(ValueError):
    """Raised when a trigger invariant is violated."""


class TriggerKind(str, Enum):
    """The trigger sources (docs/08-REPLANNING-MODEL.md)."""

    PROGRESS = "progress"
    CAPACITY = "capacity"
    TIME = "time"
    CALENDAR = "calendar"
    CONSTRAINT = "constraint"
    RESOURCE = "resource"
    DEPENDENCY = "dependency"
    BEHAVIOR = "behavior"
    GOAL = "goal"
    SYSTEM = "system"


@dataclass(frozen=True)
class Trigger:
    """One observed condition: what, and when."""

    trigger_id: uuid.UUID
    kind: TriggerKind
    detail: str
    observed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.trigger_id, uuid.UUID):
            raise TriggerError("trigger_id must be a UUID")
        if not isinstance(self.kind, TriggerKind):
            raise TriggerError("kind must be a TriggerKind")
        detail = self.detail
        if not isinstance(detail, str) or not detail.strip():
            raise TriggerError("detail must be a non-empty string")
        if len(detail.strip()) > MAX_DETAIL_LENGTH:
            raise TriggerError(
                f"detail must be at most {MAX_DETAIL_LENGTH} characters"
            )
        object.__setattr__(self, "detail", detail.strip())
        require_utc("observed_at", self.observed_at, error=TriggerError)


def raise_trigger(
    kind: TriggerKind,
    detail: str,
    *,
    observed_at: datetime | None = None,
    trigger_id: uuid.UUID | None = None,
) -> Trigger:
    """Record one observed condition.

    ``detail`` states the observation itself (what was seen, in
    what terms); interpreting it — thresholding it, cooling it
    down, acting on it — is the stability controls' and the
    adaptation ladder's job, not this factory's.
    """
    if not isinstance(kind, TriggerKind):
        raise TriggerError("kind must be a TriggerKind")
    return Trigger(
        trigger_id=trigger_id if trigger_id is not None else uuid.uuid4(),
        kind=kind,
        detail=detail,
        observed_at=observed_at if observed_at is not None else datetime.now(UTC),
    )


def triggers_of_kind(
    triggers: tuple[Trigger, ...],
    kind: TriggerKind,
) -> tuple[Trigger, ...]:
    """The triggers of one kind, in input order."""
    if not isinstance(kind, TriggerKind):
        raise TriggerError("kind must be a TriggerKind")
    if not isinstance(triggers, tuple):
        raise TriggerError("triggers must be a tuple of Trigger")
    for trigger in triggers:
        if not isinstance(trigger, Trigger):
            raise TriggerError("triggers must be Trigger instances")
    return tuple(trigger for trigger in triggers if trigger.kind == kind)
