"""Tests for the CI baseline (.github/workflows/ci.yml, TASK-006).

Validates that the CI workflow exists, parses as YAML, and keeps the
validation contract of AGENTS.md §10: tests plus the repository validators
run on every push and pull request targeting main.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"


@pytest.fixture(scope="module")
def workflow() -> dict:
    assert WORKFLOW_PATH.is_file(), "CI workflow missing: .github/workflows/ci.yml"
    parsed = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    return parsed


def test_workflow_triggers_on_push_and_pull_request(workflow: dict) -> None:
    # PyYAML parses the bare `on:` key as boolean True.
    triggers = workflow.get("on") or workflow.get(True)
    assert "push" in triggers
    assert "pull_request" in triggers
    assert "main" in triggers["push"]["branches"]
    assert "main" in triggers["pull_request"]["branches"]


def test_workflow_runs_the_test_suite(workflow: dict) -> None:
    steps = workflow["jobs"]["validate"]["steps"]
    run_commands = [step.get("run", "") for step in steps]
    assert any("python -m pytest" in command for command in run_commands)


def test_workflow_runs_all_repository_validators(workflow: dict) -> None:
    steps = workflow["jobs"]["validate"]["steps"]
    run_commands = [step.get("run", "") for step in steps]
    for expected in (
        "scripts/check_rules.py",
        "scripts/project_state.py validate",
        "scripts/progress.py check",
    ):
        assert any(expected in command for command in run_commands), (
            f"CI must run {expected}"
        )


def test_workflow_checks_conventional_commits_on_prs(workflow: dict) -> None:
    steps = workflow["jobs"]["validate"]["steps"]
    commit_check = next(
        (step for step in steps if "check-commits" in step.get("run", "")), None
    )
    assert commit_check is not None, "CI must check commit messages"
    assert commit_check.get("if") == "github.event_name == 'pull_request'"


def test_workflow_uses_full_history_checkout(workflow: dict) -> None:
    steps = workflow["jobs"]["validate"]["steps"]
    checkout = next(step for step in steps if step.get("uses", "").startswith("actions/checkout"))
    assert checkout.get("with", {}).get("fetch-depth") == 0


def test_workflow_sets_python_version(workflow: dict) -> None:
    setup = next(
        step for step in workflow["jobs"]["validate"]["steps"]
        if step.get("uses", "").startswith("actions/setup-python")
    )
    assert setup["with"]["python-version"] == "3.12"
