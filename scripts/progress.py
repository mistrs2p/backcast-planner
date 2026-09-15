"""Progress system foundation: backlog reporting and progress-doc consistency.

The repository memory is split across PROJECT_STATE.json (current state),
docs/PROGRESS.md (historical progress), and docs/SESSION-LOG.md (discoveries)
— see AGENTS.md §13. This module provides:

- ``report``: a status overview of the task backlog, aggregated per epic from
  tasks/TASK-MANIFEST.json and each task file's Status heading.
- ``check``: consistency between docs/PROGRESS.md and PROJECT_STATE.json, so
  the human-readable progress view cannot drift from the machine-readable
  state (same current task, same current epic, required sections present).

Usage:
    python scripts/progress.py report [ROOT]
    python scripts/progress.py check  [ROOT]
Exit code 0 on success; 1 when the check reports problems.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

from check_rules import Violation
from project_state import TaskManifestEntry, load_manifest, task_file_status

REQUIRED_PROGRESS_SECTIONS = ["## Current", "## Completed", "## Notes"]

CURRENT_TASK_LINE = re.compile(r"^-\s*Current Task:\s*(.+?)\s*$", re.MULTILINE)
CURRENT_EPIC_LINE = re.compile(r"^-\s*Current Epic:\s*(.+?)\s*$", re.MULTILINE)
# Stable identifiers within free-text lines; PROGRESS.md uses display names
# (e.g. "EPIC-001 Foundation") while PROJECT_STATE.json uses directory ids
# (e.g. "EPIC-001-foundation"), so comparisons use the numbered prefix.
IDENTIFIER_PREFIX = re.compile(r"(EPIC|TASK)-\d+")


def identifier_prefix(value: str) -> str | None:
    match = IDENTIFIER_PREFIX.search(value)
    return match.group(0) if match else None


def collect_statuses(root: Path) -> dict[str, str | None]:
    """Task id -> status parsed from each task file (None when unparsable)."""
    manifest = load_manifest(root)
    return {
        entry.task_id: task_file_status(root, entry) for entry in manifest
    }


def build_report(root: Path) -> dict[str, object]:
    """Per-epic and overall status counts plus the current task pointer."""
    manifest = load_manifest(root)
    statuses = collect_statuses(root)
    by_epic: dict[str, Counter[str]] = {}
    for entry in manifest:
        status = (statuses.get(entry.task_id) or "UNKNOWN").upper()
        by_epic.setdefault(entry.epic, Counter())[status] += 1

    state = json.loads((root / "PROJECT_STATE.json").read_text(encoding="utf-8"))
    overall: Counter[str] = Counter()
    for counter in by_epic.values():
        overall.update(counter)

    return {
        "current_task": state.get("current_task"),
        "current_epic": state.get("current_epic"),
        "last_completed_task": state.get("last_completed_task"),
        "total_tasks": len(manifest),
        "overall": dict(sorted(overall.items())),
        "epics": {
            epic: dict(sorted(counter.items())) for epic, counter in sorted(by_epic.items())
        },
    }


def render_report(report: dict[str, object]) -> str:
    lines = [
        "Progress report",
        "===============",
        f"Current task: {report['current_task']} (epic {report['current_epic']})",
        f"Last completed: {report['last_completed_task']}",
        f"Tasks: {report['total_tasks']}",
        f"Overall: {report['overall']}",
        "",
        "Per epic:",
    ]
    for epic, counts in report["epics"].items():
        parts = ", ".join(f"{status}={count}" for status, count in counts.items())
        lines.append(f"  {epic}: {parts}")
    return "\n".join(lines)


def check_progress_docs(root: Path) -> list[Violation]:
    """docs/PROGRESS.md must track PROJECT_STATE.json and keep its sections."""
    violations: list[Violation] = []
    progress_md = root / "docs" / "PROGRESS.md"
    session_log = root / "docs" / "SESSION-LOG.md"
    if not progress_md.is_file():
        return [Violation("progress", "docs/PROGRESS.md", "file is missing")]
    if not session_log.is_file():
        violations.append(Violation("progress", "docs/SESSION-LOG.md", "file is missing"))

    content = progress_md.read_text(encoding="utf-8")
    for section in REQUIRED_PROGRESS_SECTIONS:
        if section not in content:
            violations.append(
                Violation("progress", "docs/PROGRESS.md", f"required section missing: {section!r}")
            )

    try:
        state = json.loads((root / "PROJECT_STATE.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return violations  # state problems are reported by project_state.py

    current_task = state.get("current_task")
    task_match = CURRENT_TASK_LINE.search(content)
    if isinstance(current_task, str):
        if task_match is None:
            violations.append(
                Violation(
                    "progress",
                    "docs/PROGRESS.md",
                    "'Current Task' line missing from the Current section",
                )
            )
        elif identifier_prefix(task_match.group(1)) != identifier_prefix(current_task):
            violations.append(
                Violation(
                    "progress",
                    "docs/PROGRESS.md",
                    f"Current Task line is {task_match.group(1)!r} but PROJECT_STATE "
                    f"says {current_task}",
                )
            )

    current_epic = state.get("current_epic")
    epic_match = CURRENT_EPIC_LINE.search(content)
    if isinstance(current_epic, str):
        if epic_match is None:
            violations.append(
                Violation(
                    "progress",
                    "docs/PROGRESS.md",
                    "'Current Epic' line missing from the Current section",
                )
            )
        elif identifier_prefix(epic_match.group(1)) != identifier_prefix(current_epic):
            violations.append(
                Violation(
                    "progress",
                    "docs/PROGRESS.md",
                    f"Current Epic line is {epic_match.group(1)!r} but PROJECT_STATE "
                    f"says {current_epic}",
                )
            )
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["report", "check"], help="command to run")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)

    root = args.root.resolve()
    if args.command == "report":
        print(render_report(build_report(root)))
        return 0

    violations = check_progress_docs(root)
    if violations:
        print(f"Progress docs check: {len(violations)} problem(s)")
        for violation in violations:
            print(f"  {violation.render()}")
        return 1
    print("Progress docs check: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
