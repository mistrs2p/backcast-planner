"""Tests for AGENTS.md rule enforcement (scripts/check_rules.py, TASK-002).

Covers the machine-checkable rules: AGENTS.md presence and structure, tracked
secret files, placeholder-only .env.example values, and domain-layer import
purity. Fixtures run against temporary roots so each rule's detection and
allowance behavior is exercised independently of the real repository.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import check_rules  # noqa: E402

AGENTS_MD = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")


def make_root(tmp_path: Path, *, agents_md: str | None = AGENTS_MD) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    if agents_md is not None:
        (root / "AGENTS.md").write_text(agents_md, encoding="utf-8")
    return root


def git_track(root: Path, *relative_paths: str) -> None:
    """Initialize a git repo in root and stage the given paths."""
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", *relative_paths], cwd=root, check=True)


class TestAgentsMdCheck:
    def test_real_repository_passes(self) -> None:
        assert check_rules.check_agents_md(REPO_ROOT) == []

    def test_missing_agents_md_is_reported(self, tmp_path: Path) -> None:
        root = make_root(tmp_path, agents_md=None)
        violations = check_rules.check_agents_md(root)
        assert len(violations) == 1
        assert violations[0].rule == "agents-md"

    def test_removed_required_section_is_reported(self, tmp_path: Path) -> None:
        weakened = AGENTS_MD.replace("## 16. Forbidden Behaviors", "## 16. Guidelines")
        root = make_root(tmp_path, agents_md=weakened)
        violations = check_rules.check_agents_md(root)
        assert any("Forbidden Behaviors" in v.detail for v in violations)


class TestTrackedSecretsCheck:
    def test_real_repository_passes(self) -> None:
        assert check_rules.check_tracked_secrets(REPO_ROOT) == []

    def test_tracked_env_file_is_reported(self, tmp_path: Path) -> None:
        root = make_root(tmp_path)
        (root / ".env").write_text("JWT_SECRET=x", encoding="utf-8")
        git_track(root, ".env")
        violations = check_rules.check_tracked_secrets(root)
        assert any(v.location == ".env" for v in violations)

    def test_tracked_private_key_is_reported(self, tmp_path: Path) -> None:
        root = make_root(tmp_path)
        (root / "server.pem").write_text("-----BEGIN PRIVATE KEY-----", encoding="utf-8")
        git_track(root, "server.pem")
        violations = check_rules.check_tracked_secrets(root)
        assert any(v.location == "server.pem" for v in violations)

    def test_untracked_env_file_is_allowed(self, tmp_path: Path) -> None:
        root = make_root(tmp_path)
        (root / ".env").write_text("JWT_SECRET=x", encoding="utf-8")
        git_track(root, "AGENTS.md")  # only AGENTS.md staged; .env untracked
        assert check_rules.check_tracked_secrets(root) == []

    def test_real_credential_in_env_example_is_reported(self, tmp_path: Path) -> None:
        root = make_root(tmp_path)
        (root / ".env.example").write_text(
            "JWT_SECRET=9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c\n",
            encoding="utf-8",
        )
        violations = check_rules.check_tracked_secrets(root)
        assert any(v.location == ".env.example:1" for v in violations)

    def test_placeholder_secret_in_env_example_is_allowed(self, tmp_path: Path) -> None:
        root = make_root(tmp_path)
        (root / ".env.example").write_text(
            "JWT_SECRET=replace-me\nLLM_API_KEY=your-key\n",
            encoding="utf-8",
        )
        assert check_rules.check_tracked_secrets(root) == []

    def test_local_dev_dsn_is_allowed(self, tmp_path: Path) -> None:
        root = make_root(tmp_path)
        (root / ".env.example").write_text(
            "DATABASE_URL=postgresql+psycopg://app:app@localhost:5432/backcasting\n",
            encoding="utf-8",
        )
        assert check_rules.check_tracked_secrets(root) == []

    def test_remote_credentialed_dsn_is_reported(self, tmp_path: Path) -> None:
        root = make_root(tmp_path)
        (root / ".env.example").write_text(
            "DATABASE_URL=postgresql://prod:hunter2@db.example.com:5432/prod\n",
            encoding="utf-8",
        )
        violations = check_rules.check_tracked_secrets(root)
        assert any(v.location == ".env.example:1" for v in violations)


class TestDomainPurityCheck:
    def write_domain_module(self, root: Path, source: str) -> Path:
        domain = root / "apps" / "api" / "src" / "backcasting" / "domain"
        domain.mkdir(parents=True)
        module = domain / "goal.py"
        module.write_text(source, encoding="utf-8")
        return module

    def test_real_repository_passes(self) -> None:
        assert check_rules.check_domain_purity(REPO_ROOT) == []

    def test_forbidden_import_is_reported(self, tmp_path: Path) -> None:
        root = make_root(tmp_path)
        self.write_domain_module(root, "import sqlalchemy\n")
        violations = check_rules.check_domain_purity(root)
        assert any("sqlalchemy" in v.detail for v in violations)

    def test_forbidden_from_import_is_reported(self, tmp_path: Path) -> None:
        root = make_root(tmp_path)
        self.write_domain_module(root, "from fastapi import Depends\n")
        violations = check_rules.check_domain_purity(root)
        assert any("fastapi" in v.detail for v in violations)

    def test_vendor_llm_sdk_imports_are_reported(self, tmp_path: Path) -> None:
        root = make_root(tmp_path)
        self.write_domain_module(root, "from google import genai\nimport anthropic\n")
        violations = check_rules.check_domain_purity(root)
        details = " ".join(v.detail for v in violations)
        assert "google.genai" in details
        assert "anthropic" in details

    def test_unrelated_google_import_is_allowed(self, tmp_path: Path) -> None:
        root = make_root(tmp_path)
        self.write_domain_module(root, "import google.cloud.storage\n")
        assert check_rules.check_domain_purity(root) == []

    def test_stdlib_and_typing_imports_are_allowed(self, tmp_path: Path) -> None:
        root = make_root(tmp_path)
        self.write_domain_module(
            root,
            "from __future__ import annotations\n"
            "import uuid\nfrom dataclasses import dataclass\nfrom datetime import datetime\n",
        )
        assert check_rules.check_domain_purity(root) == []

    def test_presentation_layer_outside_domain_is_allowed(self, tmp_path: Path) -> None:
        root = make_root(tmp_path)
        presentation = root / "apps" / "api" / "src" / "backcasting" / "presentation"
        presentation.mkdir(parents=True)
        (presentation / "routes.py").write_text("import fastapi\n", encoding="utf-8")
        assert check_rules.check_domain_purity(root) == []

    def test_unparsable_domain_file_is_reported(self, tmp_path: Path) -> None:
        root = make_root(tmp_path)
        self.write_domain_module(root, "def broken(:\n")
        violations = check_rules.check_domain_purity(root)
        assert any("cannot parse" in v.detail for v in violations)


class TestRunner:
    def test_real_repository_has_no_violations(self) -> None:
        assert check_rules.run_all_checks(REPO_ROOT) == []

    def test_script_exit_code_zero_on_real_repository(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "check_rules.py")],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "OK" in result.stdout

    def test_script_exit_code_one_on_violation(self, tmp_path: Path) -> None:
        root = make_root(tmp_path, agents_md="# empty\n")
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "check_rules.py"), "--root", str(root)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert "violation" in result.stdout
