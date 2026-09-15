"""Generate the shared API contract from the FastAPI application (TASK-010).

The OpenAPI schema is the single source of truth for the API contract
(ADR-008): it is generated from the backend application and committed to
``packages/contracts/openapi.json`` so the frontend (and any other consumer)
can build typed clients against a reviewable, versioned artifact.

Usage:
    python scripts/generate_contracts.py            # write the contract
    python scripts/generate_contracts.py --check    # verify no drift
Exit codes: 0 on success (or no drift), 1 on drift or failure.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))

CONTRACT_PATH = REPO_ROOT / "packages" / "contracts" / "openapi.json"


def build_contract() -> dict:
    from backcasting.app import create_app

    return create_app().openapi()


def render_contract(contract: dict) -> str:
    return json.dumps(contract, indent=2, sort_keys=False, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed contract matches the application; exit 1 on drift",
    )
    args = parser.parse_args(argv)

    try:
        rendered = render_contract(build_contract())
    except Exception as exc:  # pragma: no cover - surfaced to the operator
        print(f"contract generation failed: {exc}")
        return 1

    if args.check:
        if not CONTRACT_PATH.is_file():
            print(f"contract missing: {CONTRACT_PATH} (run without --check to create)")
            return 1
        committed = CONTRACT_PATH.read_text(encoding="utf-8")
        if committed != rendered:
            print(
                "contract drift: packages/contracts/openapi.json does not match the "
                "application; regenerate with scripts/generate_contracts.py"
            )
            return 1
        print("contract check: OK")
        return 0

    CONTRACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONTRACT_PATH.write_text(rendered, encoding="utf-8")
    print(f"contract written: {CONTRACT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
