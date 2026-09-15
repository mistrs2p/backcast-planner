"""User domain model.

The User is the root of ownership in the domain: a user owns goals, the
calendar, availability, preferences, constraints, habits, and routines
(`docs/03-DOMAIN-MODEL.md`). This module defines the entity and its value
objects with the invariants that hold regardless of persistence or delivery
mechanism.

Rules:

- IDs are UUIDs (``docs/10-TECHNICAL-ARCHITECTURE.md``).
- Emails are validated and normalized (case-folded local/domain comparison
  is intentionally simple: the domain part is lowercased, the local part is
  preserved except for a trailing normalization of a leading/trailing
  dot-run, which addresses cannot contain).
- The timezone must be a valid IANA zone name; persisted instants use UTC
  and the user's timezone is used for interpretation and display
  (``AGENTS.md`` §7).
- ``created_at`` must be timezone-aware and UTC.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "UTC"

_EMAIL_LOCAL = re.compile(r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+$")
_EMAIL_DOMAIN = re.compile(
    r"^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?"
    r"(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+$"
)

MAX_DISPLAY_NAME_LENGTH = 100


class UserError(ValueError):
    """Raised when a User invariant is violated."""


@dataclass(frozen=True)
class Email:
    """A validated, normalized email address value object."""

    address: str

    def __post_init__(self) -> None:
        address = self.address
        if not isinstance(address, str) or address.count("@") != 1:
            raise UserError(f"invalid email address: {address!r}")
        local, domain = address.split("@")
        local = local.strip(".")
        domain = domain.lower()
        if not local or len(local) > 64:
            raise UserError(f"invalid email local part: {local!r}")
        if not _EMAIL_LOCAL.match(local):
            raise UserError(f"invalid email local part: {local!r}")
        if len(domain) > 255 or not _EMAIL_DOMAIN.match(domain):
            raise UserError(f"invalid email domain: {domain!r}")
        object.__setattr__(self, "address", f"{local}@{domain}")

    def __str__(self) -> str:
        return self.address


@dataclass(frozen=True)
class User:
    """A registered user of the planning system."""

    user_id: uuid.UUID
    email: Email
    display_name: str
    timezone: ZoneInfo = field(default_factory=lambda: ZoneInfo(DEFAULT_TIMEZONE))
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def __post_init__(self) -> None:
        if not isinstance(self.user_id, uuid.UUID):
            raise UserError("user_id must be a UUID")
        if not isinstance(self.email, Email):
            raise UserError("email must be an Email value object")
        if not isinstance(self.timezone, ZoneInfo):
            raise UserError("timezone must be a ZoneInfo")
        name = self.display_name
        if not isinstance(name, str) or not name.strip():
            raise UserError("display_name must be a non-empty string")
        if len(name.strip()) > MAX_DISPLAY_NAME_LENGTH:
            raise UserError(
                f"display_name must be at most {MAX_DISPLAY_NAME_LENGTH} characters"
            )
        object.__setattr__(self, "display_name", name.strip())
        created = self.created_at
        if not isinstance(created, datetime) or created.tzinfo is None:
            raise UserError("created_at must be timezone-aware")
        if created.utcoffset() != timezone.utc.utcoffset(created):
            raise UserError("created_at must be in UTC")


def create_user(
    email: str,
    display_name: str,
    *,
    timezone_name: str = DEFAULT_TIMEZONE,
    user_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> User:
    """Create a User, generating identity and timestamps when not supplied.

    ``created_at`` may be injected for deterministic tests; it must still be
    timezone-aware UTC.
    """
    try:
        user_timezone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
        raise UserError(f"unknown timezone: {timezone_name!r}") from exc
    return User(
        user_id=user_id if user_id is not None else uuid.uuid4(),
        email=Email(email),
        display_name=display_name,
        timezone=user_timezone,
        created_at=created_at if created_at is not None else datetime.now(timezone.utc),
    )
