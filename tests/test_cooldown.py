"""Tests for cooldown (TASK-082).

The timed half of docs/08's stability controls: persistence asks
"has this held?", cooldown asks "did we just act on it?".
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.cooldown import (
    Cooldown,
    CooldownError,
    cooldown_remaining,
    in_cooldown,
)
from backcasting.domain.execution import create_execution
from backcasting.domain.goal import create_goal
from backcasting.domain.plan import create_plan
from backcasting.domain.persistence import Persistence, assess_persistence
from backcasting.domain.task import create_task, revise_task
from backcasting.domain.threshold import Measure, Threshold, variance_shortfall
from backcasting.domain.trigger import TriggerKind, raise_trigger
from backcasting.domain.variance import progress_variance
from backcasting.domain.progress import take_progress_snapshot

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
MONDAY = datetime(2026, 6, 1, tzinfo=timezone.utc)  # a Monday
HOUR = timedelta(hours=1)
WEEK = timedelta(days=7)


@pytest.fixture
def plan():
    goal = create_goal(uuid.uuid4(), "Ship v2", created_at=CREATED)
    return create_plan(goal, 20 * HOUR, created_at=CREATED)


def _task(plan, hours):
    task = create_task(plan, "Task", created_at=CREATED)
    return revise_task(task, duration=timedelta(hours=hours), updated_at=CREATED)


def _sitting(task, day, start_hour, end_hour):
    day = day.replace(hour=start_hour)
    return create_execution(task, day, day.replace(hour=end_hour), created_at=CREATED)


class TestCooldownRecord:
    def test_holds_the_period(self) -> None:
        cooldown = Cooldown(WEEK)
        assert cooldown.period == WEEK

    def test_zero_period_is_no_cooldown(self) -> None:
        Cooldown(timedelta(0))

    def test_rejects_negative_periods(self) -> None:
        with pytest.raises(CooldownError, match="non-negative timedelta"):
            Cooldown(-HOUR)

    def test_rejects_non_timedeltas(self) -> None:
        with pytest.raises(CooldownError, match="non-negative timedelta"):
            Cooldown("one week")  # type: ignore[arg-type]

    def test_is_immutable(self) -> None:
        from dataclasses import FrozenInstanceError

        cooldown = Cooldown(WEEK)
        with pytest.raises(FrozenInstanceError):
            cooldown.period = HOUR  # type: ignore[misc]


class TestInCooldown:
    def test_suppressed_within_the_period(self) -> None:
        cooldown = Cooldown(WEEK)
        assert in_cooldown(cooldown, MONDAY, at=MONDAY) is True
        assert in_cooldown(cooldown, MONDAY, at=MONDAY + 6 * 24 * HOUR) is True

    def test_free_at_the_moment_the_period_ends(self) -> None:
        cooldown = Cooldown(WEEK)
        assert in_cooldown(cooldown, MONDAY, at=MONDAY + WEEK) is False

    def test_free_after_the_period(self) -> None:
        cooldown = Cooldown(WEEK)
        assert in_cooldown(cooldown, MONDAY, at=MONDAY + WEEK + HOUR) is False

    def test_zero_period_never_suppresses(self) -> None:
        cooldown = Cooldown(timedelta(0))
        assert in_cooldown(cooldown, MONDAY, at=MONDAY) is False

    def test_rejects_bad_arguments(self) -> None:
        cooldown = Cooldown(WEEK)
        with pytest.raises(CooldownError, match="cooldown must be"):
            in_cooldown("a week", MONDAY, at=MONDAY)  # type: ignore[arg-type]
        with pytest.raises(CooldownError, match="last_action_at must be"):
            in_cooldown(cooldown, "Monday", at=MONDAY)  # type: ignore[arg-type]
        with pytest.raises(CooldownError, match="last_action_at must be"):
            in_cooldown(cooldown, datetime(2026, 6, 1), at=MONDAY)
        with pytest.raises(CooldownError, match="at must be"):
            in_cooldown(cooldown, MONDAY, at=datetime(2026, 6, 1))
        with pytest.raises(CooldownError, match="at must not precede"):
            in_cooldown(cooldown, MONDAY, at=MONDAY - HOUR)


class TestCooldownRemaining:
    def test_counts_down_the_period(self) -> None:
        cooldown = Cooldown(WEEK)
        assert cooldown_remaining(cooldown, MONDAY, at=MONDAY) == WEEK
        assert cooldown_remaining(cooldown, MONDAY, at=MONDAY + 3 * 24 * HOUR) == 4 * 24 * HOUR

    def test_zero_at_and_after_the_end(self) -> None:
        cooldown = Cooldown(WEEK)
        assert cooldown_remaining(cooldown, MONDAY, at=MONDAY + WEEK) == timedelta(0)
        assert cooldown_remaining(cooldown, MONDAY, at=MONDAY + 2 * WEEK) == timedelta(0)

    def test_rejects_bad_arguments(self) -> None:
        cooldown = Cooldown(WEEK)
        with pytest.raises(CooldownError, match="cooldown must be"):
            cooldown_remaining("a week", MONDAY, at=MONDAY)  # type: ignore[arg-type]
        with pytest.raises(CooldownError, match="at must not precede"):
            cooldown_remaining(cooldown, MONDAY, at=MONDAY - HOUR)


class TestWiring:
    def test_a_reconfirmed_condition_waits_out_the_cooldown(self, plan) -> None:
        """The full stability story: the condition holds and is acted
        on Monday; it still holds Tuesday (re-confirmed), but the
        action is suppressed; a week later, acting is free again."""
        task = _task(plan, 8)
        hours = Threshold(Measure.SHORTFALL, 2 * HOUR, 1 * HOUR)
        patience = Persistence(2)
        cooldown = Cooldown(WEEK)

        acted_on = MONDAY
        # Tuesday's snapshot: two weeks of one hour each on an 8h task.
        sittings = (
            _sitting(task, MONDAY - WEEK, 9, 10),
            _sitting(task, MONDAY, 9, 10),
        )
        tuesday = MONDAY + 24 * HOUR
        magnitudes = tuple(
            variance_shortfall(
                progress_variance(
                    take_progress_snapshot(plan, (task,), sittings[: i + 1], at=acted_on)
                )
            )
            for i in range(len(sittings))
        )
        reading = assess_persistence(hours, magnitudes)
        assert reading.confirms(patience)  # still a state of the world

        assert in_cooldown(cooldown, acted_on, at=tuesday) is True
        assert cooldown_remaining(cooldown, acted_on, at=tuesday) == 6 * 24 * HOUR
        assert in_cooldown(cooldown, acted_on, at=acted_on + WEEK) is False

    def test_trigger_and_clock_side_by_side(self, plan) -> None:
        """The trigger records what was seen; the clock, entirely
        separately, records when the system last acted — the policy
        (TASK-083) will join them."""
        task = _task(plan, 8)
        sitting = (_sitting(task, MONDAY, 9, 11),)  # 2h of 8h: over the bound
        snapshot = take_progress_snapshot(plan, (task,), sitting, at=MONDAY + WEEK)
        slip = variance_shortfall(progress_variance(snapshot))
        hours = Threshold(Measure.SHORTFALL, 2 * HOUR, 1 * HOUR)
        assert hours.is_exceeded(slip)

        trigger = raise_trigger(
            TriggerKind.PROGRESS, f"{slip} behind plan.", observed_at=MONDAY + WEEK
        )
        cooldown = Cooldown(WEEK)
        last_action = MONDAY  # an earlier replan acted last Monday

        assert in_cooldown(cooldown, last_action, at=trigger.observed_at) is False
