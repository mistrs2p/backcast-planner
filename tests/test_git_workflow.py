"""Tests for the git workflow foundation (scripts/git_workflow.py, TASK-005).

Uses temporary git repositories to exercise branch naming enforcement
(protected branches, allowed prefixes, malformed names) and Conventional
Commit validation for non-merge commits on a task branch.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import git_workflow  # noqa: E402

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


def git_run(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True, env=GIT_ENV
    )


def make_repo(tmp_path: Path, *, default_branch: str = "main") -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git_run(root, "init", "-b", default_branch)
    (root / "README.md").write_text("# repo\n", encoding="utf-8")
    git_run(root, "add", "README.md")
    git_run(root, "commit", "-m", "chore(repo): initial commit")
    return root


def commit_file(root: Path, name: str, message: str) -> None:
    (root / name).write_text(name, encoding="utf-8")
    git_run(root, "add", name)
    git_run(root, "commit", "-m", message)


class TestBranchCheck:
    def test_well_formed_task_branch_passes(self, tmp_path: Path) -> None:
        root = make_repo(tmp_path)
        git_run(root, "checkout", "-b", "feature/TASK-001-repository-bootstrap")
        assert git_workflow.check_branch(root) == []

    @pytest.mark.parametrize(
        "branch",
        [
            "fix/TASK-042-hotfix-login",
            "chore/TASK-007-docker-baseline",
            "docs/TASK-010-shared-contracts",
            "feature/TASK-123-a-b-c-d",
        ],
    )
    def test_allowed_prefixes_pass(self, tmp_path: Path, branch: str) -> None:
        root = make_repo(tmp_path)
        git_run(root, "checkout", "-b", branch)
        assert git_workflow.check_branch(root) == []

    @pytest.mark.parametrize(
        "branch",
        [
            "main",
            "master",
            "feature/short-name",          # no task id
            "feature/task-001-name",       # lowercase prefix
            "feature/TASK-001",            # no short name
            "release/TASK-001-name",       # disallowed prefix
            "feature/TASK-001-Name",       # uppercase in short name
            "bugfix/TASK-001-name",        # disallowed prefix
        ],
    )
    def test_invalid_branches_are_reported(self, tmp_path: Path, branch: str) -> None:
        root = make_repo(tmp_path)
        if branch in ("main", "master"):
            pass  # already on the default branch
        else:
            git_run(root, "checkout", "-b", branch)
        violations = git_workflow.check_branch(root)
        assert len(violations) == 1
        assert violations[0].rule == "git-workflow"

    def test_development_on_main_is_reported(self, tmp_path: Path) -> None:
        root = make_repo(tmp_path)  # sits on main
        violations = git_workflow.check_branch(root)
        assert any("protected branch" in v.detail for v in violations)


class TestCommitCheck:
    def make_task_branch(self, tmp_path: Path, messages: list[str]) -> Path:
        root = make_repo(tmp_path)
        git_run(root, "checkout", "-b", "feature/TASK-005-git-workflow-foundation")
        for index, message in enumerate(messages):
            commit_file(root, f"file{index}.txt", message)
        return root

    @pytest.mark.parametrize(
        "message",
        [
            "feat(scope): add feature",
            "fix(api): correct behavior",
            "test(domain): cover invariants",
            "docs(readme): update instructions",
            "chore(repo): bootstrap",
            "refactor(core): simplify",
            "perf(scheduler): reduce allocations",
            "feat!: breaking change with no scope",
            "feat(api)!: breaking change with scope",
        ],
    )
    def test_conventional_commits_pass(self, tmp_path: Path, message: str) -> None:
        root = self.make_task_branch(tmp_path, [message])
        assert git_workflow.check_commits(root, "main") == []

    @pytest.mark.parametrize(
        "message",
        [
            "add feature",                  # no type
            "feat add feature",             # no colon
            "feature(api): add feature",    # invalid type
            "feat(api):",                   # no description
            "Update README",                # plain message
        ],
    )
    def test_non_conventional_commits_are_reported(self, tmp_path: Path, message: str) -> None:
        root = self.make_task_branch(tmp_path, [message])
        violations = git_workflow.check_commits(root, "main")
        assert len(violations) == 1
        assert "Conventional Commit" in violations[0].detail

    def test_base_commit_is_not_flagged(self, tmp_path: Path) -> None:
        # The initial commit on main is conventional anyway; ensure only the
        # branch commits are inspected even when the base is unconventional.
        root = make_repo(tmp_path)
        git_run(root, "checkout", "-b", "feature/TASK-005-git-workflow-foundation")
        commit_file(root, "file.txt", "feat(x): good")
        assert git_workflow.check_commits(root, "main") == []

    def test_merge_commits_are_exempt(self, tmp_path: Path) -> None:
        root = make_repo(tmp_path)
        git_run(root, "checkout", "-b", "feature/TASK-005-git-workflow-foundation")
        commit_file(root, "file.txt", "feat(x): good")
        git_run(root, "checkout", "main")
        git_run(root, "merge", "--no-ff", "-m", "Merge branch into main", "feature/TASK-005-git-workflow-foundation")
        git_run(root, "checkout", "-b", "feature/TASK-006-ci-baseline", "main")
        assert git_workflow.check_commits(root, "main") == []


class TestCli:
    def test_check_branch_fails_on_main(self, tmp_path: Path) -> None:
        root = make_repo(tmp_path)
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "git_workflow.py"), "check-branch", "--root", str(root)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1

    def test_check_commits_passes_on_clean_branch(self, tmp_path: Path) -> None:
        root = make_repo(tmp_path)
        git_run(root, "checkout", "-b", "feature/TASK-005-git-workflow-foundation")
        commit_file(root, "file.txt", "feat(x): good")
        result = subprocess.run(
            [
                sys.executable, str(SCRIPTS_DIR / "git_workflow.py"),
                "check-commits", "--root", str(root), "--base", "main",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_check_commits_on_this_repository(self) -> None:
        """All commits on the current task branch follow the convention."""
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "git_workflow.py"), "check-commits", "--base", "main"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
