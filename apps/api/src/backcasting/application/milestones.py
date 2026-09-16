"""Milestone use cases (TASK-110).

A milestone is an intermediate measurable checkpoint on the path
from current state to destination, defined during a RUNNING
backcasting run (``docs/04-BACKCASTING-MODEL.md`` step 10 —
generation after strategy selection; the MVP lets the user pin
checkpoints by hand until the AI flow arrives). The rules live in
``backcasting.domain.milestone``; this service wires them to the
ports: the goal must exist and have a run to attach to.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from backcasting.application.goals import GoalNotFoundError
from backcasting.domain.milestone import (
    Milestone,
    MilestoneError,
    define_milestone,
)
from backcasting.domain.repositories import (
    BackcastingRunRepository,
    GoalRepository,
    MilestoneRepository,
)


class NoBackcastRunError(LookupError):
    """Raised when a goal has no backcasting run to attach
    milestones to (define the backcast first, TASK-109)."""


class MilestoneService:
    """Define and list a goal's checkpoints, wired to the
    persistence ports."""

    def __init__(
        self,
        goals: GoalRepository,
        runs: BackcastingRunRepository,
        milestones: MilestoneRepository,
    ) -> None:
        self._goals = goals
        self._runs = runs
        self._milestones = milestones

    def define_milestone(
        self,
        *,
        goal_id: uuid.UUID,
        title: str,
        target_date: datetime,
        description: str = "",
    ) -> Milestone:
        """Pin a checkpoint on the goal's current run.

        Raises :class:`GoalNotFoundError` for an unknown goal,
        :class:`NoBackcastRunError` when no run exists yet, and
        :class:`MilestoneError` when the domain refuses (blank
        title, target at or before now, a finished run) — the
        presentation layer maps them.
        """
        if self._goals.get(goal_id) is None:
            raise GoalNotFoundError(f"no goal {goal_id}")
        run = self._runs.latest_for_goal(goal_id)
        if run is None:
            raise NoBackcastRunError(f"no backcasting run for goal {goal_id}")
        milestone = define_milestone(
            run, title, target_date, description=description
        )
        self._milestones.save(milestone)
        return milestone

    def list_for_goal(self, goal_id: uuid.UUID) -> tuple[Milestone, ...]:
        """The goal's checkpoints on its current run, earliest
        target first. Empty when no run exists yet — there is
        nothing to attach to, which is not an error."""
        run = self._runs.latest_for_goal(goal_id)
        if run is None:
            return ()
        return tuple(self._milestones.list_for_run(run.run_id))
