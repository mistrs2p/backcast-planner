"""Sustainability — the observed pace against the workable time.

docs/07-PROGRESS-FEEDBACK.md lists "sustainability" among the
signals. It is the judgment :mod:`~backcasting.domain.velocity`
explicitly declined to make: velocity measures how much work
materialized per calendar day, and *sustainability* compares that
against the workable time the calendar declared for the same
window.

The comparison is utilization — worked ÷ workable — against a
ceiling:

- the default ceiling is 1.0, which is the availability
  declaration's own semantics: working within the declared windows
  is sustainable *by definition of the declaration* (docs/05: the
  user said this time is workable);
- working beyond the workable time is unsustainable whatever the
  ceiling — those hours come from somewhere the user did not
  declare as workable (the evenings, the weekends, the protected
  time), which is the burnout signal;
- a lower ceiling (e.g. 0.8) lets a caller encode "leave headroom"
  policies without touching the availability declaration.

With no workable time there is nothing to utilize
(``utilization`` is ``None``); any work at all over zero workable
time is still beyond capacity, and the status says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import Enum

from backcasting.domain.availability import AvailabilityWindow
from backcasting.domain.calendar_event import CalendarEvent
from backcasting.domain.planned_capacity import workable_time
from backcasting.domain.velocity import Velocity

DEFAULT_MAX_UTILIZATION = 1.0


class SustainabilityError(ValueError):
    """Raised when a sustainability invariant is violated."""


class SustainabilityStatus(str, Enum):
    """Whether the observed pace fits the workable time."""

    SUSTAINABLE = "sustainable"
    UNSUSTAINABLE = "unsustainable"


@dataclass(frozen=True)
class Sustainability:
    """One sustainability reading over a window of time."""

    status: SustainabilityStatus
    worked: timedelta
    workable: timedelta
    utilization: float | None
    max_utilization: float

    def __post_init__(self) -> None:
        if not isinstance(self.status, SustainabilityStatus):
            raise SustainabilityError("status must be a SustainabilityStatus")
        for name in ("worked", "workable"):
            amount = getattr(self, name)
            if not isinstance(amount, timedelta) or amount < timedelta(0):
                raise SustainabilityError(
                    f"{name} must be a non-negative timedelta"
                )
        if not isinstance(self.max_utilization, (int, float)) or isinstance(
            self.max_utilization, bool
        ):
            raise SustainabilityError("max_utilization must be a number")
        if not 0 < self.max_utilization <= 1:
            raise SustainabilityError("max_utilization must be within (0, 1]")
        if self.utilization is not None:
            if not isinstance(self.utilization, (int, float)) or isinstance(
                self.utilization, bool
            ):
                raise SustainabilityError("utilization must be a number or None")
            if self.utilization < 0:
                raise SustainabilityError("utilization must be non-negative")
            if self.utilization != self.worked / self.workable:
                raise SustainabilityError(
                    "utilization must equal worked / workable"
                )
        beyond_capacity = self.worked > self.workable
        over_ceiling = (
            self.utilization is not None
            and self.utilization > self.max_utilization
        )
        if (self.status is SustainabilityStatus.UNSUSTAINABLE) != (
            beyond_capacity or over_ceiling
        ):
            raise SustainabilityError("status must match the utilization")


def assess_sustainability(
    velocity: Velocity,
    windows: tuple[AvailabilityWindow, ...],
    events: tuple[CalendarEvent, ...] = (),
    *,
    max_utilization: float = DEFAULT_MAX_UTILIZATION,
) -> Sustainability:
    """Judge the observed pace against the workable time.

    The workable side is computed with :func:`workable_time` over
    the velocity's own window, so both sides always describe the
    same range — the same-period guarantee the capacity variance
    (TASK-073) relies on.
    """
    if not isinstance(velocity, Velocity):
        raise SustainabilityError("velocity must be a Velocity")
    if not isinstance(windows, tuple):
        raise SustainabilityError("windows must be a tuple of AvailabilityWindow")
    for window in windows:
        if not isinstance(window, AvailabilityWindow):
            raise SustainabilityError("windows must be AvailabilityWindow instances")
    if not isinstance(events, tuple):
        raise SustainabilityError("events must be a tuple of CalendarEvent")
    for event in events:
        if not isinstance(event, CalendarEvent):
            raise SustainabilityError("events must be CalendarEvent instances")
    if not isinstance(max_utilization, (int, float)) or isinstance(
        max_utilization, bool
    ):
        raise SustainabilityError("max_utilization must be a number")
    if not 0 < max_utilization <= 1:
        raise SustainabilityError("max_utilization must be within (0, 1]")

    try:
        workable = workable_time(
            windows,
            events,
            range_start=velocity.window_start,
            range_end=velocity.window_end,
        )
    except ValueError as exc:
        raise SustainabilityError(str(exc)) from exc

    utilization = (
        velocity.worked / workable if workable > timedelta(0) else None
    )
    beyond_capacity = velocity.worked > workable
    over_ceiling = utilization is not None and utilization > max_utilization
    status = (
        SustainabilityStatus.UNSUSTAINABLE
        if (beyond_capacity or over_ceiling)
        else SustainabilityStatus.SUSTAINABLE
    )
    return Sustainability(
        status=status,
        worked=velocity.worked,
        workable=workable,
        utilization=utilization,
        max_utilization=max_utilization,
    )
