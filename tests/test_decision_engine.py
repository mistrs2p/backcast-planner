"""Tests for the replanning decision engine (TASK-084).

Proposal in, decision out: the reasoning layer names candidate
levels (ADR-002), the engine enforces the minimum-change principle
and the policy's gates, and names the control that decided.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backcasting.domain.decision_engine import (
    DecisionAction,
    DecisionEngineError,
    ReplanningDecision,
    decide_response,
)
from backcasting.domain.cooldown import Cooldown
from backcasting.domain.persistence import Persistence, PersistenceReading
from backcasting.domain.replanning_policy import (
    ReplanningLevel,
    ReplanningMode,
    ReplanningPolicy,
)

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
MONDAY = datetime(2026, 6, 1, tzinfo=timezone.utc)  # a Monday
HOUR = timedelta(hours=1)
WEEK = timedelta(days=7)

CONFIRMED = PersistenceReading(active=True, consecutive=3)
UNCONFIRMED = PersistenceReading(active=False, consecutive=0)
LOWER = (ReplanningLevel.RESCHEDULE, ReplanningLevel.REPLAN)


def _policy(mode: ReplanningMode) -> ReplanningPolicy:
    return ReplanningPolicy(mode, Cooldown(WEEK), Persistence(2))


class TestReplanningDecision:
    def test_shape(self) -> None:
        decision = ReplanningDecision(
            DecisionAction.ACT, ReplanningLevel.RESCHEDULE, "act-reschedule"
        )
        assert decision.action is DecisionAction.ACT
        assert decision.level is ReplanningLevel.RESCHEDULE
        assert decision.reason == "act-reschedule"

    def test_acting_and_suggesting_require_a_level(self) -> None:
        with pytest.raises(DecisionEngineError, match="require a level"):
            ReplanningDecision(DecisionAction.ACT, None, "act")
        with pytest.raises(DecisionEngineError, match="require a level"):
            ReplanningDecision(DecisionAction.SUGGEST, None, "suggest")

    def test_holding_may_go_without_a_level(self) -> None:
        ReplanningDecision(DecisionAction.HOLD, None, "not-persistent")

    def test_rejects_bad_fields(self) -> None:
        with pytest.raises(DecisionEngineError, match="action must be"):
            ReplanningDecision("act", ReplanningLevel.REPLAN, "act-replan")  # type: ignore[arg-type]
        with pytest.raises(DecisionEngineError, match="level must be"):
            ReplanningDecision(DecisionAction.ACT, "replan", "act-replan")  # type: ignore[arg-type]
        with pytest.raises(DecisionEngineError, match="reason must be"):
            ReplanningDecision(DecisionAction.HOLD, None, "   ")

    def test_is_immutable(self) -> None:
        from dataclasses import FrozenInstanceError

        decision = ReplanningDecision(DecisionAction.HOLD, None, "cooldown")
        with pytest.raises(FrozenInstanceError):
            decision.reason = "manual-mode"  # type: ignore[misc]


class TestDecideResponse:
    def test_unconfirmed_condition_holds(self) -> None:
        decision = decide_response(
            _policy(ReplanningMode.AUTOMATIC), UNCONFIRMED, LOWER, at=MONDAY
        )
        assert decision.action is DecisionAction.HOLD
        assert decision.level is None
        assert decision.reason == "not-persistent"

    def test_no_candidates_holds_even_when_confirmed(self) -> None:
        decision = decide_response(
            _policy(ReplanningMode.AUTOMATIC), CONFIRMED, (), at=MONDAY
        )
        assert decision.action is DecisionAction.HOLD
        assert decision.level is None
        assert decision.reason == "no-candidate"

    def test_automatic_acts_on_the_minimum_level(self) -> None:
        decision = decide_response(
            _policy(ReplanningMode.AUTOMATIC),
            CONFIRMED,
            (ReplanningLevel.REPLAN, ReplanningLevel.RESCHEDULE),
            at=MONDAY,
        )
        assert decision.action is DecisionAction.ACT
        assert decision.level is ReplanningLevel.RESCHEDULE
        assert decision.reason == "act-reschedule"

    def test_suggest_mode_proposes(self) -> None:
        decision = decide_response(
            _policy(ReplanningMode.SUGGEST), CONFIRMED, LOWER, at=MONDAY
        )
        assert decision.action is DecisionAction.SUGGEST
        assert decision.level is ReplanningLevel.RESCHEDULE
        assert decision.reason == "suggest-reschedule"

    def test_manual_mode_holds(self) -> None:
        decision = decide_response(
            _policy(ReplanningMode.MANUAL), CONFIRMED, LOWER, at=MONDAY
        )
        assert decision.action is DecisionAction.HOLD
        assert decision.reason == "manual-mode"

    def test_automatic_in_cooldown_holds_naming_the_clock(self) -> None:
        decision = decide_response(
            _policy(ReplanningMode.AUTOMATIC),
            CONFIRMED,
            LOWER,
            last_offered_at=MONDAY,
            at=MONDAY + HOUR,
        )
        assert decision.action is DecisionAction.HOLD
        assert decision.level is ReplanningLevel.RESCHEDULE
        assert decision.reason == "cooldown"

    def test_suggest_in_cooldown_holds_naming_the_clock(self) -> None:
        decision = decide_response(
            _policy(ReplanningMode.SUGGEST),
            CONFIRMED,
            LOWER,
            last_offered_at=MONDAY,
            at=MONDAY + HOUR,
        )
        assert decision.action is DecisionAction.HOLD
        assert decision.reason == "cooldown"

    def test_goal_revision_under_automatic_requires_the_user(self) -> None:
        decision = decide_response(
            _policy(ReplanningMode.AUTOMATIC),
            CONFIRMED,
            (ReplanningLevel.GOAL_REVISION,),
            at=MONDAY,
        )
        assert decision.action is DecisionAction.HOLD
        assert decision.level is ReplanningLevel.GOAL_REVISION
        assert decision.reason == "goal-revision-requires-user"

    def test_goal_revision_is_suggested_in_suggest_mode(self) -> None:
        decision = decide_response(
            _policy(ReplanningMode.SUGGEST),
            CONFIRMED,
            (ReplanningLevel.GOAL_REVISION,),
            at=MONDAY,
        )
        assert decision.action is DecisionAction.SUGGEST
        assert decision.level is ReplanningLevel.GOAL_REVISION

    def test_a_reading_below_the_policy_persistence_holds(self) -> None:
        """The engine demands the reading confirm against the policy's
        own persistence — a run of 2 against a policy demanding 3 is
        still noise to this policy."""
        decision = decide_response(
            _policy(ReplanningMode.AUTOMATIC),
            PersistenceReading(active=True, consecutive=1),
            LOWER,
            at=MONDAY,
        )
        assert decision.action is DecisionAction.HOLD
        assert decision.reason == "not-persistent"

    def test_rejects_bad_arguments(self) -> None:
        policy = _policy(ReplanningMode.AUTOMATIC)
        with pytest.raises(DecisionEngineError, match="policy must be"):
            decide_response("policy", CONFIRMED, LOWER, at=MONDAY)  # type: ignore[arg-type]
        with pytest.raises(DecisionEngineError, match="reading must be"):
            decide_response(policy, "confirmed", LOWER, at=MONDAY)  # type: ignore[arg-type]
        with pytest.raises(DecisionEngineError, match="levels must be a tuple"):
            decide_response(policy, CONFIRMED, list(LOWER), at=MONDAY)  # type: ignore[arg-type]
        with pytest.raises(DecisionEngineError, match="ReplanningLevel instances"):
            decide_response(policy, CONFIRMED, ("replan",), at=MONDAY)  # type: ignore[arg-type]
        with pytest.raises(DecisionEngineError, match="at must be"):
            decide_response(policy, CONFIRMED, LOWER, at=datetime(2026, 6, 1))
        with pytest.raises(DecisionEngineError, match="last_offered_at must be"):
            decide_response(
                policy,
                CONFIRMED,
                LOWER,
                last_offered_at=datetime(2026, 6, 1),  # type: ignore[arg-type]
                at=MONDAY,
            )


class TestWiring:
    def test_persistent_slip_to_decision(self) -> None:
        """The whole adaptation joint: sittings → snapshot → variance
        → slip magnitudes → persistence reading → the engine's
        decision — acting on the minimum level, outside cooldown."""
        from backcasting.domain.execution import create_execution
        from backcasting.domain.goal import create_goal
        from backcasting.domain.plan import create_plan
        from backcasting.domain.persistence import assess_persistence
        from backcasting.domain.progress import take_progress_snapshot
        from backcasting.domain.task import create_task, revise_task
        from backcasting.domain.threshold import Measure, Threshold, variance_shortfall
        from backcasting.domain.variance import progress_variance

        goal = create_goal(uuid.uuid4(), "Ship v2", created_at=CREATED)
        plan = create_plan(goal, 20 * HOUR, created_at=CREATED)
        task = create_task(plan, "Task", created_at=CREATED)
        task = revise_task(task, duration=8 * HOUR, updated_at=CREATED)
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
        reading = assess_persistence(hours, magnitudes)

        decision = decide_response(
            _policy(ReplanningMode.AUTOMATIC),
            reading,
            (ReplanningLevel.REPLAN, ReplanningLevel.RESCHEDULE),
            at=MONDAY + HOUR,
        )
        assert decision.action is DecisionAction.ACT
        assert decision.level is ReplanningLevel.RESCHEDULE
        assert decision.reason == "act-reschedule"

    def test_the_same_condition_after_an_action_waits(self) -> None:
        """The engine's decision one hour after the system already
        replanned: the condition still holds, the level is still
        minimal — and the clock says hold."""
        decision = decide_response(
            _policy(ReplanningMode.AUTOMATIC),
            CONFIRMED,
            LOWER,
            last_offered_at=MONDAY,
            at=MONDAY + HOUR,
        )
        later = decide_response(
            _policy(ReplanningMode.AUTOMATIC),
            CONFIRMED,
            LOWER,
            last_offered_at=MONDAY,
            at=MONDAY + WEEK,
        )
        assert (decision.action, decision.reason) == (
            DecisionAction.HOLD,
            "cooldown",
        )
        assert later.action is DecisionAction.ACT
