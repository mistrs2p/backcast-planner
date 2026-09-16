"""Tests for the replanning policy (TASK-083).

docs/08's vocabulary assembled: three levels, three modes, the
stability controls — and the gates that say what the system may do
about a condition, and when. The minimum-change principle picks the
lowest level that addresses it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.cooldown import Cooldown
from backcasting.domain.persistence import Persistence
from backcasting.domain.replanning_policy import (
    ReplanningLevel,
    ReplanningMode,
    ReplanningPolicy,
    ReplanningPolicyError,
    minimal_level,
)

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
MONDAY = datetime(2026, 6, 1, tzinfo=timezone.utc)  # a Monday
HOUR = timedelta(hours=1)
WEEK = timedelta(days=7)


def _policy(mode: ReplanningMode) -> ReplanningPolicy:
    return ReplanningPolicy(mode, Cooldown(WEEK), Persistence(2))


class TestLevelAndModeVocabulary:
    def test_levels_match_the_spec_ladder(self) -> None:
        assert {level.value for level in ReplanningLevel} == {
            "reschedule",
            "replan",
            "goal_revision",
        }

    def test_modes_match_the_spec_list(self) -> None:
        assert {mode.value for mode in ReplanningMode} == {
            "manual",
            "suggest",
            "automatic",
        }


class TestReplanningPolicyRecord:
    def test_holds_the_stance(self) -> None:
        policy = ReplanningPolicy(
            ReplanningMode.SUGGEST, Cooldown(WEEK), Persistence(3)
        )
        assert policy.mode is ReplanningMode.SUGGEST
        assert policy.cooldown.period == WEEK
        assert policy.persistence.required == 3

    def test_rejects_bad_fields(self) -> None:
        with pytest.raises(ReplanningPolicyError, match="mode must be"):
            ReplanningPolicy("auto", Cooldown(WEEK), Persistence(2))  # type: ignore[arg-type]
        with pytest.raises(ReplanningPolicyError, match="cooldown must be"):
            ReplanningPolicy(ReplanningMode.AUTOMATIC, "a week", Persistence(2))  # type: ignore[arg-type]
        with pytest.raises(ReplanningPolicyError, match="persistence must be"):
            ReplanningPolicy(ReplanningMode.AUTOMATIC, Cooldown(WEEK), 2)  # type: ignore[arg-type]

    def test_is_immutable(self) -> None:
        from dataclasses import FrozenInstanceError

        policy = _policy(ReplanningMode.AUTOMATIC)
        with pytest.raises(FrozenInstanceError):
            policy.mode = ReplanningMode.MANUAL  # type: ignore[misc]


class TestPermits:
    def test_automatic_acts_on_the_lower_levels(self) -> None:
        policy = _policy(ReplanningMode.AUTOMATIC)
        assert policy.permits(
            ReplanningLevel.RESCHEDULE, last_offered_at=None, at=MONDAY
        )
        assert policy.permits(
            ReplanningLevel.REPLAN, last_offered_at=None, at=MONDAY
        )

    def test_goal_revision_is_never_automatic(self) -> None:
        """docs/08 level 3 'explicitly change the destination': the
        destination is the user's, whatever the mode."""
        policy = _policy(ReplanningMode.AUTOMATIC)
        assert not policy.permits(
            ReplanningLevel.GOAL_REVISION, last_offered_at=None, at=MONDAY
        )

    def test_automatic_waits_out_the_cooldown(self) -> None:
        policy = _policy(ReplanningMode.AUTOMATIC)
        last = MONDAY
        assert not policy.permits(
            ReplanningLevel.REPLAN, last_offered_at=last, at=MONDAY + 3 * 24 * HOUR
        )
        assert policy.permits(
            ReplanningLevel.REPLAN, last_offered_at=last, at=MONDAY + WEEK
        )

    def test_manual_never_acts(self) -> None:
        policy = _policy(ReplanningMode.MANUAL)
        for level in ReplanningLevel:
            assert not policy.permits(level, last_offered_at=None, at=MONDAY)

    def test_suggest_never_acts(self) -> None:
        """The system proposes; the user acts."""
        policy = _policy(ReplanningMode.SUGGEST)
        for level in (ReplanningLevel.RESCHEDULE, ReplanningLevel.REPLAN):
            assert not policy.permits(level, last_offered_at=None, at=MONDAY)

    def test_rejects_bad_arguments(self) -> None:
        policy = _policy(ReplanningMode.AUTOMATIC)
        with pytest.raises(ReplanningPolicyError, match="level must be"):
            policy.permits("replan", last_offered_at=None, at=MONDAY)  # type: ignore[arg-type]
        with pytest.raises(ReplanningPolicyError, match="at must be"):
            policy.permits(
                ReplanningLevel.REPLAN, last_offered_at=None, at=datetime(2026, 6, 1)
            )
        with pytest.raises(ReplanningPolicyError, match="last_offered_at must be"):
            policy.permits(
                ReplanningLevel.REPLAN,
                last_offered_at=datetime(2026, 6, 1),  # type: ignore[arg-type]
                at=MONDAY,
            )


class TestSuggests:
    def test_suggest_proposes_the_lower_levels(self) -> None:
        policy = _policy(ReplanningMode.SUGGEST)
        assert policy.suggests(
            ReplanningLevel.RESCHEDULE, last_offered_at=None, at=MONDAY
        )
        assert policy.suggests(
            ReplanningLevel.REPLAN, last_offered_at=None, at=MONDAY
        )

    def test_suggest_proposes_goal_revision(self) -> None:
        """The destination stays the user's decision — but the system
        may point out that the destination is the problem."""
        policy = _policy(ReplanningMode.SUGGEST)
        assert policy.suggests(
            ReplanningLevel.GOAL_REVISION, last_offered_at=None, at=MONDAY
        )

    def test_suggestions_are_cooled_down(self) -> None:
        """A suggestion the user has just declined is not repeated
        hourly."""
        policy = _policy(ReplanningMode.SUGGEST)
        last = MONDAY
        assert not policy.suggests(
            ReplanningLevel.REPLAN, last_offered_at=last, at=MONDAY + HOUR
        )
        assert policy.suggests(
            ReplanningLevel.REPLAN, last_offered_at=last, at=MONDAY + WEEK
        )

    def test_manual_never_suggests(self) -> None:
        policy = _policy(ReplanningMode.MANUAL)
        assert not policy.suggests(
            ReplanningLevel.REPLAN, last_offered_at=None, at=MONDAY
        )

    def test_automatic_has_no_need_to_suggest(self) -> None:
        policy = _policy(ReplanningMode.AUTOMATIC)
        assert not policy.suggests(
            ReplanningLevel.RESCHEDULE, last_offered_at=None, at=MONDAY
        )

    def test_rejects_bad_arguments(self) -> None:
        policy = _policy(ReplanningMode.SUGGEST)
        with pytest.raises(ReplanningPolicyError, match="level must be"):
            policy.suggests("replan", last_offered_at=None, at=MONDAY)  # type: ignore[arg-type]
        with pytest.raises(ReplanningPolicyError, match="at must be"):
            policy.suggests(
                ReplanningLevel.REPLAN, last_offered_at=None, at=datetime(2026, 6, 1)
            )


class TestMinimalLevel:
    def test_the_lowest_level_wins(self) -> None:
        assert (
            minimal_level((ReplanningLevel.REPLAN, ReplanningLevel.RESCHEDULE))
            is ReplanningLevel.RESCHEDULE
        )

    def test_reschedule_before_replan_before_goal_revision(self) -> None:
        assert (
            minimal_level(
                (
                    ReplanningLevel.GOAL_REVISION,
                    ReplanningLevel.REPLAN,
                    ReplanningLevel.RESCHEDULE,
                )
            )
            is ReplanningLevel.RESCHEDULE
        )
        assert (
            minimal_level((ReplanningLevel.GOAL_REVISION, ReplanningLevel.REPLAN))
            is ReplanningLevel.REPLAN
        )

    def test_single_level_passes_through(self) -> None:
        assert minimal_level((ReplanningLevel.GOAL_REVISION,)) is (
            ReplanningLevel.GOAL_REVISION
        )

    def test_empty_is_none(self) -> None:
        assert minimal_level(()) is None

    def test_rejects_bad_arguments(self) -> None:
        with pytest.raises(ReplanningPolicyError, match="levels must be a tuple"):
            minimal_level([ReplanningLevel.REPLAN])  # type: ignore[arg-type]
        with pytest.raises(ReplanningPolicyError, match="level must be"):
            minimal_level(("replan",))  # type: ignore[arg-type]


class TestWiring:
    def test_a_confirmed_condition_reaches_the_policy(self) -> None:
        """The assembled story: the persistence the policy demands is
        the persistence the reading must show; the level the ladder
        picks is the level the policy gates."""
        from backcasting.domain.execution import create_execution
        from backcasting.domain.goal import create_goal
        from backcasting.domain.plan import create_plan
        from backcasting.domain.persistence import assess_persistence
        from backcasting.domain.progress import take_progress_snapshot
        from backcasting.domain.task import create_task, revise_task
        from backcasting.domain.threshold import Measure, Threshold, variance_shortfall
        from backcasting.domain.trigger import TriggerKind, raise_trigger
        from backcasting.domain.variance import progress_variance

        goal = create_goal(uuid.uuid4(), "Ship v2", created_at=CREATED)
        plan = create_plan(goal, 20 * HOUR, created_at=CREATED)
        task = create_task(plan, "Task", created_at=CREATED)
        task = revise_task(task, duration=8 * HOUR, updated_at=CREATED)
        # Two weeks of one hour each: the slip holds over the bound.
        sittings = (
            create_execution(
                task, MONDAY - WEEK, MONDAY - WEEK + HOUR, created_at=CREATED
            ),
            create_execution(task, MONDAY, MONDAY + HOUR, created_at=CREATED),
        )
        magnitudes = tuple(
            variance_shortfall(
                progress_variance(
                    take_progress_snapshot(
                        plan, (task,), sittings[: i + 1], at=MONDAY + HOUR
                    )
                )
            )
            for i in range(len(sittings))
        )
        hours = Threshold(Measure.SHORTFALL, 2 * HOUR, 1 * HOUR)

        policy = _policy(ReplanningMode.AUTOMATIC)
        reading = assess_persistence(hours, magnitudes)
        assert reading.confirms(policy.persistence)

        trigger = raise_trigger(
            TriggerKind.PROGRESS, "Two consecutive weeks behind plan.",
            observed_at=MONDAY + HOUR,
        )
        # The conflict-resolution ladder (docs/06) already runs
        # reschedule-first; the minimum-change principle agrees.
        level = minimal_level(
            (ReplanningLevel.RESCHEDULE, ReplanningLevel.REPLAN)
        )
        assert level is ReplanningLevel.RESCHEDULE
        assert policy.permits(level, last_offered_at=None, at=trigger.observed_at)

    def test_a_condition_within_cooldown_holds_even_if_confirmed(self) -> None:
        """Stability composes: the reading confirms, the ladder picks,
        and the clock still says wait — the system replanned this
        plan an hour ago and will not do so again this week."""
        policy = _policy(ReplanningMode.AUTOMATIC)
        last_replan = MONDAY
        at = MONDAY + HOUR
        assert policy.permits(
            ReplanningLevel.REPLAN, last_offered_at=None, at=at
        )
        assert not policy.permits(
            ReplanningLevel.REPLAN, last_offered_at=last_replan, at=at
        )
