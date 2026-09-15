"""AGENTS.md rule enforcement for the backcasting-planner repository.

Machine-checkable rules enforced here (see AGENTS.md):

- AGENTS.md exists and keeps its required rule sections (§2 source of truth).
- Secret files are never tracked by git; ``.env.example`` holds only
  placeholder values (§7, §16).
- The domain layer stays framework/vendor independent: Python files under any
  ``domain`` directory inside ``apps/api`` must not import FastAPI, SQLAlchemy,
  Redis, task-queue libraries, vendor LLM SDKs, or web/UI frameworks (§4).

Rules that require human or runtime judgment (task ordering, test integrity,
migration review) are not statically checkable and are intentionally out of
scope for this script.

Usage:
    python scripts/check_rules.py            # check the repository
    python scripts/check_rules.py --root PATH
Exit code 0 means no violations; 1 means violations were found.
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REQUIRED_AGENTS_SECTIONS = [
    "## 1. Mission",
    "## 2. Source of Truth",
    "## 4. Architecture Rules",
    "## 5. AI Rules",
    "## 7. Engineering Rules",
    "## 16. Forbidden Behaviors",
]

# Modules the domain layer must never import (AGENTS.md §4). Keyed by the
# top-level package name an import statement would use.
FORBIDDEN_DOMAIN_IMPORTS = {
    # Web frameworks / presentation
    "fastapi": "FastAPI (web framework)",
    "flask": "web framework",
    "django": "web framework",
    "starlette": "web framework",
    # Persistence / infrastructure
    "sqlalchemy": "SQLAlchemy (ORM)",
    "alembic": "Alembic (migrations)",
    "redis": "Redis client",
    "celery": "task queue",
    "dramatiq": "task queue",
    "rq": "task queue",
    # Vendor LLM SDKs
    "openai": "vendor LLM SDK",
    "anthropic": "vendor LLM SDK",
    "litellm": "vendor LLM SDK",
    "cohere": "vendor LLM SDK",
    "mistralai": "vendor LLM SDK",
    # UI tooling (defensive; the domain is Python-only)
    "streamlit": "UI library",
    "gradio": "UI library",
}

# Substrings that make a google.* import an LLM SDK import rather than an
# unrelated Google library.
GOOGLE_LLM_SUBMODULES = ("generativeai", "genai", "cloud.aiplatform")

SECRET_FILE_PATTERNS = (".env",)
SECRET_FILE_SUFFIXES = (".pem", ".key", ".p12", ".pfx")
TRACKED_SECRET_ALLOWLIST = {".env.example"}

# Keys whose values are credentials and must be placeholders in .env.example.
SECRET_KEY_PATTERN = re.compile(r"(SECRET|PASSWORD|PASSWD|TOKEN|API_KEY|PRIVATE_KEY)", re.I)
PLACEHOLDER_VALUE = re.compile(r"^(replace-me|change-me|your-[\w.-]*|example-[\w.-]*|test-[\w.-]*|<[^>]+>|\*+|)$")
# user:password@host in a DSN, where the host is not local.
NON_LOCAL_CREDENTIALS = re.compile(
    r"://[^/@:\s]+:(?!/@)[^/@\s]+@(?!localhost|127\.0\.0\.1|\[::1\])"
)


@dataclass(frozen=True)
class Violation:
    rule: str
    location: str
    detail: str

    def render(self) -> str:
        return f"[{self.rule}] {self.location}: {self.detail}"


def check_agents_md(root: Path) -> list[Violation]:
    """AGENTS.md must exist and keep its required rule sections."""
    violations: list[Violation] = []
    agents_md = root / "AGENTS.md"
    if not agents_md.is_file():
        return [Violation("agents-md", "AGENTS.md", "file is missing")]
    content = agents_md.read_text(encoding="utf-8")
    for section in REQUIRED_AGENTS_SECTIONS:
        if section not in content:
            violations.append(
                Violation("agents-md", "AGENTS.md", f"required section missing: {section!r}")
            )
    return violations


def _git_tracked_files(root: Path) -> list[str]:
    """Files tracked by git; empty when git is unavailable (not a git repo)."""
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    return [line for line in result.stdout.splitlines() if line]


def check_tracked_secrets(root: Path) -> list[Violation]:
    """No secret files may be tracked; .env.example stays placeholder-only."""
    violations: list[Violation] = []
    tracked = _git_tracked_files(root)

    for relpath in tracked:
        name = Path(relpath).name
        looks_secret = (
            name in SECRET_FILE_PATTERNS
            or (name.endswith(SECRET_FILE_SUFFIXES) and not relpath.startswith("docs/"))
        )
        if looks_secret and relpath not in TRACKED_SECRET_ALLOWLIST:
            violations.append(
                Violation("no-secrets", relpath, "secret-like file is tracked by git")
            )

    env_example = root / ".env.example"
    if env_example.is_file():
        for lineno, line in enumerate(
            env_example.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if "=" not in line or line.strip().startswith("#"):
                continue
            key, _, value = line.partition("=")
            if SECRET_KEY_PATTERN.search(key) and not PLACEHOLDER_VALUE.match(value.strip()):
                violations.append(
                    Violation(
                        "no-secrets",
                        f".env.example:{lineno}",
                        f"{key.strip()} must hold a placeholder, not a real credential",
                    )
                )
            if NON_LOCAL_CREDENTIALS.search(value):
                violations.append(
                    Violation(
                        "no-secrets",
                        f".env.example:{lineno}",
                        f"{key.strip()} embeds credentials for a non-local host",
                    )
                )
    return violations


def _imported_modules(tree: ast.Module) -> set[str]:
    """Top-level module names imported anywhere in a module."""
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module.split(".")[0])
    return modules


def _google_llm_imports(tree: ast.Module) -> set[str]:
    """Fully-qualified google.* imports that reference LLM SDK submodules."""
    llm_imports: set[str] = set()
    candidates: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            candidates.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            candidates.append(node.module)
            candidates.extend(f"{node.module}.{alias.name}" for alias in node.names)
    for name in candidates:
        if name.split(".")[0] == "google" and any(sub in name for sub in GOOGLE_LLM_SUBMODULES):
            llm_imports.add(name)
    return llm_imports


def find_domain_directories(root: Path) -> list[Path]:
    """Every ``domain`` directory under apps/api (layered monolith convention)."""
    api_root = root / "apps" / "api"
    if not api_root.is_dir():
        return []
    return sorted(path for path in api_root.rglob("domain") if path.is_dir())


def check_domain_purity(root: Path) -> list[Violation]:
    """Domain Python files must not import infrastructure or vendor modules."""
    violations: list[Violation] = []
    for domain_dir in find_domain_directories(root):
        for py_file in sorted(domain_dir.rglob("*.py")):
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            except SyntaxError as exc:
                violations.append(
                    Violation(
                        "domain-purity",
                        str(py_file.relative_to(root)),
                        f"cannot parse file: {exc}",
                    )
                )
                continue
            rel = py_file.relative_to(root).as_posix()
            for module in sorted(_imported_modules(tree) & FORBIDDEN_DOMAIN_IMPORTS.keys()):
                violations.append(
                    Violation(
                        "domain-purity",
                        rel,
                        f"forbidden import {module!r} ({FORBIDDEN_DOMAIN_IMPORTS[module]})",
                    )
                )
            for qualified in sorted(_google_llm_imports(tree)):
                violations.append(
                    Violation("domain-purity", rel, f"forbidden import {qualified!r} (vendor LLM SDK)")
                )
    return violations


def run_all_checks(root: Path) -> list[Violation]:
    return [
        *check_agents_md(root),
        *check_tracked_secrets(root),
        *check_domain_purity(root),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)

    root = args.root.resolve()
    violations = run_all_checks(root)
    if violations:
        print(f"AGENTS.md enforcement: {len(violations)} violation(s)")
        for violation in violations:
            print(f"  {violation.render()}")
        return 1
    print("AGENTS.md enforcement: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
