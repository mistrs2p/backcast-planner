"""Tests for PROJECT_STATE foundation (scripts/project_state.py, TASK-003).

Validates the state schema, task-manifest integrity, and the consistency rules
that keep PROJECT_STATE.json honest against the task backlog: current task
exists and is not already completed, dependencies are completed before a task
becomes current, and the last completed task is really marked COMPLETED.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import project_state  # noqa: E402

VALID_STATE: dict[str, Any] = {
    "project": "backcasting-planner",
    "phase": "implementation",
    "current_epic": "EPIC-001-foundation",
    "current_task": "TASK-004",
    "last_completed_task": "TASK-003",
    "task_status": "ready",
    "blocked_tasks": [],
    "open_bugs": [],
    "active_branch": None,
    "last_validation": {
        "tests": "pass",
        "lint": "not_applicable",
        "typecheck": "not_applicable",
        "build": "not_applicable",
    },
    "technology_baseline": {"frontend": "Next.js"},
    "updated_at": "2026-09-15",
}


def make_repo(
    tmp_path: Path,
    state: dict[str, Any] | None = None,
    manifest: list[dict[str, Any]] | None = None,
) -> Path:
    """A minimal repository fixture with a state file and task backlog."""
    root = tmp_path / "repo"
    root.mkdir()
    state = VALID_STATE if state is None else state
    (root / "PROJECT_STATE.json").write_text(
        json.dumps(state, indent=2), encoding="utf-8"
    )

    entries = manifest if manifest is not None else [
        {
            "id": 1,
            "title": "First",
            "epic": "EPIC-001-foundation",
            "dependencies": [],
            "path": "EPIC-001-foundation/TASK-001-first.md",
        },
        {
            "id": 2,
            "title": "Second",
            "epic": "EPIC-001-foundation",
            "dependencies": [1],
            "path": "EPIC-001-foundation/TASK-002-second.md",
        },
        {
            "id": 3,
            "title": "Third",
            "epic": "EPIC-001-foundation",
            "dependencies": [1, 2],
            "path": "EPIC-001-foundation/TASK-003-third.md",
        },
        {
            "id": 4,
            "title": "Fourth",
            "epic": "EPIC-001-foundation",
            "dependencies": [3],
            "path": "EPIC-001-foundation/TASK-004-fourth.md",
        },
    ]
    (root / "tasks" / "EPIC-001-foundation").mkdir(parents=True)

    def write_task(path: str, status: str) -> None:
        task_file = root / "tasks" / path
        task_file.parent.mkdir(parents=True, exist_ok=True)
        task_file.write_text(
            f"# {path}\n\n## Status\n{status}\n\n## Dependencies\nNone\n",
            encoding="utf-8",
        )

    write_task("EPIC-001-foundation/TASK-001-first.md", "COMPLETED")
    write_task("EPIC-001-foundation/TASK-002-second.md", "COMPLETED")
    write_task("EPIC-001-foundation/TASK-003-third.md", "COMPLETED")
    write_task("EPIC-001-foundation/TASK-004-fourth.md", "READY")

    (root / "tasks" / "TASK-MANIFEST.json").write_text(
        json.dumps(entries, indent=2), encoding="utf-8"
    )
    return root


def validate_fixture(root: Path) -> list[str]:
    state = json.loads((root / "PROJECT_STATE.json").read_text(encoding="utf-8"))
    manifest = project_state.load_manifest(root)
    return [v.render() for v in project_state.validate_state(state, root, manifest)]


class TestSchema:
    def test_valid_state_passes(self, tmp_path: Path) -> None:
        assert validate_fixture(make_repo(tmp_path)) == []

    def test_missing_key_is_reported(self, tmp_path: Path) -> None:
        state = {**VALID_STATE}
        del state["current_task"]
        assert any("current_task" in v for v in validate_fixture(make_repo(tmp_path, state)))

    def test_wrong_type_is_reported(self, tmp_path: Path) -> None:
        assert any(
            "blocked_tasks" in v for v in validate_fixture(make_repo(tmp_path, {**VALID_STATE, "blocked_tasks": "none"}))
        )

    def test_unknown_task_status_is_reported(self, tmp_path: Path) -> None:
        assert any(
            "lifecycle" in v
            for v in validate_fixture(make_repo(tmp_path, {**VALID_STATE, "task_status": "sorta-done"}))
        )

    def test_unknown_validation_result_is_reported(self, tmp_path: Path) -> None:
        state = {**VALID_STATE, "last_validation": {**VALID_STATE["last_validation"], "lint": "green"}}
        assert any(
            "last_validation.lint" in v for v in validate_fixture(make_repo(tmp_path, state))
        )

    def test_bad_updated_at_is_reported(self, tmp_path: Path) -> None:
        assert any(
            "updated_at" in v
            for v in validate_fixture(make_repo(tmp_path, {**VALID_STATE, "updated_at": "yesterday"}))
        )


class TestTaskReferences:
    def test_current_task_not_in_manifest_is_reported(self, tmp_path: Path) -> None:
        assert any(
            "not found in task manifest" in v
            for v in validate_fixture(make_repo(tmp_path, {**VALID_STATE, "current_task": "TASK-099"}))
        )

    def test_malformed_task_id_is_reported(self, tmp_path: Path) -> None:
        assert any(
            "TASK-NNN" in v
            for v in validate_fixture(make_repo(tmp_path, {**VALID_STATE, "current_task": "task 4"}))
        )

    def test_completed_current_task_is_reported(self, tmp_path: Path) -> None:
        root = make_repo(tmp_path)
        task_file = root / "tasks" / "EPIC-001-foundation" / "TASK-004-fourth.md"
        task_file.write_text("# t\n\n## Status\nCOMPLETED\n", encoding="utf-8")
        assert any("already COMPLETED" in v for v in validate_fixture(root))

    def test_unmet_dependency_is_reported(self, tmp_path: Path) -> None:
        state = {**VALID_STATE, "last_completed_task": "TASK-002"}
        root = make_repo(tmp_path, state)
        task_file = root / "tasks" / "EPIC-001-foundation" / "TASK-003-third.md"
        task_file.write_text("# t\n\n## Status\nREADY\n", encoding="utf-8")
        assert any("dependency TASK-003" in v for v in validate_fixture(root))

    def test_last_completed_not_marked_completed_is_reported(self, tmp_path: Path) -> None:
        root = make_repo(tmp_path)
        task_file = root / "tasks" / "EPIC-001-foundation" / "TASK-003-third.md"
        task_file.write_text("# t\n\n## Status\nREADY\n", encoding="utf-8")
        assert any("last_completed_task" in v for v in validate_fixture(root))

    def test_unknown_epic_is_reported(self, tmp_path: Path) -> None:
        assert any(
            "epic directory not found" in v
            for v in validate_fixture(
                make_repo(tmp_path, {**VALID_STATE, "current_epic": "EPIC-099-nope"})
            )
        )


class TestManifestIntegrity:
    def test_missing_task_file_is_reported(self, tmp_path: Path) -> None:
        root = make_repo(tmp_path)
        (root / "tasks" / "EPIC-001-foundation" / "TASK-004-fourth.md").unlink()
        manifest = project_state.load_manifest(root)
        assert any(
            "task file listed in manifest is missing" in v.render()
            for v in project_state.check_manifest(root, manifest)
        )

    def test_unknown_dependency_is_reported(self, tmp_path: Path) -> None:
        manifest = [
            {
                "id": 4,
                "title": "Fourth",
                "epic": "EPIC-001-foundation",
                "dependencies": [99],
                "path": "EPIC-001-foundation/TASK-004-fourth.md",
            }
        ]
        root = make_repo(tmp_path, manifest=manifest)
        parsed = project_state.load_manifest(root)
        assert any(
            "unknown task: TASK-099" in v.render()
            for v in project_state.check_manifest(root, parsed)
        )

    def test_duplicate_id_is_reported(self, tmp_path: Path) -> None:
        manifest = [
            {
                "id": 4,
                "title": "Fourth",
                "epic": "EPIC-001-foundation",
                "dependencies": [],
                "path": "EPIC-001-foundation/TASK-004-fourth.md",
            },
            {
                "id": 4,
                "title": "Fourth again",
                "epic": "EPIC-001-foundation",
                "dependencies": [],
                "path": "EPIC-001-foundation/TASK-004-fourth.md",
            },
        ]
        root = make_repo(tmp_path, manifest=manifest)
        parsed = project_state.load_manifest(root)
        assert any(
            "duplicate task id" in v.render()
            for v in project_state.check_manifest(root, parsed)
        )


class TestRunner:
    def test_real_repository_passes(self) -> None:
        assert project_state.run_all_checks(REPO_ROOT) == []

    def test_script_exit_code_zero_on_real_repository(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "project_state.py"), "validate"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_script_exit_code_one_on_broken_state(self, tmp_path: Path) -> None:
        root = make_repo(tmp_path, {**VALID_STATE, "current_task": "TASK-099"})
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "project_state.py"), "validate", "--root", str(root)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert "problem" in result.stdout

    def test_missing_state_file_is_reported(self, tmp_path: Path) -> None:
        root = tmp_path / "empty"
        root.mkdir()
        violations = project_state.run_all_checks(root)
        assert any("PROJECT_STATE.json" in v.render() for v in violations)
