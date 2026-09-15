"""Tests for the Gap domain model (TASK-020).

Covers the gap shape: references to the goal, current state, and future
state it was computed from; validated metric dimensions with unique names;
optional bounded narrative; UTC calculation time; and the record factory.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backcasting.domain.gap import (
    MAX_NARRATIVE_LENGTH,
    Gap,
    GapDimension,
    GapError,
    record_gap,
)
from backcasting.domain.metric import Metric, MetricDirection, MetricKind

CALCULATED = datetime(2026, 1, 5, tzinfo=timezone.utc)


def make_metric(name: str = "Distance") -> Metric:
    return Metric(name, MetricKind.COUNT, MetricDirection.MAXIMIZE)


def make_dimension(
    name: str = "Distance", current: object = 5, target: object = 42
) -> GapDimension:
    return GapDimension(make_metric(name), current, target)


class TestGapDimension:
    def test_valid_dimension_round_trips(self) -> None:
        dimension = GapDimension(make_metric(), 5, 42)
        assert dimension.current_value == 5
        assert dimension.target_value == 42

    def test_values_are_validated_against_the_metric(self) -> None:
        with pytest.raises(GapError):
            GapDimension(make_metric(), -1, 42)
        with pytest.raises(GapError):
            GapDimension(make_metric(), 5, "42")

    def test_non_metric_is_rejected(self) -> None:
        with pytest.raises(GapError):
            GapDimension("distance", 5, 42)  # type: ignore[arg-type]

    def test_boolean_metric_dimension(self) -> None:
        metric = Metric(
            "Registered", MetricKind.BOOLEAN, MetricDirection.TARGET, target_value=True
        )
        dimension = GapDimension(metric, False, True)
        assert dimension.current_value is False
        assert dimension.target_value is True


class TestGap:
    def _valid_kwargs(self) -> dict:
        return {
            "gap_id": uuid.uuid4(),
            "goal_id": uuid.uuid4(),
            "current_state_id": uuid.uuid4(),
            "future_state_id": uuid.uuid4(),
            "calculated_at": CALCULATED,
            "dimensions": (make_dimension(),),
            "narrative": "Long way to the marathon distance.",
        }

    def test_valid_gap_round_trips(self) -> None:
        kwargs = self._valid_kwargs()
        gap = Gap(**kwargs)
        assert gap.gap_id == kwargs["gap_id"]
        assert gap.goal_id == kwargs["goal_id"]
        assert gap.current_state_id == kwargs["current_state_id"]
        assert gap.future_state_id == kwargs["future_state_id"]
        assert gap.calculated_at == CALCULATED
        assert len(gap.dimensions) == 1
        assert gap.narrative == "Long way to the marathon distance."

    def test_gap_without_dimensions_or_narrative_is_valid(self) -> None:
        kwargs = self._valid_kwargs()
        gap = Gap(
            gap_id=kwargs["gap_id"],
            goal_id=kwargs["goal_id"],
            current_state_id=kwargs["current_state_id"],
            future_state_id=kwargs["future_state_id"],
            calculated_at=CALCULATED,
        )
        assert gap.dimensions == ()
        assert gap.narrative == ""

    def test_gap_is_immutable(self) -> None:
        gap = Gap(**self._valid_kwargs())
        with pytest.raises(AttributeError):
            gap.narrative = "different"  # type: ignore[misc]

    @pytest.mark.parametrize(
        "key,bad_value",
        [
            ("gap_id", "not-a-uuid"),
            ("goal_id", None),
            ("current_state_id", 1),
            ("future_state_id", "not-a-uuid"),
        ],
    )
    def test_non_uuid_references_are_rejected(self, key: str, bad_value: object) -> None:
        with pytest.raises(GapError):
            Gap(**{**self._valid_kwargs(), key: bad_value})

    def test_non_tuple_dimensions_are_rejected(self) -> None:
        with pytest.raises(GapError):
            Gap(**{**self._valid_kwargs(), "dimensions": [make_dimension()]})

    def test_non_dimension_members_are_rejected(self) -> None:
        with pytest.raises(GapError):
            Gap(**{**self._valid_kwargs(), "dimensions": ("not a dimension",)})

    def test_duplicate_metric_names_are_rejected(self) -> None:
        with pytest.raises(GapError):
            Gap(
                **{
                    **self._valid_kwargs(),
                    "dimensions": (make_dimension("Distance"), make_dimension("Distance")),
                }
            )

    def test_distinct_metric_names_are_accepted(self) -> None:
        gap = Gap(
            **{
                **self._valid_kwargs(),
                "dimensions": (
                    make_dimension("Distance"),
                    make_dimension("Weekly runs"),
                ),
            }
        )
        assert len(gap.dimensions) == 2

    def test_narrative_is_stripped_and_bounded(self) -> None:
        gap = Gap(**{**self._valid_kwargs(), "narrative": "  far  "})
        assert gap.narrative == "far"
        with pytest.raises(GapError):
            Gap(**{**self._valid_kwargs(), "narrative": "x" * (MAX_NARRATIVE_LENGTH + 1)})

    def test_naive_calculated_at_is_rejected(self) -> None:
        with pytest.raises(GapError):
            Gap(**{**self._valid_kwargs(), "calculated_at": datetime(2026, 1, 5)})

    def test_non_utc_calculated_at_is_rejected(self) -> None:
        # Europe/Berlin is UTC+1 on 2026-01-05.
        local = datetime(2026, 1, 5, 12, tzinfo=ZoneInfo("Europe/Berlin"))
        with pytest.raises(GapError):
            Gap(**{**self._valid_kwargs(), "calculated_at": local})


class TestRecordGap:
    def test_generates_identity_and_timestamp(self) -> None:
        before = datetime.now(timezone.utc)
        gap = record_gap(uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
        after = datetime.now(timezone.utc)
        assert isinstance(gap.gap_id, uuid.UUID)
        assert before <= gap.calculated_at <= after

    def test_injected_id_and_timestamp_are_honoured(self) -> None:
        gap_id = uuid.uuid4()
        dimension = make_dimension()
        gap = record_gap(
            uuid.uuid4(),
            uuid.uuid4(),
            uuid.uuid4(),
            dimensions=(dimension,),
            narrative="far",
            gap_id=gap_id,
            calculated_at=CALCULATED,
        )
        assert gap.gap_id == gap_id
        assert gap.calculated_at == CALCULATED
        assert gap.dimensions == (dimension,)
        assert gap.narrative == "far"

    def test_future_timestamp_is_accepted(self) -> None:
        gap = record_gap(
            uuid.uuid4(),
            uuid.uuid4(),
            uuid.uuid4(),
            calculated_at=CALCULATED + timedelta(days=1),
        )
        assert gap.calculated_at == CALCULATED + timedelta(days=1)
