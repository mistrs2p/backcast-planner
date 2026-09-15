"""Tests for the Docker baseline (infra/docker-compose.yml, TASK-007).

Validates that the local development environment provides PostgreSQL and
Redis with health checks and persistent storage, that credentials come from
environment placeholders rather than hard-coded secrets, and — when the
Docker CLI is available — that `docker compose config` accepts the file.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = REPO_ROOT / "infra" / "docker-compose.yml"


@pytest.fixture(scope="module")
def compose() -> dict:
    assert COMPOSE_PATH.is_file(), "docker compose file missing: infra/docker-compose.yml"
    parsed = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    return parsed


def test_postgres_service_is_defined(compose: dict) -> None:
    postgres = compose["services"]["postgres"]
    assert postgres["image"].startswith("postgres:")
    assert "5432:5432" in postgres["ports"][0] or postgres["ports"][0].endswith(":5432")


def test_postgres_has_persistent_volume(compose: dict) -> None:
    postgres = compose["services"]["postgres"]["volumes"]
    # Regression: PostgreSQL 18 rejects a mount directly at the data directory;
    # the volume must mount at /var/lib/postgresql (data lives in a subdirectory,
    # see docker-library/postgres#37).
    assert "postgres-data:/var/lib/postgresql" in postgres
    assert "postgres-data" in compose["volumes"]


def test_postgres_credentials_use_placeholders(compose: dict) -> None:
    environment = compose["services"]["postgres"]["environment"]
    for key in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"):
        assert key in environment
        value = environment[key]
        assert "${" in value, f"{key} must default via an environment placeholder"


def test_redis_service_is_defined(compose: dict) -> None:
    redis = compose["services"]["redis"]
    assert redis["image"].startswith("redis:")
    assert redis["ports"][0].endswith(":6379")


def test_both_services_have_healthchecks(compose: dict) -> None:
    for service in ("postgres", "redis"):
        healthcheck = compose["services"][service]["healthcheck"]
        assert healthcheck["test"]
        assert "interval" in healthcheck
        assert "retries" in healthcheck


def test_no_hardcoded_secrets_in_compose_file() -> None:
    content = COMPOSE_PATH.read_text(encoding="utf-8")
    # Credentials must arrive through ${VAR:-default} placeholders.
    assert "POSTGRES_PASSWORD: ${" in content


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker CLI not available")
def test_docker_compose_accepts_the_file() -> None:
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_PATH), "config", "--quiet"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
