"""Repository structure invariants for the backcasting-planner monorepo.

Established by TASK-001 (Repository bootstrap). These tests pin the bootstrap
contract: the execution pack (rules, state, docs, tasks) and the application
skeleton (apps, packages, infra, scripts, tests) exist as committed content.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_ROOT_FILES = [
    "AGENTS.md",
    "PROJECT_STATE.json",
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CHANGELOG.md",
    ".gitignore",
    ".gitattributes",
    ".env.example",
    "pyproject.toml",
]

REQUIRED_DIRECTORIES = [
    "docs",
    "docs/adr",
    "tasks",
    "apps",
    "apps/api",
    "apps/web",
    "packages",
    "packages/contracts",
    "infra",
    "scripts",
    "tests",
]

# Numbered specification documents expected in docs/ (00 through 15).
REQUIRED_SPEC_DOCS = [
    f"docs/{i:02d}-{name}.md"
    for i, name in enumerate(
        [
            "PROJECT-CONTEXT",
            "PRODUCT-VISION",
            "CONCEPTUAL-MODEL",
            "DOMAIN-MODEL",
            "BACKCASTING-MODEL",
            "CALENDAR-MODEL",
            "PLANNING-SCHEDULING",
            "PROGRESS-FEEDBACK",
            "REPLANNING-MODEL",
            "AI-ARCHITECTURE",
            "TECHNICAL-ARCHITECTURE",
            "AGENT-SYSTEM",
            "IMPLEMENTATION-PLAN",
            "TESTING",
            "DEPLOYMENT",
            "OPERATIONS",
        ],
        start=0,
    )
]

REQUIRED_MEMORY_DOCS = [
    "docs/PROGRESS.md",
    "docs/SESSION-LOG.md",
]

REQUIRED_ADRS = [
    "docs/adr/ADR-001-modular-monolith.md",
    "docs/adr/ADR-002-deterministic-core-ai-separation.md",
    "docs/adr/ADR-003-goal-plan-schedule-separation.md",
    "docs/adr/ADR-004-rolling-horizon.md",
    "docs/adr/ADR-005-tailwind.md",
    "docs/adr/ADR-006-llm-provider-abstraction.md",
    "docs/adr/ADR-007-technology-versions.md",
]


@pytest.mark.parametrize("relative_path", REQUIRED_ROOT_FILES)
def test_root_file_exists(relative_path: str) -> None:
    path = REPO_ROOT / relative_path
    assert path.is_file(), f"required root file missing: {relative_path}"
    assert path.stat().st_size > 0, f"required root file is empty: {relative_path}"


@pytest.mark.parametrize("relative_path", REQUIRED_DIRECTORIES)
def test_directory_exists_and_is_populated(relative_path: str) -> None:
    path = REPO_ROOT / relative_path
    assert path.is_dir(), f"required directory missing: {relative_path}"
    assert any(path.iterdir()), f"required directory is empty: {relative_path}"


@pytest.mark.parametrize("relative_path", REQUIRED_SPEC_DOCS + REQUIRED_MEMORY_DOCS + REQUIRED_ADRS)
def test_documentation_file_exists(relative_path: str) -> None:
    path = REPO_ROOT / relative_path
    assert path.is_file(), f"required documentation missing: {relative_path}"


def test_task_backlog_exists_for_first_epic() -> None:
    epic_dir = REPO_ROOT / "tasks" / "EPIC-001-foundation"
    assert epic_dir.is_dir(), "tasks/EPIC-001-foundation missing"
    task_files = sorted(epic_dir.glob("TASK-*.md"))
    assert len(task_files) >= 10, (
        "EPIC-001-foundation should define at least its 10 baseline tasks"
    )


def test_project_state_is_valid_json_with_required_keys() -> None:
    import json

    state_path = REPO_ROOT / "PROJECT_STATE.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    required_keys = {
        "project",
        "phase",
        "current_epic",
        "current_task",
        "last_completed_task",
        "task_status",
        "blocked_tasks",
        "open_bugs",
        "active_branch",
        "last_validation",
        "technology_baseline",
        "updated_at",
    }
    missing = required_keys - state.keys()
    assert not missing, f"PROJECT_STATE.json missing keys: {sorted(missing)}"
