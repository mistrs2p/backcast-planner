"""Repository interfaces — the domain's persistence ports.

The domain layer defines *what* it needs from persistence; the
infrastructure layer decides *how* (SQLAlchemy + PostgreSQL per ADR-007).
These abstract interfaces keep the dependency direction pointing inward
(AGENTS.md §4): domain code never imports an ORM, and infrastructure
implements these contracts.

Conventions:

- Entities are immutable; repositories store the instance given and return
  the instance stored — identity (UUID) is the key.
- ``get``/lookup methods return ``None`` when nothing matches; absence is
  not an error.
- ``save`` performs insert-or-replace keyed by the entity's id: the domain
  produces new instances on change, so there is no separate update path.
- Implementations raise :class:`RepositoryError` for infrastructure
  failures so callers never see driver-specific exceptions.
- The Future State port exposes a single destination per goal (1:1 in the
  MVP, docs/03-DOMAIN-MODEL.md); enforcing that uniqueness is the
  implementation's job.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import Sequence

from backcasting.domain.calendar import Calendar
from backcasting.domain.calendar_event import CalendarEvent
from backcasting.domain.current_state import CurrentState
from backcasting.domain.future_state import FutureState
from backcasting.domain.goal import Goal
from backcasting.domain.user import Email, User


class RepositoryError(RuntimeError):
    """Raised by implementations on infrastructure failures."""


class UserRepository(ABC):
    """Persistence port for :class:`~backcasting.domain.user.User`."""

    @abstractmethod
    def save(self, user: User) -> None:
        """Insert or replace the user keyed by ``user_id``."""

    @abstractmethod
    def get(self, user_id: uuid.UUID) -> User | None:
        """Return the user with ``user_id``, or ``None``."""

    @abstractmethod
    def get_by_email(self, email: Email) -> User | None:
        """Return the user with the (normalized) email, or ``None``."""


class GoalRepository(ABC):
    """Persistence port for :class:`~backcasting.domain.goal.Goal`."""

    @abstractmethod
    def save(self, goal: Goal) -> None:
        """Insert or replace the goal keyed by ``goal_id``."""

    @abstractmethod
    def get(self, goal_id: uuid.UUID) -> Goal | None:
        """Return the goal with ``goal_id``, or ``None``."""

    @abstractmethod
    def list_for_user(self, user_id: uuid.UUID) -> Sequence[Goal]:
        """Return the user's goals, oldest first."""


class CurrentStateRepository(ABC):
    """Persistence port for :class:`~backcasting.domain.current_state.CurrentState`."""

    @abstractmethod
    def save(self, state: CurrentState) -> None:
        """Insert or replace the snapshot keyed by ``state_id``."""

    @abstractmethod
    def get(self, state_id: uuid.UUID) -> CurrentState | None:
        """Return the snapshot with ``state_id``, or ``None``."""

    @abstractmethod
    def list_for_goal(self, goal_id: uuid.UUID) -> Sequence[CurrentState]:
        """Return the goal's snapshots, oldest capture first."""

    @abstractmethod
    def latest_for_goal(self, goal_id: uuid.UUID) -> CurrentState | None:
        """Return the most recently captured snapshot, or ``None``."""


class FutureStateRepository(ABC):
    """Persistence port for :class:`~backcasting.domain.future_state.FutureState`."""

    @abstractmethod
    def save(self, state: FutureState) -> None:
        """Insert or replace the destination keyed by ``state_id``."""

    @abstractmethod
    def get(self, state_id: uuid.UUID) -> FutureState | None:
        """Return the destination with ``state_id``, or ``None``."""

    @abstractmethod
    def get_for_goal(self, goal_id: uuid.UUID) -> FutureState | None:
        """Return the goal's destination (1:1 in the MVP), or ``None``."""


class CalendarRepository(ABC):
    """Persistence port for :class:`~backcasting.domain.calendar.Calendar`.

    A user owns one calendar in the MVP ("User owns calendar",
    docs/03-DOMAIN-MODEL.md); ``get_by_user`` therefore returns the
    user's single calendar or ``None``.
    """

    @abstractmethod
    def save(self, calendar: Calendar) -> None:
        """Insert or replace the calendar keyed by ``calendar_id``."""

    @abstractmethod
    def get(self, calendar_id: uuid.UUID) -> Calendar | None:
        """Return the calendar with ``calendar_id``, or ``None``."""

    @abstractmethod
    def get_by_user(self, user_id: uuid.UUID) -> Calendar | None:
        """Return the user's calendar, or ``None``."""


class CalendarEventRepository(ABC):
    """Persistence port for :class:`~backcasting.domain.calendar_event.CalendarEvent`."""

    @abstractmethod
    def save(self, event: CalendarEvent) -> None:
        """Insert or replace the event keyed by ``event_id``."""

    @abstractmethod
    def list_for_calendar(self, calendar_id: uuid.UUID) -> Sequence[CalendarEvent]:
        """Return the calendar's events, earliest start first."""
