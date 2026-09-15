"""Tests for the feasibility engine (TASK-025).

Pins the spec rule "Required Workload + Buffer ≤ usable Capacity"
(docs/04): boundary equality is feasible, slack exposes the distance to
the boundary, and inputs must be non-negative timedeltas.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from backcasting.domain.feasibility import (
    FeasibilityError,
    FeasibilityResult,
    evaluate_feasibility,
)

HOUR = timedelta(hours=1)


class TestEvaluateFeasibility:
    def test_workload_and_buffer_within_capacity_is_feasible(self) -> None:
        result = evaluate_feasibility(30 * HOUR, 5 * HOUR, 50 * HOUR)
        assert result.feasible is True
        assert result.total_required == 35 * HOUR
        assert result.slack == 15 * HOUR

    def test_boundary_equality_is_feasible(self) -> None:
        result = evaluate_feasibility(30 * HOUR, 5 * HOUR, 35 * HOUR)
        assert result.feasible is True
        assert result.slack == timedelta(0)

    def test_overload_is_infeasible_with_negative_slack(self) -> None:
        result = evaluate_feasibility(30 * HOUR, 6 * HOUR, 35 * HOUR)
        assert result.feasible is False
        assert result.slack == -HOUR

    def test_zero_workload_with_capacity_is_feasible(self) -> None:
        result = evaluate_feasibility(timedelta(0), timedelta(0), timedelta(0))
        assert result.feasible is True
        assert result.slack == timedelta(0)

    def test_buffer_can_make_a_plan_infeasible(self) -> None:
        without_buffer = evaluate_feasibility(30 * HOUR, timedelta(0), 32 * HOUR)
        with_buffer = evaluate_feasibility(30 * HOUR, 3 * HOUR, 32 * HOUR)
        assert without_buffer.feasible is True
        assert with_buffer.feasible is False

    def test_result_exposes_inputs(self) -> None:
        result = evaluate_feasibility(10 * HOUR, 2 * HOUR, 20 * HOUR)
        assert result.required_workload == 10 * HOUR
        assert result.buffer == 2 * HOUR
        assert result.usable_capacity == 20 * HOUR

    def test_result_is_immutable(self) -> None:
        result = evaluate_feasibility(10 * HOUR, 2 * HOUR, 20 * HOUR)
        with pytest.raises(AttributeError):
            result.feasible = False  # type: ignore[misc]

    @pytest.mark.parametrize(
        "workload,buffer,capacity",
        [
            (-HOUR, 0, 10 * HOUR),
            (0, -HOUR, 10 * HOUR),
            (0, 0, -HOUR),
        ],
    )
    def test_negative_inputs_are_rejected(
        self, workload: timedelta, buffer: timedelta, capacity: timedelta
    ) -> None:
        with pytest.raises(FeasibilityError):
            evaluate_feasibility(workload, buffer, capacity)

    @pytest.mark.parametrize(
        "workload,buffer,capacity",
        [
            (5, 0, 10 * HOUR),
            (0, "1h", 10 * HOUR),
            (0, 0, 100),
            (None, 0, 0),
        ],
    )
    def test_non_timedelta_inputs_are_rejected(
        self, workload: object, buffer: object, capacity: object
    ) -> None:
        with pytest.raises(FeasibilityError):
            evaluate_feasibility(workload, buffer, capacity)  # type: ignore[arg-type]


def test_result_type_is_exported_and_constructible() -> None:
    # The result is a value object callers may persist; keep it importable
    # and constructible independently of the engine.
    result = FeasibilityResult(
        required_workload=timedelta(0),
        buffer=timedelta(0),
        usable_capacity=timedelta(0),
        feasible=True,
        total_required=timedelta(0),
        slack=timedelta(0),
    )
    assert result.feasible is True
