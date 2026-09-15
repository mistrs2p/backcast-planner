"""Environment configuration for the backcasting backend.

Loads settings from environment variables (optionally seeded from a ``.env``
file) and validates them deterministically before the application starts, so
misconfiguration fails fast with actionable messages instead of at runtime.

Rules:

- ``APP_ENV`` must be one of development / test / staging / production.
- ``LOG_LEVEL`` must be a standard Python logging level.
- ``DATABASE_URL`` must use the PostgreSQL scheme (postgresql:// or
  postgresql+psycopg://) — the technology baseline mandates PostgreSQL.
- ``REDIS_URL`` must use the redis:// scheme.
- ``JWT_SECRET`` is required and must not be a known placeholder in any
  environment, and must be reasonably strong in production.
- ``LLM_PROVIDER``, when set, must be one of the providers supported by the
  LLM abstraction (openai / anthropic / google); ``LLM_MODEL`` requires a
  provider.

This module is stdlib-only by design: dependency selection and pinning happen
in TASK-009 (technology verification). It lives in the application layer, not
the domain, and imports nothing from infrastructure vendors.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping

PLACEHOLDER_SECRETS = {"replace-me", "change-me", "secret", "password", "your-jwt-secret"}

SUPPORTED_LLM_PROVIDERS = frozenset({"openai", "anthropic", "google"})

ALLOWED_DATABASE_SCHEMES = ("postgresql://", "postgresql+psycopg://")

MIN_PRODUCTION_SECRET_LENGTH = 32


class SettingsError(ValueError):
    """Raised when the environment configuration is invalid."""


class AppEnvironment(str, Enum):
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


@dataclass(frozen=True)
class Settings:
    """Validated application settings."""

    app_env: AppEnvironment
    log_level: int
    database_url: str
    redis_url: str
    jwt_secret: str
    llm_provider: str | None = None
    llm_model: str | None = None

    @property
    def is_production(self) -> bool:
        return self.app_env is AppEnvironment.PRODUCTION


def parse_dotenv(path: Path) -> dict[str, str]:
    """Parse a ``.env`` file into a mapping.

    Only simple ``KEY=VALUE`` lines are supported; blank lines and ``#``
    comments are ignored. Values are taken verbatim (no interpolation, no
    shell expansion), which keeps parsing predictable and side-effect free.
    """
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


def _validate(raw: Mapping[str, str]) -> Settings:
    problems: list[str] = []

    app_env_raw = raw.get("APP_ENV", "development").strip().lower()
    try:
        app_env = AppEnvironment(app_env_raw)
    except ValueError:
        allowed = ", ".join(env.value for env in AppEnvironment)
        problems.append(f"APP_ENV {app_env_raw!r} is not one of: {allowed}")

    log_level_name = raw.get("LOG_LEVEL", "INFO").strip().upper()
    log_level = logging.getLevelName(log_level_name)
    if not isinstance(log_level, int):
        problems.append(f"LOG_LEVEL {log_level_name!r} is not a standard logging level")

    database_url = raw.get("DATABASE_URL", "").strip()
    if not database_url:
        problems.append("DATABASE_URL is required")
    elif not database_url.startswith(ALLOWED_DATABASE_SCHEMES):
        problems.append(
            "DATABASE_URL must use the PostgreSQL scheme "
            f"({' or '.join(ALLOWED_DATABASE_SCHEMES)})"
        )

    redis_url = raw.get("REDIS_URL", "").strip()
    if not redis_url:
        problems.append("REDIS_URL is required")
    elif not redis_url.startswith("redis://"):
        problems.append("REDIS_URL must use the redis:// scheme")

    jwt_secret = raw.get("JWT_SECRET", "").strip()
    if not jwt_secret:
        problems.append("JWT_SECRET is required")
    elif jwt_secret.lower() in PLACEHOLDER_SECRETS:
        problems.append("JWT_SECRET must be replaced with a real secret")

    llm_provider = raw.get("LLM_PROVIDER", "").strip().lower() or None
    llm_model = raw.get("LLM_MODEL", "").strip() or None
    if llm_provider is not None and llm_provider not in SUPPORTED_LLM_PROVIDERS:
        problems.append(
            f"LLM_PROVIDER {llm_provider!r} is not one of: "
            f"{', '.join(sorted(SUPPORTED_LLM_PROVIDERS))}"
        )
    if llm_model is not None and llm_provider is None:
        problems.append("LLM_MODEL requires LLM_PROVIDER to be set")

    is_production = app_env_raw == AppEnvironment.PRODUCTION.value
    if is_production and jwt_secret and jwt_secret.lower() not in PLACEHOLDER_SECRETS:
        if len(jwt_secret) < MIN_PRODUCTION_SECRET_LENGTH:
            problems.append(
                f"JWT_SECRET must be at least {MIN_PRODUCTION_SECRET_LENGTH} characters "
                "in production"
            )

    if problems:
        raise SettingsError("invalid environment configuration:\n  - " + "\n  - ".join(problems))

    return Settings(
        app_env=app_env,
        log_level=log_level,
        database_url=database_url,
        redis_url=redis_url,
        jwt_secret=jwt_secret,
        llm_provider=llm_provider,
        llm_model=llm_model,
    )


def load_settings(
    env: Mapping[str, str] | None = None,
    dotenv: Path | None = None,
) -> Settings:
    """Load and validate settings.

    Real environment variables (``env``, defaulting to ``os.environ``) take
    precedence over values from the ``.env`` file: the file seeds defaults,
    it never overrides the actual environment.
    """
    effective: dict[str, str] = {}
    if dotenv is not None and dotenv.is_file():
        effective.update(parse_dotenv(dotenv))
    effective.update(dict(env if env is not None else os.environ))
    return _validate(effective)
