"""Docker artifact checks (TASK-117).

The production Docker capability's invariants are structural, so
they are checked statically like the AGENTS.md rules
(``scripts/check_rules.py``): both images multi-stage, non-root,
and healthchecked; the web image carries API_ORIGIN at build AND
runtime (learned live in TASK-111 — the rewrite destination is
baked at build while the server-side fetches read the variable at
``next start``); the compose file wires the two services on one
network with a health-gated dependency and no secrets.

What is intentionally out of scope: image building and container
behavior — those are validated by actually running
``docker compose up --build`` (see docs/PROGRESS.md, TASK-117).

Usage:
    python scripts/check_docker.py
Exit code 0 means no violations; 1 means violations were found.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SECRET_KEYS = ("JWT_SECRET", "API_KEY", "SECRET_KEY", "PASSWORD")


def check_dockerfile(path: Path, runtime_from: str) -> list[str]:
    violations: list[str] = []
    if not path.exists():
        return [f"missing Dockerfile: {path.relative_to(ROOT)}"]
    text = path.read_text(encoding="utf-8")

    stages = re.findall(r"^FROM \S+ AS (\S+)", text, re.M)
    if len(stages) < 2 or "builder" not in stages or "runtime" not in stages:
        violations.append(
            f"{path.name}: expected a multi-stage build (builder -> runtime),"
            f" found stages {stages}"
        )
    if f"FROM {runtime_from} AS runtime" not in text:
        violations.append(
            f"{path.name}: runtime stage must run on {runtime_from}"
        )
    if not re.search(r"^USER (?!root\b)\S+", text, re.M):
        violations.append(f"{path.name}: the container must run non-root")
    if "HEALTHCHECK" not in text:
        violations.append(
            f"{path.name}: the image carries its own HEALTHCHECK"
            " (docs/14: deploy → smoke test → health check)"
        )
    return violations


def check_dockerignore(path: Path, must_exclude: tuple[str, ...]) -> list[str]:
    violations: list[str] = []
    if not path.exists():
        return [f"missing .dockerignore: {path.relative_to(ROOT)}"]
    entries = {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    for pattern in must_exclude:
        if pattern not in entries:
            violations.append(
                f"{path.name}: must exclude {pattern}"
            )
    return violations


def check_compose(path: Path) -> list[str]:
    violations: list[str] = []
    if not path.exists():
        return [f"missing compose file: {path.relative_to(ROOT)}"]
    text = path.read_text(encoding="utf-8")

    for key in SECRET_KEYS:
        if re.search(rf"{key}\s*[:=]", text):
            violations.append(
                "docker-compose.yml: secrets never live in compose files"
                f" (found {key})"
            )

    try:
        import yaml

        compose = yaml.safe_load(text)
    except ImportError:
        compose = None
    if not isinstance(compose, dict) or not isinstance(
        compose.get("services"), dict
    ):
        return violations + ["docker-compose.yml: unparseable or no services"]

    services = compose["services"]
    web = services.get("web")
    if not isinstance(web, dict):
        return violations + ["docker-compose.yml: no web service"]

    build = web.get("build")
    build_origin = None
    if isinstance(build, dict) and isinstance(build.get("args"), dict):
        build_origin = build["args"].get("API_ORIGIN")
    if build_origin is None:
        violations.append(
            "docker-compose.yml: the web build must receive API_ORIGIN"
            " (the rewrite destination is baked at build time)"
        )

    environment = web.get("environment")
    runtime_origin = None
    if isinstance(environment, dict):
        runtime_origin = environment.get("API_ORIGIN")
    if runtime_origin is None:
        violations.append(
            "docker-compose.yml: the web runtime must set API_ORIGIN"
            " (the server-side fetches read it at next start)"
        )

    if build_origin is not None and runtime_origin is not None:
        if build_origin != runtime_origin:
            violations.append(
                "docker-compose.yml: the web build arg and runtime env for"
                " API_ORIGIN must agree — a split origin serves half the"
                " traffic the wrong backend"
            )
        if not str(build_origin).startswith("http://api:"):
            violations.append(
                "docker-compose.yml: the web origin must target the api"
                " service on the compose network"
            )

    depends = web.get("depends_on")
    healthy_gate = (
        isinstance(depends, dict)
        and isinstance(depends.get("api"), dict)
        and depends["api"].get("condition") == "service_healthy"
    )
    if not healthy_gate:
        violations.append(
            "docker-compose.yml: web must wait on the api health check"
        )
    return violations


def main() -> int:
    violations: list[str] = []
    api = ROOT / "apps" / "api"
    web = ROOT / "apps" / "web"

    violations += check_dockerfile(api / "Dockerfile", "python:3.12-slim")
    violations += check_dockerfile(web / "Dockerfile", "node:22-alpine")
    violations += check_dockerignore(
        api / ".dockerignore",
        ("__pycache__/", "venv/", ".pytest_cache/", "evals/"),
    )
    violations += check_dockerignore(
        web / ".dockerignore",
        ("node_modules/", ".next/"),
    )
    violations += check_compose(ROOT / "docker-compose.yml")

    web_dockerfile = (web / "Dockerfile").read_text(encoding="utf-8")
    if "ARG API_ORIGIN" not in web_dockerfile:
        violations.append("apps/web/Dockerfile: build must take API_ORIGIN")
    if not re.search(r"^ENV API_ORIGIN=", web_dockerfile, re.M):
        violations.append(
            "apps/web/Dockerfile: runtime must default API_ORIGIN"
        )

    if violations:
        print("docker artifact checks failed:")
        for violation in violations:
            print(f"  - {violation}")
        return 1
    print("docker artifact checks: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
