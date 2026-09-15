"""PROJECT_STATE.json foundation: schema validation and task-graph consistency.

`PROJECT_STATE.json` is the compact source of truth for execution state
(AGENTS.md §2, §13). This module keeps it honest:

- Schema: required keys, types, and lifecycle enums.
- Consistency with `tasks/TASK-MANIFEST.json`: referenced tasks exist, task
  files exist, and dependency edges point at known tasks.
- Consistency with the task files themselves: the current task is not already
  COMPLETED, the last completed task is really marked COMPLETED, and every
  dependency of the current task is COMPLETED before work may start
  (AGENTS.md §8.2, §14).

Usage:
    python scripts/project_state.py validate [ROOT]
Exit code 0 means the state is valid; 1 means problems were found.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from check_rules import Violation

TASK_ID_PATTERN = re.compile(r"^TASK-(\d{3,})$")

# Lifecycle states from tasks/README.md (lowercased in PROJECT_STATE.json).
ALLOWED_TASK_STATUSES = {
    "draft",
    "ready",
    "in_progress",
    "validating",
    "completed",
    "blocked",
    "failed",
    "cancelled",
}

ALLOWED_VALIDATION_RESULTS = {
    "not_run",
    "not_applicable",
    "pass",
    "fail",
    "skipped",
}

REQUIRED_STATE_KEYS = {
    "project": str,
    "phase": str,
    "current_epic": str,
    "current_task": str,
    "last_completed_task": (str, type(None)),
    "task_status": str,
    "blocked_tasks": list,
    "open_bugs": list,
    "active_branch": (str, type(None)),
    "last_validation": dict,
    "technology_baseline": dict,
    "updated_at": (str, type(None)),
}

REQUIRED_VALIDATION_KEYS = ("tests", "lint", "typecheck", "build")

STATUS_HEADING = "## Status"


@dataclass
class TaskManifestEntry:
    task_id: str
    title: str
    epic: str
    dependencies: list[str]
    path: str


def load_manifest(root: Path) -> list[TaskManifestEntry]:
    manifest_path = root / "tasks" / "TASK-MANIFEST.json"
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    return [
        TaskManifestEntry(
            task_id=f"TASK-{entry['id']:03d}",
            title=entry["title"],
            epic=entry["epic"],
            dependencies=[f"TASK-{dep:03d}" for dep in entry.get("dependencies", [])],
            path=entry["path"],
        )
        for entry in raw
    ]


def task_file_status(root: Path, entry: TaskManifestEntry) -> str | None:
    """Status line value from a task file's `## Status` heading, if parseable."""
    task_file = root / "tasks" / entry.path
    if not task_file.is_file():
        return None
    lines = task_file.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if line.strip() == STATUS_HEADING:
            for following in lines[index + 1 :]:
                stripped = following.strip()
                if stripped:
                    return stripped
    return None


def check_manifest(root: Path, manifest: list[TaskManifestEntry]) -> list[Violation]:
    """The task manifest itself must be internally consistent."""
    violations: list[Violation] = []
    seen_ids: set[str] = set()
    for entry in manifest:
        if entry.task_id in seen_ids:
            violations.append(
                Violation("manifest", entry.task_id, "duplicate task id")
            )
        seen_ids.add(entry.task_id)
        task_file = root / "tasks" / entry.path
        if not task_file.is_file():
            violations.append(
                Violation("manifest", entry.path, "task file listed in manifest is missing")
            )
        if not (root / "tasks" / entry.epic).is_dir():
            violations.append(
                Violation("manifest", entry.task_id, f"unknown epic directory: {entry.epic}")
            )
        for dep in entry.dependencies:
            if dep not in {other.task_id for other in manifest}:
                violations.append(
                    Violation("manifest", entry.task_id, f"dependency on unknown task: {dep}")
                )
    return violations


def _check_schema(state: dict) -> list[Violation]:
    violations: list[Violation] = []
    for key, expected_type in REQUIRED_STATE_KEYS.items():
        if key not in state:
            violations.append(Violation("state", key, "required key missing"))
        elif not isinstance(state[key], expected_type):
            violations.append(
                Violation(
                    "state",
                    key,
                    f"expected {getattr(expected_type, '__name__', str(expected_type))}, "
                    f"got {type(state[key]).__name__}",
                )
            )
    if isinstance(state.get("task_status"), str) and state["task_status"] not in ALLOWED_TASK_STATUSES:
        violations.append(
            Violation(
                "state",
                "task_status",
                f"{state['task_status']!r} is not a task lifecycle state "
                f"({', '.join(sorted(ALLOWED_TASK_STATUSES))})",
            )
        )
    last_validation = state.get("last_validation")
    if isinstance(last_validation, dict):
        for key in REQUIRED_VALIDATION_KEYS:
            value = last_validation.get(key)
            if value is None:
                violations.append(Violation("state", f"last_validation.{key}", "key missing"))
            elif value not in ALLOWED_VALIDATION_RESULTS:
                violations.append(
                    Violation(
                        "state",
                        f"last_validation.{key}",
                        f"{value!r} is not a validation result",
                    )
                )
    updated_at = state.get("updated_at")
    if isinstance(updated_at, str):
        try:
            date.fromisoformat(updated_at)
        except ValueError:
            violations.append(
                Violation("state", "updated_at", f"{updated_at!r} is not an ISO date (YYYY-MM-DD)")
            )
    return violations


def _check_task_references(
    state: dict, root: Path, manifest: list[TaskManifestEntry]
) -> list[Violation]:
    violations: list[Violation] = []
    by_id = {entry.task_id: entry for entry in manifest}

    for key in ("current_task", "last_completed_task"):
        value = state.get(key)
        if isinstance(value, str):
            if not TASK_ID_PATTERN.match(value):
                violations.append(
                    Violation("state", key, f"{value!r} is not a TASK-NNN identifier")
                )
            elif value not in by_id:
                violations.append(Violation("state", key, f"{value} not found in task manifest"))

    current_task = state.get("current_task")
    if isinstance(current_task, str) and current_task in by_id:
        entry = by_id[current_task]
        status = task_file_status(root, entry)
        if status is None:
            violations.append(
                Violation("state", "current_task", f"{current_task} file has no parseable status")
            )
        elif status.lower() == "completed":
            violations.append(
                Violation(
                    "state",
                    "current_task",
                    f"{current_task} is already COMPLETED; advance current_task",
                )
            )
        for dep in entry.dependencies:
            dep_status = task_file_status(root, by_id[dep]) if dep in by_id else None
            if dep_status is None or dep_status.lower() != "completed":
                violations.append(
                    Violation(
                        "state",
                        "current_task",
                        f"dependency {dep} is not COMPLETED (status: {dep_status!r})",
                    )
                )

    last_completed = state.get("last_completed_task")
    if isinstance(last_completed, str) and last_completed in by_id:
        status = task_file_status(root, by_id[last_completed])
        if status is None or status.lower() != "completed":
            violations.append(
                Violation(
                    "state",
                    "last_completed_task",
                    f"{last_completed} is not marked COMPLETED in its task file "
                    f"(status: {status!r})",
                )
            )

    current_epic = state.get("current_epic")
    if isinstance(current_epic, str) and not (root / "tasks" / current_epic).is_dir():
        violations.append(
            Violation("state", "current_epic", f"epic directory not found under tasks/: {current_epic}")
        )
    return violations


def validate_state(state: dict, root: Path, manifest: list[TaskManifestEntry]) -> list[Violation]:
    return [*_check_schema(state), *_check_task_references(state, root, manifest)]


def run_all_checks(root: Path) -> list[Violation]:
    state_path = root / "PROJECT_STATE.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [Violation("state", "PROJECT_STATE.json", "file is missing")]
    except json.JSONDecodeError as exc:
        return [Violation("state", "PROJECT_STATE.json", f"invalid JSON: {exc}")]
    if not isinstance(state, dict):
        return [Violation("state", "PROJECT_STATE.json", "top-level value must be an object")]

    try:
        manifest = load_manifest(root)
    except FileNotFoundError:
        return [Violation("manifest", "tasks/TASK-MANIFEST.json", "file is missing")]
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        return [Violation("manifest", "tasks/TASK-MANIFEST.json", f"cannot parse manifest: {exc}")]

    return [*check_manifest(root, manifest), *validate_state(state, root, manifest)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["validate"], help="command to run")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)

    root = args.root.resolve()
    violations = run_all_checks(root)
    if violations:
        print(f"PROJECT_STATE validation: {len(violations)} problem(s)")
        for violation in violations:
            print(f"  {violation.render()}")
        return 1
    print("PROJECT_STATE validation: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
