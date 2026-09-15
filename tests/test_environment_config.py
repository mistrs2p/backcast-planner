"""Tests for environment configuration (apps/api/src/backcasting/config.py, TASK-008)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from backcasting.config import (
    AppEnvironment,
    SettingsError,
    load_settings,
    parse_dotenv,
)

VALID_ENV = {
    "APP_ENV": "development",
    "LOG_LEVEL": "INFO",
    "DATABASE_URL": "postgresql+psycopg://app:app@localhost:5432/backcasting",
    "REDIS_URL": "redis://localhost:6379/0",
    "JWT_SECRET": "a-sufficiently-long-development-secret",
}


def load(env: dict[str, str], **kwargs):
    return load_settings(env, **kwargs)


class TestValidConfigurations:
    def test_minimal_environment_uses_defaults(self) -> None:
        settings = load(
            {
                "DATABASE_URL": VALID_ENV["DATABASE_URL"],
                "REDIS_URL": VALID_ENV["REDIS_URL"],
                "JWT_SECRET": VALID_ENV["JWT_SECRET"],
            }
        )
        assert settings.app_env is AppEnvironment.DEVELOPMENT
        assert settings.log_level == logging.INFO
        assert settings.llm_provider is None
        assert settings.llm_model is None
        assert not settings.is_production

    def test_all_fields_load(self) -> None:
        settings = load(
            {
                **VALID_ENV,
                "APP_ENV": "staging",
                "LOG_LEVEL": "debug",
                "LLM_PROVIDER": "anthropic",
                "LLM_MODEL": "claude-sonnet-5",
            }
        )
        assert settings.app_env is AppEnvironment.STAGING
        assert settings.log_level == logging.DEBUG
        assert settings.llm_provider == "anthropic"
        assert settings.llm_model == "claude-sonnet-5"

    @pytest.mark.parametrize(
        "provider", ["openai", "anthropic", "google"]
    )
    def test_supported_llm_providers(self, provider: str) -> None:
        settings = load({**VALID_ENV, "LLM_PROVIDER": provider})
        assert settings.llm_provider == provider

    def test_dotenv_example_is_a_valid_seed(self, tmp_path: Path) -> None:
        """The committed .env.example must parse and validate as a seed file."""
        repo_root = Path(__file__).resolve().parents[1]
        dotenv = tmp_path / ".env"
        dotenv.write_text(
            (repo_root / ".env.example").read_text(encoding="utf-8"), encoding="utf-8"
        )
        parsed = parse_dotenv(dotenv)
        assert parsed["APP_ENV"] == "development"
        # Placeholder secret seeds must be rejected by validation.
        with pytest.raises(SettingsError, match="JWT_SECRET"):
            load_settings(VALID_ENV | {"JWT_SECRET": ""}, dotenv=dotenv)


class TestInvalidConfigurations:
    @pytest.mark.parametrize(
        "overrides, expected_problem",
        [
            ({"APP_ENV": "prod"}, "APP_ENV"),
            ({"LOG_LEVEL": "loud"}, "LOG_LEVEL"),
            ({"DATABASE_URL": "mysql://localhost/db"}, "PostgreSQL scheme"),
            ({"DATABASE_URL": ""}, "DATABASE_URL is required"),
            ({"REDIS_URL": "amqp://localhost"}, "redis://"),
            ({"JWT_SECRET": ""}, "JWT_SECRET is required"),
            ({"JWT_SECRET": "replace-me"}, "real secret"),
            ({"LLM_PROVIDER": "cohere"}, "LLM_PROVIDER"),
            ({"LLM_MODEL": "gpt-5"}, "LLM_PROVIDER to be set"),
        ],
    )
    def test_invalid_values_are_rejected(
        self, overrides: dict[str, str], expected_problem: str
    ) -> None:
        with pytest.raises(SettingsError, match=expected_problem):
            load({**VALID_ENV, **overrides})

    def test_all_problems_are_reported_at_once(self) -> None:
        with pytest.raises(SettingsError) as exc_info:
            load({"APP_ENV": "development"})
        message = str(exc_info.value)
        for expected in ("DATABASE_URL", "REDIS_URL", "JWT_SECRET"):
            assert expected in message

    def test_short_production_secret_is_rejected(self) -> None:
        with pytest.raises(SettingsError, match="at least 32 characters"):
            load({**VALID_ENV, "APP_ENV": "production", "JWT_SECRET": "too-short-for-prod"})

    def test_long_production_secret_is_accepted(self) -> None:
        settings = load(
            {
                **VALID_ENV,
                "APP_ENV": "production",
                "JWT_SECRET": "x" * 48,
            }
        )
        assert settings.is_production


class TestDotenvParsing:
    def test_comments_and_blanks_are_ignored(self, tmp_path: Path) -> None:
        dotenv = tmp_path / ".env"
        dotenv.write_text(
            "# comment\n\nAPP_ENV=test\n  LOG_LEVEL = warning \n",
            encoding="utf-8",
        )
        parsed = parse_dotenv(dotenv)
        assert parsed == {"APP_ENV": "test", "LOG_LEVEL": "warning"}

    def test_quoted_values_are_stripped(self, tmp_path: Path) -> None:
        dotenv = tmp_path / ".env"
        dotenv.write_text('JWT_SECRET="quoted-secret"\n', encoding="utf-8")
        assert parse_dotenv(dotenv) == {"JWT_SECRET": "quoted-secret"}

    def test_environment_overrides_dotenv(self, tmp_path: Path) -> None:
        dotenv = tmp_path / ".env"
        dotenv.write_text(
            "\n".join(f"{key}={value}" for key, value in VALID_ENV.items())
            + "\nLOG_LEVEL=error\n",
            encoding="utf-8",
        )
        settings = load_settings({"LOG_LEVEL": "warning"}, dotenv=dotenv)
        assert settings.log_level == logging.WARNING

    def test_missing_dotenv_is_ignored(self, tmp_path: Path) -> None:
        settings = load_settings(VALID_ENV, dotenv=tmp_path / "does-not-exist")
        assert settings.app_env is AppEnvironment.DEVELOPMENT
