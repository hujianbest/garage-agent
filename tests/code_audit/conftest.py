"""Shared fixtures for code-audit pack tests.

The audit-reporter scripts live under packs/code-audit/skills/audit-reporter/
scripts/ and are NOT installed as a Python package (they are intentionally
plain stdlib scripts that ship inside the pack). We add that directory to
sys.path here so test modules can ``import render_html`` directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = (
    REPO_ROOT
    / "packs"
    / "code-audit"
    / "skills"
    / "audit-reporter"
    / "scripts"
)
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
