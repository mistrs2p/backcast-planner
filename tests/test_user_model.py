"""Tests for the User domain model (TASK-011).

Covers the Email value object's validation/normalization, the User entity's
invariants (identity, awareness of timestamps in UTC, display-name rules,
IANA timezone), and the ``create_user`` factory.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backcasting.domain.user import (
    MAX_DISPLAY_NAME_LENGTH,
    Email,
    User,
    UserError,
    create_user,
)


class TestEmail:
    def test_valid_email_is_preserved(self) -> None:
        assert Email("Ada.Lovelace@example.com").address == "Ada.Lovelace@example.com"

    def test_domain_is_lowercased(self) -> None:
        assert Email("user@EXAMPLE.COM").address == "user@example.com"

    def test_surrounding_dots_in_local_part_are_stripped(self) -> None:
        assert Email(".user.@example.com").address == "user@example.com"

    def test_string_form_is_the_address(self) -> None:
        assert str(Email("user@example.com")) == "user@example.com"

    def test_equality_by_value(self) -> None:
        assert Email("user@example.com") == Email("user@EXAMPLE.COM")

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "no-at-sign",
            "two@at@signs.example",
            "@example.com",
            "user@",
            "user@example",
            "user@-example-.com",
            "user name@example.com",
            "us er@example.com",
            "user@@example.com",
        ],
    )
    def test_invalid_emails_are_rejected(self, raw: str) -> None:
        with pytest.raises(UserError):
            Email(raw)

    def test_overlong_local_part_is_rejected(self) -> None:
        with pytest.raises(UserError):
            Email(f"{'a' * 65}@example.com")

    def test_non_string_is_rejected(self) -> None:
        with pytest.raises(UserError):
            Email(None)  # type: ignore[arg-type]


class TestUser:
    def _valid_kwargs(self) -> dict:
        return {
            "user_id": uuid.uuid4(),
            "email": Email("user@example.com"),
            "display_name": "Ada Lovelace",
            "timezone": ZoneInfo("Europe/London"),
            "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        }

    def test_valid_user_round_trips(self) -> None:
        kwargs = self._valid_kwargs()
        user = User(**kwargs)
        assert user.user_id == kwargs["user_id"]
        assert user.email == kwargs["email"]
        assert user.display_name == "Ada Lovelace"
        assert user.timezone == ZoneInfo("Europe/London")
        assert user.created_at == kwargs["created_at"]

    def test_display_name_is_stripped(self) -> None:
        user = User(**{**self._valid_kwargs(), "display_name": "  Ada  "})
        assert user.display_name == "Ada"

    def test_user_is_immutable(self) -> None:
        user = User(**self._valid_kwargs())
        with pytest.raises(AttributeError):
            user.display_name = "someone else"  # type: ignore[misc]

    def test_non_uuid_id_is_rejected(self) -> None:
        with pytest.raises(UserError):
            User(**{**self._valid_kwargs(), "user_id": "not-a-uuid"})

    def test_raw_string_email_is_rejected(self) -> None:
        with pytest.raises(UserError):
            User(**{**self._valid_kwargs(), "email": "user@example.com"})

    def test_string_timezone_is_rejected(self) -> None:
        with pytest.raises(UserError):
            User(**{**self._valid_kwargs(), "timezone": "Europe/London"})

    @pytest.mark.parametrize("bad_name", ["", "   ", "x" * (MAX_DISPLAY_NAME_LENGTH + 1)])
    def test_invalid_display_names_are_rejected(self, bad_name: str) -> None:
        with pytest.raises(UserError):
            User(**{**self._valid_kwargs(), "display_name": bad_name})

    def test_naive_created_at_is_rejected(self) -> None:
        with pytest.raises(UserError):
            User(**{**self._valid_kwargs(), "created_at": datetime(2026, 1, 1)})

    def test_non_utc_created_at_is_rejected(self) -> None:
        created = datetime(
            2026, 1, 1, 12, tzinfo=ZoneInfo("Europe/Berlin")
        )  # UTC+1 at that instant
        assert created.utcoffset() != timezone.utc.utcoffset(created)
        with pytest.raises(UserError):
            User(**{**self._valid_kwargs(), "created_at": created})


class TestCreateUser:
    def test_generates_identity_and_timestamp(self) -> None:
        before = datetime.now(timezone.utc)
        user = create_user("user@example.com", "Ada")
        after = datetime.now(timezone.utc)
        assert isinstance(user.user_id, uuid.UUID)
        assert before <= user.created_at <= after
        assert user.timezone == ZoneInfo("UTC")

    def test_injected_id_and_timestamp_are_honoured(self) -> None:
        user_id = uuid.uuid4()
        created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        user = create_user(
            "user@example.com",
            "Ada",
            timezone_name="Asia/Tehran",
            user_id=user_id,
            created_at=created_at,
        )
        assert user.user_id == user_id
        assert user.created_at == created_at
        assert user.timezone == ZoneInfo("Asia/Tehran")

    def test_injected_timestamp_must_be_utc(self) -> None:
        naive = datetime(2026, 1, 1)
        with pytest.raises(UserError):
            create_user("user@example.com", "Ada", created_at=naive)

    @pytest.mark.parametrize("bad_zone", ["", "Not/A_Zone", "Mars/Olympus_Mons"])
    def test_unknown_timezone_is_rejected(self, bad_zone: str) -> None:
        with pytest.raises(UserError):
            create_user("user@example.com", "Ada", timezone_name=bad_zone)

    def test_invalid_email_is_rejected(self) -> None:
        with pytest.raises(UserError):
            create_user("not-an-email", "Ada")
