"""Tests for the metric abstraction (TASK-015).

Covers the five measurement kinds and their value validation, metric
definitions (target direction requires a value, score requires a scale),
and direction-aware variance interpretation (docs/07-PROGRESS-FEEDBACK.md).
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from backcasting.domain.metric import (
    Metric,
    MetricDirection,
    MetricError,
    MetricKind,
    interpret_variance,
    validate_metric_value,
)


class TestEnums:
    def test_kinds_match_spec(self) -> None:
        assert [k.value for k in MetricKind] == [
            "count",
            "duration",
            "percentage",
            "boolean",
            "score",
        ]

    def test_directions_match_spec(self) -> None:
        assert [d.value for d in MetricDirection] == [
            "maximize",
            "minimize",
            "target",
        ]

    def test_enums_are_string_serializable(self) -> None:
        assert MetricKind("percentage") is MetricKind.PERCENTAGE
        assert MetricDirection("maximize") is MetricDirection.MAXIMIZE


class TestValidateMetricValue:
    def test_count_accepts_non_negative_integers(self) -> None:
        assert validate_metric_value(MetricKind.COUNT, 0) == 0
        assert validate_metric_value(MetricKind.COUNT, 42) == 42

    @pytest.mark.parametrize("bad", [-1, 1.5, True, "3", None])
    def test_count_rejects_invalid_values(self, bad: object) -> None:
        with pytest.raises(MetricError):
            validate_metric_value(MetricKind.COUNT, bad)

    def test_duration_accepts_non_negative_timedeltas(self) -> None:
        assert validate_metric_value(MetricKind.DURATION, timedelta(0)) == timedelta(0)
        assert (
            validate_metric_value(MetricKind.DURATION, timedelta(hours=2))
            == timedelta(hours=2)
        )

    @pytest.mark.parametrize("bad", [timedelta(seconds=-1), 30, "1h", None])
    def test_duration_rejects_invalid_values(self, bad: object) -> None:
        with pytest.raises(MetricError):
            validate_metric_value(MetricKind.DURATION, bad)

    def test_percentage_accepts_bounds_inclusive(self) -> None:
        assert validate_metric_value(MetricKind.PERCENTAGE, 0) == 0
        assert validate_metric_value(MetricKind.PERCENTAGE, 100) == 100
        assert validate_metric_value(MetricKind.PERCENTAGE, 55.5) == 55.5

    @pytest.mark.parametrize("bad", [-0.1, 100.1, True, "50", None, float("nan")])
    def test_percentage_rejects_invalid_values(self, bad: object) -> None:
        with pytest.raises(MetricError):
            validate_metric_value(MetricKind.PERCENTAGE, bad)

    def test_boolean_accepts_bools_only(self) -> None:
        assert validate_metric_value(MetricKind.BOOLEAN, True) is True
        assert validate_metric_value(MetricKind.BOOLEAN, False) is False

    @pytest.mark.parametrize("bad", [1, 0, "yes", None])
    def test_boolean_rejects_non_bools(self, bad: object) -> None:
        with pytest.raises(MetricError):
            validate_metric_value(MetricKind.BOOLEAN, bad)

    def test_score_requires_explicit_scale(self) -> None:
        with pytest.raises(MetricError):
            validate_metric_value(MetricKind.SCORE, 5)
        assert validate_metric_value(MetricKind.SCORE, 5, score_min=0, score_max=10) == 5

    def test_score_bounds_are_inclusive(self) -> None:
        assert validate_metric_value(MetricKind.SCORE, 0, score_min=0, score_max=10) == 0
        assert (
            validate_metric_value(MetricKind.SCORE, 10, score_min=0, score_max=10) == 10
        )

    @pytest.mark.parametrize("bad", [-1, 11, True, "7", None, float("inf")])
    def test_score_rejects_out_of_scale_values(self, bad: object) -> None:
        with pytest.raises(MetricError):
            validate_metric_value(MetricKind.SCORE, bad, score_min=0, score_max=10)

    def test_score_scale_must_be_ordered(self) -> None:
        with pytest.raises(MetricError):
            validate_metric_value(MetricKind.SCORE, 5, score_min=10, score_max=0)
        with pytest.raises(MetricError):
            validate_metric_value(MetricKind.SCORE, 5, score_min=5, score_max=5)

    def test_non_enum_kind_is_rejected(self) -> None:
        with pytest.raises(MetricError):
            validate_metric_value("count", 1)  # type: ignore[arg-type]


class TestMetric:
    def test_simple_metric_definition(self) -> None:
        metric = Metric("Training runs", MetricKind.COUNT, MetricDirection.MAXIMIZE)
        assert metric.name == "Training runs"
        assert metric.validate(3) == 3

    def test_name_is_stripped_and_bounded(self) -> None:
        assert Metric("  Runs  ", MetricKind.COUNT, MetricDirection.MAXIMIZE).name == "Runs"
        with pytest.raises(MetricError):
            Metric("x" * 201, MetricKind.COUNT, MetricDirection.MAXIMIZE)
        with pytest.raises(MetricError):
            Metric("  ", MetricKind.COUNT, MetricDirection.MAXIMIZE)

    def test_metric_is_immutable(self) -> None:
        metric = Metric("Runs", MetricKind.COUNT, MetricDirection.MAXIMIZE)
        with pytest.raises(AttributeError):
            metric.name = "other"  # type: ignore[misc]

    def test_target_direction_requires_target_value(self) -> None:
        with pytest.raises(MetricError):
            Metric("Weight", MetricKind.COUNT, MetricDirection.TARGET)
        metric = Metric(
            "Weight", MetricKind.COUNT, MetricDirection.TARGET, target_value=70
        )
        assert metric.target_value == 70

    def test_target_value_is_validated_against_kind(self) -> None:
        with pytest.raises(MetricError):
            Metric(
                "Sessions", MetricKind.COUNT, MetricDirection.TARGET, target_value=-1
            )

    def test_false_is_a_valid_boolean_target(self) -> None:
        metric = Metric(
            "Injured", MetricKind.BOOLEAN, MetricDirection.TARGET, target_value=False
        )
        assert metric.target_value is False

    def test_non_target_direction_rejects_target_value(self) -> None:
        with pytest.raises(MetricError):
            Metric(
                "Runs", MetricKind.COUNT, MetricDirection.MAXIMIZE, target_value=5
            )

    def test_score_metric_requires_scale(self) -> None:
        with pytest.raises(MetricError):
            Metric("Satisfaction", MetricKind.SCORE, MetricDirection.MAXIMIZE)
        metric = Metric(
            "Satisfaction", MetricKind.SCORE, MetricDirection.MAXIMIZE,
            score_min=0, score_max=10,
        )
        assert metric.validate(7.5) == 7.5
        with pytest.raises(MetricError):
            metric.validate(12)

    def test_non_score_metric_rejects_scale(self) -> None:
        with pytest.raises(MetricError):
            Metric(
                "Runs", MetricKind.COUNT, MetricDirection.MAXIMIZE,
                score_min=0, score_max=10,
            )

    def test_bad_kind_or_direction_are_rejected(self) -> None:
        with pytest.raises(MetricError):
            Metric("Runs", "count", MetricDirection.MAXIMIZE)  # type: ignore[arg-type]
        with pytest.raises(MetricError):
            Metric("Runs", MetricKind.COUNT, "maximize")  # type: ignore[arg-type]


class TestInterpretVariance:
    def test_maximize_direction(self) -> None:
        metric = Metric("Runs", MetricKind.COUNT, MetricDirection.MAXIMIZE)
        good = interpret_variance(metric, 3, 5)
        assert good.delta == 2
        assert good.favorable is True
        bad = interpret_variance(metric, 5, 3)
        assert bad.delta == -2
        assert bad.favorable is False
        even = interpret_variance(metric, 4, 4)
        assert even.favorable is True

    def test_minimize_direction(self) -> None:
        metric = Metric("Cigarettes", MetricKind.COUNT, MetricDirection.MINIMIZE)
        good = interpret_variance(metric, 10, 6)
        assert good.delta == -4
        assert good.favorable is True
        bad = interpret_variance(metric, 6, 10)
        assert bad.favorable is False

    def test_target_direction(self) -> None:
        metric = Metric(
            "Weight", MetricKind.COUNT, MetricDirection.TARGET, target_value=70
        )
        hit = interpret_variance(metric, 70, 70)
        assert hit.delta == 0
        assert hit.favorable is True
        miss = interpret_variance(metric, 70, 72)
        assert miss.delta == 2
        assert miss.favorable is False

    def test_duration_variance_uses_seconds(self) -> None:
        metric = Metric(
            "Session length", MetricKind.DURATION, MetricDirection.TARGET,
            target_value=timedelta(hours=1),
        )
        result = interpret_variance(
            metric, timedelta(hours=1), timedelta(hours=1, minutes=30)
        )
        assert result.delta == 30 * 60
        assert result.favorable is False

    def test_boolean_variance(self) -> None:
        metric = Metric(
            "Completed", MetricKind.BOOLEAN, MetricDirection.TARGET, target_value=True
        )
        hit = interpret_variance(metric, True, True)
        assert hit.delta == 0
        assert hit.favorable is True
        miss = interpret_variance(metric, True, False)
        assert miss.delta == -1
        assert miss.favorable is False

    def test_percentage_variance(self) -> None:
        metric = Metric("Adherence", MetricKind.PERCENTAGE, MetricDirection.MAXIMIZE)
        result = interpret_variance(metric, 80, 92.5)
        assert result.delta == pytest.approx(12.5)
        assert result.favorable is True

    def test_values_are_validated_before_interpretation(self) -> None:
        metric = Metric("Runs", MetricKind.COUNT, MetricDirection.MAXIMIZE)
        with pytest.raises(MetricError):
            interpret_variance(metric, 3, -1)
        with pytest.raises(MetricError):
            interpret_variance(metric, 2.5, 4)

    def test_non_metric_is_rejected(self) -> None:
        with pytest.raises(MetricError):
            interpret_variance("runs", 1, 2)  # type: ignore[arg-type]
