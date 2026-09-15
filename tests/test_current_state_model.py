"""Tests for the Current State domain model (TASK-013).

Covers the snapshot invariants: UUID identity, goal reference, non-empty
bounded narrative, timezone-aware UTC capture time, immutability, and the
capture factory.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from backcasting.domain.current_state import (
    MAX_NARRATIVE_LENGTH,
    CurrentState,
    CurrentStateError,
    capture_current_state,
)

CAPTURED = datetime(2026, 1, 1, tzinfo=timezone.utc)


class TestCurrentState:
    def _valid_kwargs(self) -> dict:
        return {
            "state_id": uuid.uuid4(),
            "goal_id": uuid.uuid4(),
            "narrative": "Can run 5 km comfortably, no race experience.",
            "captured_at": CAPTURED,
        }

    def test_valid_snapshot_round_trips(self) -> None:
        kwargs = self._valid_kwargs()
        state = CurrentState(**kwargs)
        assert state.state_id == kwargs["state_id"]
        assert state.goal_id == kwargs["goal_id"]
        assert state.narrative == kwargs["narrative"]
        assert state.captured_at == CAPTURED

    def test_narrative_is_stripped(self) -> None:
        state = CurrentState(
            **{**self._valid_kwargs(), "narrative": "  reality  "}
        )
        assert state.narrative == "reality"

    def test_snapshot_is_immutable(self) -> None:
        state = CurrentState(**self._valid_kwargs())
        with pytest.raises(AttributeError):
            state.narrative = "different reality"  # type: ignore[misc]

    def test_non_uuid_ids_are_rejected(self) -> None:
        with pytest.raises(CurrentStateError):
            CurrentState(**{**self._valid_kwargs(), "state_id": "not-a-uuid"})
        with pytest.raises(CurrentStateError):
            CurrentState(**{**self._valid_kwargs(), "goal_id": None})

    @pytest.mark.parametrize(
        "bad_narrative", ["", "   ", "x" * (MAX_NARRATIVE_LENGTH + 1)]
    )
    def test_invalid_narratives_are_rejected(self, bad_narrative: str) -> None:
        with pytest.raises(CurrentStateError):
            CurrentState(**{**self._valid_kwargs(), "narrative": bad_narrative})

    def test_naive_capture_time_is_rejected(self) -> None:
        with pytest.raises(CurrentStateError):
            CurrentState(**{**self._valid_kwargs(), "captured_at": datetime(2026, 1, 1)})

    def test_non_utc_capture_time_is_rejected(self) -> None:
        # Europe/Berlin is UTC+1 on 2026-01-01.
        local = datetime(2026, 1, 1, 12, tzinfo=ZoneInfo("Europe/Berlin"))
        with pytest.raises(CurrentStateError):
            CurrentState(**{**self._valid_kwargs(), "captured_at": local})


class TestCaptureCurrentState:
    def test_generates_identity_and_timestamp(self) -> None:
        before = datetime.now(timezone.utc)
        state = capture_current_state(uuid.uuid4(), "Present reality")
        after = datetime.now(timezone.utc)
        assert isinstance(state.state_id, uuid.UUID)
        assert before <= state.captured_at <= after

    def test_injected_id_and_timestamp_are_honoured(self) -> None:
        state_id = uuid.uuid4()
        state = capture_current_state(
            uuid.uuid4(),
            "Present reality",
            state_id=state_id,
            captured_at=CAPTURED,
        )
        assert state.state_id == state_id
        assert state.captured_at == CAPTURED

    def test_invalid_narrative_is_rejected(self) -> None:
        with pytest.raises(CurrentStateError):
            capture_current_state(uuid.uuid4(), "  ")

    def test_snapshots_are_independent_instances(self) -> None:
        goal_id = uuid.uuid4()
        first = capture_current_state(goal_id, "Before training")
        second = capture_current_state(goal_id, "After six weeks of training")
        assert first is not second
        assert first.narrative == "Before training"
        assert second.narrative == "After six weeks of training"
