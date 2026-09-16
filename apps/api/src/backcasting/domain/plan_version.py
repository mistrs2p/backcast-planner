"""Plan versioning domain model.

"Every meaningful replan produces a traceable plan version with
reason, source run and change set" (docs/08-REPLANNING-MODEL.md).
A :class:`PlanVersion` is that trace: one append-only record per
meaningful change to a plan, naming *why* it changed, which backcasting
run produced it (if any), and *what* changed.

Modeling decisions within the spec's latitude:

- Versions are history, not state: they are immutable records keyed to
  the plan they belong to, with strictly increasing per-plan version
  numbers. The current state of the plan lives in the :class:`Plan`
  value itself; versions explain how it got there.
- A version's :class:`PlanChangeSet` covers the *content* a
  replan may modify — the plan's ``title`` and ``workload``, and,
  for a local replan (TASK-085), the task it revised. Lifecycle moves
  (ACTIVE → SUPERSEDED, …) are not change-set content: they flow
  through :func:`backcasting.domain.plan.transition_plan` with their
  own rules, and a caller composes the two when a replan both changes
  content and moves status.
- A change set that changes nothing is not a *meaningful* replan and
  is rejected — every version must leave the plan different from how
  it found it.

Rules:

- ``version`` is a positive integer, unique and strictly increasing
  per plan.
- ``reason`` is non-empty free text ≤ 500 characters (stripped).
- ``source_run_id`` is optional provenance — the run whose result
  produced this version (a manual replan has none).
- ``created_at`` is timezone-aware UTC.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone

from backcasting.domain.plan import Plan
from backcasting.domain.timezone import UTC, require_utc

MAX_REASON_LENGTH = 500


class PlanVersionError(ValueError):
    """Raised when a plan-versioning invariant is violated."""


@dataclass(frozen=True)
class PlanChangeSet:
    """What one plan version changed: new values, or None to keep."""

    title: str | None = None
    workload: timedelta | None = None
    revised_task_ids: tuple[uuid.UUID, ...] = ()

    def __post_init__(self) -> None:
        if self.title is not None:
            if not isinstance(self.title, str):
                raise PlanVersionError("title must be a string or None")
            if len(self.title) > 200:
                raise PlanVersionError("title must be at most 200 characters")
        if self.workload is not None:
            if (
                not isinstance(self.workload, timedelta)
                or self.workload < timedelta(0)
            ):
                raise PlanVersionError(
                    "workload must be a non-negative timedelta or None"
                )
        if not isinstance(self.revised_task_ids, tuple):
            raise PlanVersionError("revised_task_ids must be a tuple of UUIDs")
        for task_id in self.revised_task_ids:
            if not isinstance(task_id, uuid.UUID):
                raise PlanVersionError("revised_task_ids must be UUID instances")


@dataclass(frozen=True)
class PlanVersion:
    """One traceable version of a plan: why, from where, what changed."""

    version_id: uuid.UUID
    plan_id: uuid.UUID
    version: int
    reason: str
    change_set: PlanChangeSet
    source_run_id: uuid.UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not isinstance(self.version_id, uuid.UUID):
            raise PlanVersionError("version_id must be a UUID")
        if not isinstance(self.plan_id, uuid.UUID):
            raise PlanVersionError("plan_id must be a UUID")
        if isinstance(self.version, bool) or not isinstance(self.version, int):
            raise PlanVersionError("version must be an integer")
        if self.version < 1:
            raise PlanVersionError("version must be at least 1")
        reason = self.reason
        if not isinstance(reason, str):
            raise PlanVersionError("reason must be a string")
        reason = reason.strip()
        if not reason:
            raise PlanVersionError("reason must not be empty")
        if len(reason) > MAX_REASON_LENGTH:
            raise PlanVersionError(
                f"reason must be at most {MAX_REASON_LENGTH} characters"
            )
        object.__setattr__(self, "reason", reason)
        if not isinstance(self.change_set, PlanChangeSet):
            raise PlanVersionError("change_set must be a PlanChangeSet")
        if self.source_run_id is not None and not isinstance(
            self.source_run_id, uuid.UUID
        ):
            raise PlanVersionError("source_run_id must be a UUID or None")
        require_utc("created_at", self.created_at, error=PlanVersionError)


def apply_plan_version(
    plan: Plan,
    history: tuple[PlanVersion, ...],
    *,
    reason: str,
    change_set: PlanChangeSet,
    source_run_id: uuid.UUID | None = None,
    version_id: uuid.UUID | None = None,
    at: datetime | None = None,
) -> tuple[Plan, PlanVersion]:
    """Apply a meaningful change to ``plan``, recording its version.

    Returns the next :class:`Plan` value (content fields moved, no
    status change) and the :class:`PlanVersion` tracing the change.
    ``history`` is the plan's existing version trail; the new version
    number is one past its highest. A change set whose applied values
    leave the plan unchanged is rejected — a version must be a
    *meaningful* replan.
    """
    if not isinstance(plan, Plan):
        raise TypeError("plan must be a Plan")
    if not isinstance(history, tuple):
        raise PlanVersionError("history must be a tuple of PlanVersion")
    seen: set[int] = set()
    highest = 0
    for record in history:
        if not isinstance(record, PlanVersion):
            raise PlanVersionError("history must be PlanVersion instances")
        if record.plan_id != plan.plan_id:
            raise PlanVersionError("version does not belong to this plan")
        if record.version in seen:
            raise PlanVersionError(
                f"duplicate version number {record.version} in history"
            )
        seen.add(record.version)
        highest = max(highest, record.version)

    title = change_set.title if change_set.title is not None else plan.title
    workload = (
        change_set.workload if change_set.workload is not None else plan.workload
    )
    if (
        title == plan.title
        and workload == plan.workload
        and not change_set.revised_task_ids
    ):
        raise PlanVersionError(
            "change set changes nothing; a plan version must be a meaningful replan"
        )

    now = at if at is not None else datetime.now(UTC)
    revised = replace(plan, title=title, workload=workload, updated_at=now)
    version = PlanVersion(
        version_id=version_id if version_id is not None else uuid.uuid4(),
        plan_id=plan.plan_id,
        version=highest + 1,
        reason=reason,
        change_set=change_set,
        source_run_id=source_run_id,
        created_at=now,
    )
    return revised, version


def latest_version(history: tuple[PlanVersion, ...]) -> PlanVersion | None:
    """The most recent version in a trail, or ``None`` if there is none."""
    if not isinstance(history, tuple):
        raise PlanVersionError("history must be a tuple of PlanVersion")
    for record in history:
        if not isinstance(record, PlanVersion):
            raise PlanVersionError("history must be PlanVersion instances")
    if not history:
        return None
    return max(history, key=lambda record: record.version)
