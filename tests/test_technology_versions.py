"""Traceability tests for the verified technology baseline (TASK-009).

Pins the contract of docs/adr/ADR-007-technology-versions.md: every backend
dependency and dev dependency is exactly pinned, Docker images use exact
tags, and each pinned version is recorded in the ADR, so versions cannot
drift silently from their verified rationale.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
ADR_PATH = REPO_ROOT / "docs" / "adr" / "ADR-007-technology-versions.md"
API_PYPROJECT = REPO_ROOT / "apps" / "api" / "pyproject.toml"
COMPOSE_PATH = REPO_ROOT / "infra" / "docker-compose.yml"
REQUIREMENTS_DEV = REPO_ROOT / "requirements-dev.txt"

EXACT_PIN = re.compile(r"^([A-Za-z0-9_.\[\]-]+)==(\d[^ ;]+)$")


def parse_pins(lines: list[str]) -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = EXACT_PIN.match(stripped)
        assert match is not None, f"dependency must be exactly pinned (==): {stripped!r}"
        pins[match.group(1)] = match.group(2)
    return pins


def api_dependencies() -> dict[str, str]:
    content = API_PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r"^dependencies = \[\n((?:.*\n)*?)\]", content, re.MULTILINE)
    assert match is not None, "apps/api/pyproject.toml must declare dependencies"
    return parse_pins(re.findall(r'"([^"]+)"', match.group(1)))


@pytest.fixture(scope="module")
def adr_content() -> str:
    assert ADR_PATH.is_file()
    return ADR_PATH.read_text(encoding="utf-8")


class TestBackendPins:
    def test_expected_dependencies_are_pinned(self) -> None:
        pins = api_dependencies()
        expected = {
            "fastapi": "0.141.1",
            "uvicorn[standard]": "0.53.0",
            "sqlalchemy": "2.0.53",
            "alembic": "1.20.0",
            "psycopg[binary]": "3.3.5",
            "redis": "8.1.0",
            "tzdata": "2026.4",
        }
        assert pins == expected

    def test_python_requires_matches_verified_runtime(self) -> None:
        content = API_PYPROJECT.read_text(encoding="utf-8")
        assert 'requires-python = ">=3.12,<3.14"' in content

    def test_every_pin_is_recorded_in_the_adr(self, adr_content: str) -> None:
        for name, version in api_dependencies().items():
            base_name = name.split("[")[0]
            assert version in adr_content, f"{name} pin {version} missing from ADR-007"
            assert base_name in adr_content.lower(), f"{base_name} missing from ADR-007"


class TestDevPins:
    def test_requirements_dev_is_exactly_pinned(self) -> None:
        pins = parse_pins(REQUIREMENTS_DEV.read_text(encoding="utf-8").splitlines())
        assert pins == {"pytest": "9.1.1", "pyyaml": "6.0.3"}

    def test_pins_are_recorded_in_the_adr(self, adr_content: str) -> None:
        for version in ("9.1.1", "6.0.3"):
            assert version in adr_content


class TestInfrastructurePins:
    def test_compose_images_use_exact_tags(self) -> None:
        compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
        assert compose["services"]["postgres"]["image"] == "postgres:18.4"
        assert compose["services"]["redis"]["image"] == "redis:7.4.11-alpine"

    def test_infrastructure_versions_are_recorded_in_the_adr(self, adr_content: str) -> None:
        for version in ("18.4", "7.4.11"):
            assert version in adr_content


class TestFrontendRecord:
    def test_adr_records_verified_frontend_versions(self, adr_content: str) -> None:
        for version in ("16.3.5", "19.3.0", "4.3.3", "5.9.3"):
            assert version in adr_content

    def test_adr_documents_the_typescript_rationale(self, adr_content: str) -> None:
        # The ADR must explain why the newest TypeScript major was not chosen.
        assert "Deliberately not the highest" in adr_content

    def test_adr_documents_the_worker_deferral(self, adr_content: str) -> None:
        assert "deferred" in adr_content.lower()
