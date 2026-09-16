"""Tests for persistence detection (TASK-081).

A condition that crosses a threshold once may be noise; one that
holds for consecutive observations is a state of the world. The
hysteresis state machine of TASK-080, run over time.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone

import pytest

from backcasting.domain.execution import create_execution
from backcasting.domain.goal import create_goal
from backcasting.domain.persistence import (
    Persistence,
    PersistenceError,
    PersistenceReading,
    assess_persistence,
)
from backcasting.domain.plan import create_plan
from backcasting.domain.progress import take_progress_snapshot
from backcasting.domain.task import create_task, revise_task
from backcasting.domain.threshold import (
    Measure,
    Threshold,
    variance_shortfall,
)
from backcasting.domain.variance import progress_variance

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


class TestPersistenceRecord:
    def test_holds_the_required_run(self) -> None:
        persistence = Persistence(3)
        assert persistence.required == 3

    def test_one_observation_is_valid(self) -> None:
        Persistence(1)

    def test_rejects_zero_and_below(self) -> None:
        with pytest.raises(PersistenceError, match="at least 1"):
            Persistence(0)
        with pytest.raises(PersistenceError, match="at least 1"):
            Persistence(-1)

    def test_rejects_non_integers(self) -> None:
        with pytest.raises(PersistenceError, match="integer"):
            Persistence("three")  # type: ignore[arg-type]
        with pytest.raises(PersistenceError, match="integer"):
            Persistence(2.0)  # type: ignore[arg-type]
        with pytest.raises(PersistenceError, match="integer"):
            Persistence(True)  # type: ignore[arg-type]


class TestPersistenceReading:
    def test_confirms_at_and_beyond_the_required_run(self) -> None:
        persistence = Persistence(3)
        assert not PersistenceReading(active=True, consecutive=2).confirms(persistence)
        assert PersistenceReading(active=True, consecutive=3).confirms(persistence)
        assert PersistenceReading(active=True, consecutive=4).confirms(persistence)

    def test_an_inactive_reading_never_confirms(self) -> None:
        assert not PersistenceReading(active=False, consecutive=0).confirms(
            Persistence(1)
        )

    def test_rejects_bad_fields(self) -> None:
        with pytest.raises(PersistenceError, match="active must be"):
            PersistenceReading(active="yes", consecutive=1)  # type: ignore[arg-type]
        with pytest.raises(PersistenceError, match="consecutive must be"):
            PersistenceReading(active=True, consecutive="many")  # type: ignore[arg-type]
        with pytest.raises(PersistenceError, match="non-negative"):
            PersistenceReading(active=True, consecutive=-1)

    def test_inactive_cannot_claim_a_run(self) -> None:
        with pytest.raises(PersistenceError, match="inactive condition"):
            PersistenceReading(active=False, consecutive=2)

    def test_confirms_rejects_bad_persistence(self) -> None:
        reading = PersistenceReading(active=True, consecutive=1)
        with pytest.raises(PersistenceError, match="persistence must be"):
            reading.confirms(3)  # type: ignore[arg-type]


class TestAssessPersistence:
    @pytest.fixture
    def hours(self) -> Threshold:
        # Enter at 2h behind, clear at 1h: hysteresis between.
        return Threshold(Measure.SHORTFALL, 2 * HOUR, 1 * HOUR)

    def test_empty_run_is_inactive(self, hours) -> None:
        reading = assess_persistence(hours, ())
        assert reading.active is False
        assert reading.consecutive == 0

    def test_single_exceedance_holds_once(self, hours) -> None:
        reading = assess_persistence(hours, (3 * HOUR,))
        assert reading.active is True
        assert reading.consecutive == 1

    def test_consecutive_exceedances_accumulate(self, hours) -> None:
        reading = assess_persistence(hours, (3 * HOUR, 4 * HOUR, 5 * HOUR))
        assert reading.consecutive == 3

    def test_clearing_resets_the_run(self, hours) -> None:
        reading = assess_persistence(hours, (3 * HOUR, 4 * HOUR, 30 * HOUR / 60))
        assert reading.active is False
        assert reading.consecutive == 0

    def test_the_gap_holds_the_run(self, hours) -> None:
        """A dip that does not reach the exit bound has not stopped
        being a condition — the run counts on."""
        reading = assess_persistence(hours, (3 * HOUR, 4 * HOUR, 90 * HOUR / 60))
        assert reading.active is True
        assert reading.consecutive == 3

    def test_a_gap_before_entering_is_not_a_run(self, hours) -> None:
        """While inactive, a sub-threshold observation is just quiet:
        nothing enters, nothing is held."""
        reading = assess_persistence(hours, (90 * HOUR / 60, 3 * HOUR))
        assert reading.active is True
        assert reading.consecutive == 1

    def test_enter_wins_on_equal_bounds(self) -> None:
        plain = Threshold(Measure.SHORTFALL, 2 * HOUR)
        reading = assess_persistence(plain, (2 * HOUR, 2 * HOUR))
        assert reading.active is True
        assert reading.consecutive == 2

    def test_recovery_then_relapse_starts_a_new_run(self, hours) -> None:
        reading = assess_persistence(
            hours, (3 * HOUR, 30 * HOUR / 60, 4 * HOUR)
        )
        assert reading.active is True
        assert reading.consecutive == 1

    def test_rate_magnitudes_work_the_same(self) -> None:
        ceiling = Threshold(Measure.UTILIZATION, 0.8, 0.6)
        reading = assess_persistence(ceiling, (0.9, 0.75, 0.95))
        assert reading.active is True
        assert reading.consecutive == 3

    def test_rejects_bad_arguments(self, hours) -> None:
        with pytest.raises(PersistenceError, match="threshold must be"):
            assess_persistence("2h", ())  # type: ignore[arg-type]
        with pytest.raises(PersistenceError, match="magnitudes must be a tuple"):
            assess_persistence(hours, [3 * HOUR])  # type: ignore[arg-type]
        with pytest.raises(PersistenceError, match="magnitude must be"):
            assess_persistence(hours, (3,))
        with pytest.raises(PersistenceError, match="magnitude must be"):
            assess_persistence(hours, (-HOUR,))


class TestWiring:
    def test_three_weeks_behind_confirms_and_raises_the_trigger(self, plan) -> None:
        """The full stability chain: weekly snapshots → variance →
        slip magnitudes → the state machine — and when the run
        confirms, the trigger (TASK-079) is raised with the streak."""
        from backcasting.domain.trigger import TriggerKind, raise_trigger

        task = _task(plan, 8)
        # One hour a week on an 8h task: snapshots are cumulative, so
        # the slip (7h, 6h, 5h) stays over the enter bound every week.
        weekly = (
            (_sitting(task, MONDAY, 9, 10),),
            (_sitting(task, MONDAY + WEEK, 9, 10),),
            (_sitting(task, MONDAY + 2 * WEEK, 9, 10),),
        )
        cumulative = tuple(
            tuple(sitting for week in weekly[: i + 1] for sitting in week)
            for i in range(len(weekly))
        )
        hours = Threshold(Measure.SHORTFALL, 2 * HOUR, 1 * HOUR)
        patience = Persistence(3)

        magnitudes = tuple(
            variance_shortfall(
                progress_variance(
                    take_progress_snapshot(
                        plan, (task,), sittings, at=MONDAY + (week + 1) * WEEK
                    )
                )
            )
            for week, sittings in enumerate(cumulative)
        )
        reading = assess_persistence(hours, magnitudes)

        assert magnitudes == (7 * HOUR, 6 * HOUR, 5 * HOUR)
        assert reading.confirms(patience)
        trigger = raise_trigger(
            TriggerKind.PROGRESS,
            f"{reading.consecutive} consecutive weeks behind plan by "
            f"at least {hours.enter_bound}.",
            observed_at=MONDAY + 3 * WEEK,
        )
        assert trigger.kind is TriggerKind.PROGRESS
        assert "3 consecutive weeks" in trigger.detail

    def test_one_bad_week_is_noise_not_a_trigger(self, plan) -> None:
        """The stability the control buys: a single over-threshold
        week — followed by a clear one — never confirms."""
        task = _task(plan, 8)
        weekly = (
            (_sitting(task, MONDAY, 9, 15),),   # 6h of 8h: 2h behind
            (_sitting(task, MONDAY + WEEK, 9, 11),),  # catches up: slip clears
        )
        cumulative = tuple(
            tuple(sitting for week in weekly[: i + 1] for sitting in week)
            for i in range(len(weekly))
        )
        hours = Threshold(Measure.SHORTFALL, 2 * HOUR, 1 * HOUR)

        magnitudes = tuple(
            variance_shortfall(
                progress_variance(
                    take_progress_snapshot(
                        plan, (task,), sittings, at=MONDAY + (week + 1) * WEEK
                    )
                )
            )
            for week, sittings in enumerate(cumulative)
        )
        reading = assess_persistence(hours, magnitudes)

        assert magnitudes == (2 * HOUR, timedelta(0))
        assert reading.active is False
        assert reading.consecutive == 0
        assert not reading.confirms(Persistence(2))
