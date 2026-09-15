"""Tests for the Desired Future State domain model (TASK-014).

Covers destination invariants (identity, goal reference, bounded
description, UTC-aware target/creation timestamps, target after creation),
immutability, the define factory, and explicit revision semantics
(docs/08-REPLANNING-MODEL.md: replanning preserves the Future State).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backcasting.domain.future_state import (
    MAX_DESCRIPTION_LENGTH,
    FutureState,
    FutureStateError,
    define_future_state,
    revise_future_state,
)

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
TARGET = datetime(2026, 10, 11, tzinfo=timezone.utc)  # marathon race day


class TestFutureState:
    def _valid_kwargs(self) -> dict:
        return {
            "state_id": uuid.uuid4(),
            "goal_id": uuid.uuid4(),
            "description": "Complete the city marathon.",
            "target_date": TARGET,
            "created_at": CREATED,
            "updated_at": CREATED,
        }

    def test_valid_destination_round_trips(self) -> None:
        kwargs = self._valid_kwargs()
        state = FutureState(**kwargs)
        assert state.state_id == kwargs["state_id"]
        assert state.goal_id == kwargs["goal_id"]
        assert state.description == "Complete the city marathon."
        assert state.target_date == TARGET
        assert state.created_at == CREATED

    def test_description_is_stripped(self) -> None:
        state = FutureState(**{**self._valid_kwargs(), "description": "  finish  "})
        assert state.description == "finish"

    def test_destination_is_immutable(self) -> None:
        state = FutureState(**self._valid_kwargs())
        with pytest.raises(AttributeError):
            state.description = "somewhere else"  # type: ignore[misc]

    def test_non_uuid_ids_are_rejected(self) -> None:
        with pytest.raises(FutureStateError):
            FutureState(**{**self._valid_kwargs(), "state_id": "not-a-uuid"})
        with pytest.raises(FutureStateError):
            FutureState(**{**self._valid_kwargs(), "goal_id": 7})

    @pytest.mark.parametrize(
        "bad_description", ["", "   ", "x" * (MAX_DESCRIPTION_LENGTH + 1)]
    )
    def test_invalid_descriptions_are_rejected(self, bad_description: str) -> None:
        with pytest.raises(FutureStateError):
            FutureState(**{**self._valid_kwargs(), "description": bad_description})

    def test_naive_timestamps_are_rejected(self) -> None:
        with pytest.raises(FutureStateError):
            FutureState(**{**self._valid_kwargs(), "target_date": datetime(2026, 10, 11)})
        with pytest.raises(FutureStateError):
            FutureState(**{**self._valid_kwargs(), "created_at": datetime(2026, 1, 1)})
        with pytest.raises(FutureStateError):
            FutureState(**{**self._valid_kwargs(), "updated_at": datetime(2026, 1, 1)})

    def test_non_utc_timestamps_are_rejected(self) -> None:
        # Europe/Berlin is UTC+1 on 2026-01-01.
        local = datetime(2026, 1, 1, 12, tzinfo=ZoneInfo("Europe/Berlin"))
        with pytest.raises(FutureStateError):
            FutureState(**{**self._valid_kwargs(), "created_at": local})
        with pytest.raises(FutureStateError):
            FutureState(**{**self._valid_kwargs(), "updated_at": local})

    def test_target_not_after_creation_is_rejected(self) -> None:
        with pytest.raises(FutureStateError):
            FutureState(
                **{**self._valid_kwargs(), "target_date": CREATED}
            )
        with pytest.raises(FutureStateError):
            FutureState(
                **{
                    **self._valid_kwargs(),
                    "target_date": CREATED - timedelta(seconds=1),
                }
            )

    def test_updated_before_created_is_rejected(self) -> None:
        with pytest.raises(FutureStateError):
            FutureState(
                **{
                    **self._valid_kwargs(),
                    "updated_at": CREATED - timedelta(seconds=1),
                }
            )


class TestDefineFutureState:
    def test_generates_identity_and_timestamps(self) -> None:
        before = datetime.now(timezone.utc)
        state = define_future_state(
            uuid.uuid4(), "Finish the race.", before + timedelta(days=30)
        )
        after = datetime.now(timezone.utc)
        assert isinstance(state.state_id, uuid.UUID)
        assert before <= state.created_at <= after
        assert state.created_at == state.updated_at

    def test_injected_id_and_timestamp_are_honoured(self) -> None:
        state_id = uuid.uuid4()
        state = define_future_state(
            uuid.uuid4(),
            "Finish the race.",
            TARGET,
            state_id=state_id,
            created_at=CREATED,
        )
        assert state.state_id == state_id
        assert state.created_at == CREATED

    def test_target_in_the_past_is_rejected(self) -> None:
        with pytest.raises(FutureStateError):
            define_future_state(
                uuid.uuid4(), "Finish the race.", CREATED - timedelta(days=1)
            )

    def test_invalid_description_is_rejected(self) -> None:
        with pytest.raises(FutureStateError):
            define_future_state(uuid.uuid4(), "  ", TARGET)


class TestReviseFutureState:
    def test_revision_changes_only_destination_fields(self) -> None:
        state = define_future_state(
            uuid.uuid4(), "Complete the marathon.", TARGET, created_at=CREATED
        )
        later = CREATED + timedelta(days=2)
        new_target = TARGET + timedelta(weeks=8)
        revised = revise_future_state(
            state,
            updated_at=later,
            description="Complete the marathon under 4 hours.",
            target_date=new_target,
        )
        assert revised.state_id == state.state_id
        assert revised.goal_id == state.goal_id
        assert revised.created_at == state.created_at
        assert revised.description == "Complete the marathon under 4 hours."
        assert revised.target_date == new_target
        assert revised.updated_at == later

    def test_partial_revision_keeps_other_fields(self) -> None:
        state = define_future_state(
            uuid.uuid4(), "Complete the marathon.", TARGET, created_at=CREATED
        )
        revised = revise_future_state(
            state, updated_at=CREATED + timedelta(days=1), description="new text"
        )
        assert revised.target_date == state.target_date
        assert revised.description == "new text"

    def test_original_destination_is_unchanged(self) -> None:
        state = define_future_state(
            uuid.uuid4(), "Complete the marathon.", TARGET, created_at=CREATED
        )
        revise_future_state(
            state, updated_at=CREATED + timedelta(days=1), description="new text"
        )
        assert state.description == "Complete the marathon."

    def test_revision_revalidates_fields(self) -> None:
        state = define_future_state(
            uuid.uuid4(), "Complete the marathon.", TARGET, created_at=CREATED
        )
        with pytest.raises(FutureStateError):
            revise_future_state(
                state, updated_at=CREATED + timedelta(days=1), description=""
            )
        with pytest.raises(FutureStateError):
            revise_future_state(
                state,
                updated_at=CREATED + timedelta(days=1),
                target_date=CREATED,  # not after creation
            )

    def test_revision_timestamp_must_not_precede_creation(self) -> None:
        state = define_future_state(
            uuid.uuid4(), "Complete the marathon.", TARGET, created_at=CREATED
        )
        with pytest.raises(FutureStateError):
            revise_future_state(state, updated_at=CREATED - timedelta(seconds=1))
