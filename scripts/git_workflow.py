"""Git workflow foundation: branch naming and commit message enforcement.

AGENTS.md §9 defines the repository's git rules. This module enforces the
statically checkable parts:

- Development happens on task branches, never directly on ``main``.
- Branch naming: ``feature/TASK-###-short-name``, ``fix/...``, ``chore/...``,
  ``docs/...``.
- Commit messages follow Conventional Commit style:
  ``type(scope): description`` with type in
  feat/fix/test/docs/chore/refactor/perf. Merge commits are exempt.

Usage:
    python scripts/git_workflow.py check-branch [ROOT]
    python scripts/git_workflow.py check-commits [ROOT] [--base REF]
Exit code 0 when the workflow rules hold; 1 when violations are found.
Requires git; repositories without git report a single violation instead of
failing silently.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from check_rules import Violation

PROTECTED_BRANCHES = {"main", "master"}

# Branch prefixes defined in AGENTS.md §9.
BRANCH_NAME_PATTERN = re.compile(
    r"^(feature|fix|chore|docs)/TASK-\d{1,3}-[a-z0-9]+(-[a-z0-9]+)*$"
)

# Conventional Commit types listed in AGENTS.md §9.
CONVENTIONAL_COMMIT_PATTERN = re.compile(
    r"^(feat|fix|test|docs|chore|refactor|perf)(\([a-z0-9._/-]+\))?!?: .+"
)


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    )
    return result.stdout


def current_branch(root: Path) -> str | None:
    try:
        branch = git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return branch or None


def check_branch(root: Path) -> list[Violation]:
    """Current branch must be a properly named task branch, not protected."""
    branch = current_branch(root)
    if branch is None:
        return [Violation("git-workflow", "HEAD", "not on a git branch (or git unavailable)")]
    if branch in PROTECTED_BRANCHES:
        return [
            Violation(
                "git-workflow",
                branch,
                "developing directly on a protected branch is forbidden (AGENTS.md §9)",
            )
        ]
    if branch == "HEAD":
        return [Violation("git-workflow", "HEAD", "detached HEAD has no branch name")]
    if not BRANCH_NAME_PATTERN.match(branch):
        return [
            Violation(
                "git-workflow",
                branch,
                "branch name must be feature|fix|chore|docs/TASK-###-short-name",
            )
        ]
    return []


def commits_on_branch(root: Path, base: str) -> list[str]:
    """Commit hashes on the current branch that are not on ``base``."""
    try:
        merge_base = git(root, "merge-base", base, "HEAD").strip()
    except subprocess.CalledProcessError:
        # Base ref unknown (e.g. no main yet); fall back to all commits.
        output = git(root, "rev-list", "--reverse", "HEAD")
        return output.split()

    output = git(root, "rev-list", "--reverse", f"{merge_base}..HEAD")
    return output.split()


def check_commits(root: Path, base: str) -> list[Violation]:
    """Every non-merge commit on the branch must use Conventional Commit style."""
    violations: list[Violation] = []
    try:
        hashes = commits_on_branch(root, base)
    except (OSError, subprocess.CalledProcessError) as exc:
        return [Violation("git-workflow", "git", f"cannot inspect commit history: {exc}")]

    for commit_hash in hashes:
        message = git(root, "log", "-1", "--format=%s", commit_hash).strip()
        if message.startswith("Merge "):
            continue  # merge commits are exempt
        if not CONVENTIONAL_COMMIT_PATTERN.match(message):
            violations.append(
                Violation(
                    "git-workflow",
                    f"{commit_hash[:10]} {message!r}",
                    "commit message is not Conventional Commit style "
                    "(type(scope): description)",
                )
            )
    return violations


def default_base(root: Path) -> str:
    """Prefer origin/main, then local main; 'HEAD~20' as a last resort."""
    for ref in ("origin/main", "main"):
        try:
            git(root, "rev-parse", "--verify", ref)
            return ref
        except subprocess.CalledProcessError:
            continue
    return "HEAD~20"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "command", choices=["check-branch", "check-commits"], help="command to run"
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--base",
        help="base ref for check-commits (default: origin/main, then main)",
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    if args.command == "check-branch":
        violations = check_branch(root)
        label = "Branch check"
    else:
        base = args.base or default_base(root)
        violations = check_commits(root, base)
        label = f"Commit check (base {base})"

    if violations:
        print(f"{label}: {len(violations)} violation(s)")
        for violation in violations:
            print(f"  {violation.render()}")
        return 1
    print(f"{label}: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
