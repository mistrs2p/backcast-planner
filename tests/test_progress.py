"""Tests for the progress system foundation (scripts/progress.py, TASK-004).

Covers backlog reporting (per-epic status aggregation from task files) and the
consistency rules that keep docs/PROGRESS.md synchronized with
PROJECT_STATE.json: matching current task/epic and required sections.
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

import progress  # noqa: E402

STATE: dict[str, Any] = {
    "project": "backcasting-planner",
    "phase": "implementation",
    "current_epic": "EPIC-001-foundation",
    "current_task": "TASK-002",
    "last_completed_task": "TASK-001",
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
    "technology_baseline": {},
    "updated_at": "2026-09-15",
}

PROGRESS_MD = """# Project Progress

## Current
- Phase: Implementation
- Current Task: TASK-002 (Second thing)
- Current Epic: EPIC-001 Foundation

## Completed
- TASK-001 done.

## Notes
- This file is historical.
"""

MANIFEST = [
    {
        "id": 1,
        "title": "First",
        "epic": "EPIC-001-foundation",
        "dependencies": [],
        "path": "EPIC-001-foundation/TASK-001-first.md",
    },
    {
        "id": 2,
        "title": "Second thing",
        "epic": "EPIC-001-foundation",
        "dependencies": [1],
        "path": "EPIC-001-foundation/TASK-002-second.md",
    },
    {
        "id": 3,
        "title": "Other",
        "epic": "EPIC-002-other",
        "dependencies": [],
        "path": "EPIC-002-other/TASK-003-other.md",
    },
]


def make_repo(tmp_path: Path, *, progress_md: str = PROGRESS_MD) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "PROJECT_STATE.json").write_text(json.dumps(STATE), encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "PROGRESS.md").write_text(progress_md, encoding="utf-8")
    (root / "docs" / "SESSION-LOG.md").write_text("# Session Log\n", encoding="utf-8")
    (root / "tasks").mkdir()
    (root / "tasks" / "TASK-MANIFEST.json").write_text(json.dumps(MANIFEST), encoding="utf-8")

    statuses = {
        "EPIC-001-foundation/TASK-001-first.md": "COMPLETED",
        "EPIC-001-foundation/TASK-002-second.md": "READY",
        "EPIC-002-other/TASK-003-other.md": "DRAFT",
    }
    for path, status in statuses.items():
        task_file = root / "tasks" / path
        task_file.parent.mkdir(parents=True, exist_ok=True)
        task_file.write_text(f"# {path}\n\n## Status\n{status}\n", encoding="utf-8")
    return root


class TestReport:
    def test_report_aggregates_statuses_per_epic(self, tmp_path: Path) -> None:
        report = progress.build_report(make_repo(tmp_path))
        assert report["total_tasks"] == 3
        assert report["overall"] == {"COMPLETED": 1, "DRAFT": 1, "READY": 1}
        assert report["epics"]["EPIC-001-foundation"] == {"COMPLETED": 1, "READY": 1}
        assert report["epics"]["EPIC-002-other"] == {"DRAFT": 1}

    def test_report_reflects_current_state_pointers(self, tmp_path: Path) -> None:
        report = progress.build_report(make_repo(tmp_path))
        assert report["current_task"] == "TASK-002"
        assert report["last_completed_task"] == "TASK-001"

    def test_unparsable_task_counts_as_unknown(self, tmp_path: Path) -> None:
        root = make_repo(tmp_path)
        (root / "tasks" / "EPIC-002-other" / "TASK-003-other.md").write_text(
            "# no status heading\n", encoding="utf-8"
        )
        report = progress.build_report(root)
        assert report["overall"].get("UNKNOWN") == 1

    def test_rendered_report_contains_epic_lines(self, tmp_path: Path) -> None:
        rendered = progress.render_report(progress.build_report(make_repo(tmp_path)))
        assert "EPIC-001-foundation: COMPLETED=1, READY=1" in rendered
        assert "Current task: TASK-002" in rendered

    def test_real_repository_report_runs(self) -> None:
        report = progress.build_report(REPO_ROOT)
        assert report["total_tasks"] == 134
        assert report["overall"].get("COMPLETED", 0) >= 3


class TestProgressDocsCheck:
    def test_consistent_repo_passes(self, tmp_path: Path) -> None:
        assert progress.check_progress_docs(make_repo(tmp_path)) == []

    def test_real_repository_passes(self) -> None:
        assert progress.check_progress_docs(REPO_ROOT) == []

    def test_stale_current_task_is_reported(self, tmp_path: Path) -> None:
        stale = PROGRESS_MD.replace("TASK-002 (Second thing)", "TASK-001 (First)")
        violations = progress.check_progress_docs(make_repo(tmp_path, progress_md=stale))
        assert any("Current Task" in v.detail for v in violations)

    def test_missing_current_task_line_is_reported(self, tmp_path: Path) -> None:
        stale = PROGRESS_MD.replace("- Current Task: TASK-002 (Second thing)\n", "")
        violations = progress.check_progress_docs(make_repo(tmp_path, progress_md=stale))
        assert any("Current Task" in v.detail for v in violations)

    def test_stale_current_epic_is_reported(self, tmp_path: Path) -> None:
        stale = PROGRESS_MD.replace("EPIC-001 Foundation", "EPIC-009 Whatever")
        violations = progress.check_progress_docs(make_repo(tmp_path, progress_md=stale))
        assert any("Current Epic" in v.detail for v in violations)

    def test_missing_section_is_reported(self, tmp_path: Path) -> None:
        stale = PROGRESS_MD.replace("## Notes\n- This file is historical.\n", "")
        violations = progress.check_progress_docs(make_repo(tmp_path, progress_md=stale))
        assert any("## Notes" in v.detail for v in violations)

    def test_missing_session_log_is_reported(self, tmp_path: Path) -> None:
        root = make_repo(tmp_path)
        (root / "docs" / "SESSION-LOG.md").unlink()
        violations = progress.check_progress_docs(root)
        assert any("SESSION-LOG" in v.location for v in violations)


class TestCli:
    def test_report_command_succeeds_on_real_repository(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "progress.py"), "report"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "Progress report" in result.stdout

    def test_check_command_succeeds_on_real_repository(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "progress.py"), "check"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_check_command_fails_on_stale_progress_md(self, tmp_path: Path) -> None:
        stale = PROGRESS_MD.replace("TASK-002 (Second thing)", "TASK-001 (First)")
        root = make_repo(tmp_path, progress_md=stale)
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "progress.py"), "check", "--root", str(root)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert "problem" in result.stdout
