"""Best-effort git branch/commit identification for the running process.

Diagnostic only -- must never raise or block a caller. Added 2026-08-13:
a real MGC paper order (2026-08-03) traced back to the shared engine
checkout running whatever branch happened to be checked out at the
process's last restart, with no record anywhere of what commit was
actually loaded into the running process -- see the
fix/engine-pythonhome-crashloop Phase 0b investigation. This makes that
observable going forward, both in startup logs (main.py) and live via
GET /health (routers/health_router.py).
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def get_git_provenance() -> str:
    """Return "<branch>@<short-sha>" for this checkout, or "unknown"."""
    try:
        cwd = Path(__file__).resolve().parent.parent
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd,
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).decode().strip()
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=cwd,
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).decode().strip()
        return f"{branch}@{sha}"
    except Exception:
        return "unknown"
