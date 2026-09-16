"""CI workflow checks (TASK-118).

The CI/CD capability's invariants are structural, so they are
checked statically like the other repository validators
(``scripts/check_rules.py``, ``scripts/check_docker.py``): every
AGENTS.md validation gate must run in CI — the backend suite and
repository validators, the web verify/build gates, and a Docker
image build (docs/14's pipeline: validate -> build -> ...). A gate
that quietly disappears from the workflow is a hole in the pipeline
that nothing else catches, so the workflow is pinned the same way
the Docker artifacts are.

What is intentionally out of scope: whether the workflow *passes*
on GitHub — that is validated by the runs themselves, the same way
image behavior is validated by ``docker compose up --build`` rather
than by scripts/check_docker.py.

Usage:
    python scripts/check_ci.py
Exit code 0 means no violations; 1 means violations were found.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

SECRET_KEYS = ("JWT_SECRET", "API_KEY", "SECRET_KEY", "PASSWORD")

# The commands each job must run. Substring match against the
# concatenation of the job's step `run` values.
VALIDATE_COMMANDS = (
    "python -m pytest",
    "python scripts/generate_contracts.py --check",
    "python scripts/check_rules.py",
    "python scripts/project_state.py validate",
    "python scripts/progress.py check",
    "python scripts/check_docker.py",
    "python scripts/check_ci.py",
)
WEB_COMMANDS = ("npm ci", "npm run verify", "npm run build")
DOCKER_COMMANDS = ("docker compose build",)

EXPECTED_JOBS = ("validate", "web", "docker")


def _triggers(workflow: dict) -> dict:
    # PyYAML parses the YAML 1.1 boolean-looking key `on` as True.
    triggers = workflow.get("on")
    if triggers is None:
        triggers = workflow.get(True)
    return triggers if isinstance(triggers, dict) else {}


def _runs_of(job: dict) -> str:
    runs = []
    for step in job.get("steps") or []:
        run = step.get("run")
        if isinstance(run, str):
            runs.append(run)
    return "\n".join(runs)


def _uses_of(job: dict) -> str:
    uses = []
    for step in job.get("steps") or []:
        use = step.get("uses")
        if isinstance(use, str):
            uses.append(use)
    return "\n".join(uses)


def check_workflow(path: Path) -> list[str]:
    violations: list[str] = []
    if not path.exists():
        return [f"missing workflow: {path.relative_to(ROOT)}"]
    text = path.read_text(encoding="utf-8")

    for key in SECRET_KEYS:
        if key in text:
            violations.append(
                f"{path.name}: no credentials in workflows (found {key})"
            )

    try:
        workflow = yaml.safe_load(text)
    except yaml.YAMLError as error:
        return violations + [f"{path.name}: unparseable YAML ({error})"]
    if not isinstance(workflow, dict) or not isinstance(
        workflow.get("jobs"), dict
    ):
        return violations + [f"{path.name}: no jobs"]

    for event in ("push", "pull_request"):
        branches = _triggers(workflow).get(event)
        if not (
            isinstance(branches, dict) and "main" in (branches.get("branches") or [])
        ):
            violations.append(
                f"{path.name}: must trigger on {event} to main"
                " (main is the protected integration branch)"
            )

    jobs = workflow["jobs"]
    for name in EXPECTED_JOBS:
        if not isinstance(jobs.get(name), dict):
            violations.append(f"{path.name}: no {name} job")
    if violations:
        return violations

    commands_by_job = (
        ("validate", VALIDATE_COMMANDS),
        ("web", WEB_COMMANDS),
        ("docker", DOCKER_COMMANDS),
    )
    for job_name, commands in commands_by_job:
        runs = _runs_of(jobs[job_name])
        for command in commands:
            if command not in runs:
                violations.append(
                    f"{path.name}: the {job_name} job must run `{command}`"
                )

    web = jobs["web"]
    if "actions/setup-node" not in _uses_of(web):
        violations.append(
            f"{path.name}: the web job must set up Node explicitly"
            " (the gates run on a pinned toolchain)"
        )
    for step in web.get("steps") or []:
        if step.get("uses") == "actions/setup-node@v4":
            node_version = (step.get("with") or {}).get("node-version")
            if str(node_version) != "22":
                violations.append(
                    f"{path.name}: the web job must pin Node 22"
                    " (apps/web package.json engines floor is 20.9;"
                    " 22 is the version the production image runs)"
                )
    return violations


def main() -> int:
    violations = check_workflow(WORKFLOW)
    if violations:
        print("ci workflow checks failed:")
        for violation in violations:
            print(f"  - {violation}")
        return 1
    print("ci workflow checks: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
