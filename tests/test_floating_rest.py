"""Tests for floating rest (TASK-033).

Pins "floating rest supports quotas without fixed weekdays" (docs/05):
a positive weekly quota bound to a calendar, and satisfaction measured
from arbitrary rest intervals with overlaps merged, never
double-counted.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backcasting.domain.calendar import Calendar, create_calendar
from backcasting.domain.floating_rest import (
    FloatingRest,
    FloatingRestError,
    RestBalance,
    create_floating_rest,
    evaluate_rest,
)

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
UTC = timezone.utc
LONDON = ZoneInfo("Europe/London")
HOUR = timedelta(hours=1)


@pytest.fixture
def calendar() -> Calendar:
    return create_calendar(uuid.uuid4(), timezone=LONDON, created_at=CREATED)


def _interval(day: int, start_hour: int, end_hour: int) -> tuple:
    return (
        datetime(2026, 1, day, start_hour, tzinfo=UTC),
        datetime(2026, 1, day, end_hour, tzinfo=UTC),
    )


class TestFloatingRest:
    def _valid_kwargs(self) -> dict:
        return {
            "rest_id": uuid.uuid4(),
            "calendar_id": uuid.uuid4(),
            "title": "Rest evenings",
            "weekly_quota": 10 * HOUR,
            "created_at": CREATED,
            "updated_at": CREATED,
        }

    def test_valid_quota_is_accepted(self) -> None:
        rest = FloatingRest(**self._valid_kwargs())
        assert rest.title == "Rest evenings"
        assert rest.weekly_quota == 10 * HOUR

    def test_title_is_stripped_and_bounded(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["title"] = "  Rest  "
        assert FloatingRest(**kwargs).title == "Rest"
        kwargs["title"] = "x" * 201
        with pytest.raises(FloatingRestError):
            FloatingRest(**kwargs)

    @pytest.mark.parametrize("title", ["", "   "])
    def test_empty_title_is_rejected(self, title: str) -> None:
        kwargs = self._valid_kwargs()
        kwargs["title"] = title
        with pytest.raises(FloatingRestError):
            FloatingRest(**kwargs)

    @pytest.mark.parametrize("quota", [timedelta(0), -HOUR, 8, "8h"])
    def test_invalid_quotas_are_rejected(self, quota: object) -> None:
        kwargs = self._valid_kwargs()
        kwargs["weekly_quota"] = quota
        with pytest.raises(FloatingRestError):
            FloatingRest(**kwargs)

    @pytest.mark.parametrize("field_name", ["rest_id", "calendar_id"])
    def test_ids_must_be_uuids(self, field_name: str) -> None:
        kwargs = self._valid_kwargs()
        kwargs[field_name] = "not-a-uuid"
        with pytest.raises(FloatingRestError):
            FloatingRest(**kwargs)

    @pytest.mark.parametrize("stamp_name", ["created_at", "updated_at"])
    def test_stamps_must_be_utc_and_aware(self, stamp_name: str) -> None:
        kwargs = self._valid_kwargs()
        kwargs[stamp_name] = datetime(2026, 1, 1)
        with pytest.raises(FloatingRestError):
            FloatingRest(**kwargs)
        kwargs[stamp_name] = CREATED.astimezone(ZoneInfo("Asia/Tehran"))
        with pytest.raises(FloatingRestError):
            FloatingRest(**kwargs)

    def test_updated_at_must_not_precede_created_at(self) -> None:
        kwargs = self._valid_kwargs()
        kwargs["updated_at"] = CREATED - timedelta(seconds=1)
        with pytest.raises(FloatingRestError):
            FloatingRest(**kwargs)

    def test_quota_is_immutable(self) -> None:
        rest = FloatingRest(**self._valid_kwargs())
        with pytest.raises(AttributeError):
            rest.weekly_quota = 5 * HOUR  # type: ignore[misc]


class TestCreateFloatingRest:
    def test_creates_quota_bound_to_calendar(self, calendar: Calendar) -> None:
        rest = create_floating_rest(
            calendar, "Rest evenings", 10 * HOUR, created_at=CREATED
        )
        assert isinstance(rest.rest_id, uuid.UUID)
        assert rest.calendar_id == calendar.calendar_id
        assert rest.created_at == CREATED
        assert rest.updated_at == CREATED

    def test_injectable_id_and_clock(self, calendar: Calendar) -> None:
        rest_id = uuid.uuid4()
        rest = create_floating_rest(
            calendar,
            "Rest evenings",
            10 * HOUR,
            rest_id=rest_id,
            created_at=CREATED,
        )
        assert rest.rest_id == rest_id

    def test_rejects_non_calendar(self) -> None:
        with pytest.raises(TypeError):
            create_floating_rest("no", "Rest", HOUR, created_at=CREATED)  # type: ignore[arg-type]


class TestEvaluateRest:
    @pytest.fixture
    def rest(self, calendar: Calendar) -> FloatingRest:
        return create_floating_rest(
            calendar, "Rest evenings", 4 * HOUR, created_at=CREATED
        )

    def test_no_rest_is_unsatisfied(self, rest: FloatingRest) -> None:
        balance = evaluate_rest(rest, ())
        assert isinstance(balance, RestBalance)
        assert balance.consumed == timedelta(0)
        assert balance.remaining == 4 * HOUR
        assert balance.satisfied is False

    def test_disjoint_intervals_sum(self, rest: FloatingRest) -> None:
        balance = evaluate_rest(
            rest,
            (_interval(5, 19, 21), _interval(6, 9, 11)),  # 2h + 2h
        )
        assert balance.consumed == 4 * HOUR
        assert balance.remaining == timedelta(0)
        assert balance.satisfied is True

    def test_unsorted_intervals_are_handled(self, rest: FloatingRest) -> None:
        balance = evaluate_rest(
            rest,
            (_interval(6, 9, 11), _interval(5, 19, 21)),
        )
        assert balance.consumed == 4 * HOUR

    def test_overlapping_intervals_are_merged_not_summed(
        self, rest: FloatingRest
    ) -> None:
        balance = evaluate_rest(
            rest,
            (
                _interval(5, 19, 22),  # 3h
                _interval(5, 20, 23),  # overlaps 1h, adds 1h
            ),
        )
        assert balance.consumed == 4 * HOUR
        assert balance.satisfied is True

    def test_contained_interval_adds_nothing(self, rest: FloatingRest) -> None:
        balance = evaluate_rest(
            rest,
            (_interval(5, 19, 23), _interval(5, 20, 21)),
        )
        assert balance.consumed == 4 * HOUR

    def test_touching_intervals_merge(self, rest: FloatingRest) -> None:
        balance = evaluate_rest(
            rest,
            (_interval(5, 19, 21), _interval(5, 21, 23)),
        )
        assert balance.consumed == 4 * HOUR
        assert balance.satisfied is True

    def test_consuming_more_than_quota_is_satisfied(
        self, rest: FloatingRest
    ) -> None:
        balance = evaluate_rest(rest, (_interval(5, 18, 23),))  # 5h
        assert balance.consumed == 5 * HOUR
        assert balance.remaining == -HOUR
        assert balance.satisfied is True

    def test_partial_rest_reports_shortfall(self, rest: FloatingRest) -> None:
        balance = evaluate_rest(rest, (_interval(5, 19, 21),))  # 2h of 4h
        assert balance.remaining == 2 * HOUR
        assert balance.satisfied is False

    def test_rejects_non_tuple_intervals(self, rest: FloatingRest) -> None:
        with pytest.raises(FloatingRestError):
            evaluate_rest(
                rest, [_interval(5, 19, 21)]  # type: ignore[arg-type]
            )

    def test_rejects_malformed_intervals(self, rest: FloatingRest) -> None:
        with pytest.raises(FloatingRestError):
            evaluate_rest(rest, (_interval(5, 19, 21), (CREATED,)))  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "interval",
        [
            (datetime(2026, 1, 5, 19), datetime(2026, 1, 5, 21, tzinfo=UTC)),
            (
                datetime(2026, 1, 5, 19, tzinfo=UTC),
                datetime(2026, 1, 5, 19, tzinfo=ZoneInfo("Asia/Tehran")),
            ),
            (
                datetime(2026, 1, 5, 21, tzinfo=UTC),
                datetime(2026, 1, 5, 19, tzinfo=UTC),
            ),
            (
                datetime(2026, 1, 5, 19, tzinfo=UTC),
                datetime(2026, 1, 5, 19, tzinfo=UTC),
            ),
        ],
    )
    def test_rejects_invalid_intervals(
        self, rest: FloatingRest, interval: tuple
    ) -> None:
        with pytest.raises(FloatingRestError):
            evaluate_rest(rest, (interval,))

    def test_rejects_non_rest(self) -> None:
        with pytest.raises(TypeError):
            evaluate_rest("not a rest", ())  # type: ignore[arg-type]
