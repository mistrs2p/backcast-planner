"""Goal use cases, wired to the persistence port.

The HTTP layer (``backcasting.api.goals``) translates; the domain
(``backcasting.domain.goal``) holds the rules — a non-blank,
bounded title, UUID identity, UTC timestamps. This service is the
smallest wiring between them: create, read, and list, with the
domain's violations surfaced as typed errors so the presentation
layer can map them to statuses without importing domain
exceptions.
"""

from __future__ import annotations

import uuid

from backcasting.domain.goal import Goal, GoalError, create_goal
from backcasting.domain.repositories import GoalRepository


class GoalNotFoundError(LookupError):
    """Raised when a requested goal does not exist."""


class GoalService:
    """The goal use cases (create, read, list), wired to the
    persistence port."""

    def __init__(self, goals: GoalRepository) -> None:
        self._goals = goals

    def create_goal(
        self, *, user_id: uuid.UUID, title: str, description: str = ""
    ) -> Goal:
        """Create a goal for ``user_id`` (pipeline step 1).

        Domain violations (blank or oversized title, non-UUID ids)
        raise :class:`GoalError` — the presentation layer maps them
        to 422.
        """
        goal = create_goal(user_id, title, description=description)
        self._goals.save(goal)
        return goal

    def get_goal(self, goal_id: uuid.UUID) -> Goal:
        """Return the goal, or raise :class:`GoalNotFoundError`."""
        goal = self._goals.get(goal_id)
        if goal is None:
            raise GoalNotFoundError(f"no goal {goal_id}")
        return goal

    def list_for_user(self, user_id: uuid.UUID) -> tuple[Goal, ...]:
        """The user's goals, oldest first."""
        return tuple(self._goals.list_for_user(user_id))
