"""Shared pytest configuration for repository-level tests.

Makes the backend package under ``apps/api/src`` importable so application
tests can run from the repository root without installation. Packaging and
dependency pinning are formalized by TASK-009/TASK-010.
"""

from __future__ import annotations

import sys
from pathlib import Path

API_SRC = Path(__file__).resolve().parents[1] / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
