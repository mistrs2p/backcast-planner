"""Backcast use cases — steps 1–4 of the pipeline, wired to the
persistence ports (TASK-109).

``docs/04-BACKCASTING-MODEL.md`` opens with the intent layer:
normalize the goal (done — the goal exists), capture the current
state, define the desired future, and calculate the gap. This
service composes those domain operations for one goal and records
the artifacts so the UI can visualize the chain. The remaining
pipeline steps (strategies, milestones, planning) belong to later
tasks; replanning (docs/08) will revisit redefinition.

The MVP pins one backcast per goal: one future state (the 1:1 of
docs/03-DOMAIN-MODEL.md) and the gap calculated for it. Capturing
a *new* current state is a natural act (that is what progress
measurement does, TASK-114); redefining the destination is an
explicit goal revision, out of scope here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from backcasting.application.goals import GoalNotFoundError
from backcasting.domain.current_state import CurrentState, capture_current_state
from backcasting.domain.future_state import FutureState, define_future_state
from backcasting.domain.gap import Gap, calculate_gap
from backcasting.domain.repositories import (
    CurrentStateRepository,
    FutureStateRepository,
    GapRepository,
    GoalRepository,
)


class BackcastAlreadyExistsError(Exception):
    """Raised when a goal already has a backcast (one per goal in
    the MVP; redefinition arrives with replanning)."""


@dataclass(frozen=True)
class BackcastBundle:
    """The backcast's intent layer for one goal, as the UI shows
    it: where we are, where we're going, and the recorded distance
    between the two."""

    current: CurrentState
    future: FutureState
    gap: Gap


class BackcastService:
    """Define and read a goal's backcast context (pipeline steps
    1–4), wired to the persistence ports."""

    def __init__(
        self,
        goals: GoalRepository,
        current_states: CurrentStateRepository,
        future_states: FutureStateRepository,
        gaps: GapRepository,
    ) -> None:
        self._goals = goals
        self._current_states = current_states
        self._future_states = future_states
        self._gaps = gaps

    def define_backcast(
        self,
        *,
        goal_id: uuid.UUID,
        current_narrative: str,
        future_description: str,
        target_date: datetime,
        gap_narrative: str = "",
    ) -> BackcastBundle:
        """Capture the current state, define the future state, and
        calculate the gap — recording all three.

        Raises :class:`GoalNotFoundError` for an unknown goal,
        :class:`BackcastAlreadyExistsError` when the goal already
        has a backcast, and the domain's errors
        (:class:`~backcasting.domain.current_state.CurrentStateError`,
        :class:`~backcasting.domain.future_state.FutureStateError`,
        :class:`~backcasting.domain.gap.GapError`) for invariant
        violations — the presentation layer maps them.
        """
        goal = self._goals.get(goal_id)
        if goal is None:
            raise GoalNotFoundError(f"no goal {goal_id}")
        if self._future_states.get_for_goal(goal_id) is not None:
            raise BackcastAlreadyExistsError(
                "goal already has a backcast (one per goal in the MVP)"
            )
        current = capture_current_state(goal_id, current_narrative)
        future = define_future_state(goal_id, future_description, target_date)
        gap = calculate_gap(
            goal, current, future, narrative=gap_narrative
        )
        self._current_states.save(current)
        self._future_states.save(future)
        self._gaps.save(gap)
        return BackcastBundle(current=current, future=future, gap=gap)

    def get_backcast(self, goal_id: uuid.UUID) -> BackcastBundle | None:
        """The goal's backcast, or ``None`` when none is defined.

        Composed from the recorded artifacts; the latest current
        snapshot is used, so later captures (progress measurement)
        appear here while the destination and its recorded gap stay
        pinned.
        """
        future = self._future_states.get_for_goal(goal_id)
        gap = self._gaps.get_for_goal(goal_id)
        current = self._current_states.latest_for_goal(goal_id)
        if future is None or gap is None or current is None:
            return None
        return BackcastBundle(current=current, future=future, gap=gap)
