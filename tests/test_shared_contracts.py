"""Tests for the shared contracts foundation (TASK-010).

Covers the FastAPI application factory, the /health endpoint, and the
committed OpenAPI contract in packages/contracts: it must exist, be valid
OpenAPI, expose the health route, and match a fresh generation from the
application (no drift).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
CONTRACT_PATH = REPO_ROOT / "packages" / "contracts" / "openapi.json"


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backcasting.app import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


class TestApplication:
    def test_app_metadata(self, client) -> None:
        app = client.app
        assert app.title == "Backcasting Planner API"
        assert app.version

    def test_health_endpoint(self, client) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


@pytest.fixture(scope="module")
def contract() -> dict:
    assert CONTRACT_PATH.is_file(), "committed contract missing: packages/contracts/openapi.json"
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


class TestCommittedContract:

    def test_is_openapi_3_1(self, contract: dict) -> None:
        assert contract["openapi"].startswith("3.")

    def test_exposes_health_route(self, contract: dict) -> None:
        health = contract["paths"]["/health"]["get"]
        assert health["operationId"] == "getHealth"
        assert health["tags"] == ["system"]

    def test_carries_api_identity(self, contract: dict) -> None:
        assert contract["info"]["title"] == "Backcasting Planner API"
        assert contract["info"]["version"]

    def test_committed_contract_matches_application(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "generate_contracts.py"), "--check"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
