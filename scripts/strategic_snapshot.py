#!/usr/bin/env python3
"""Write docs/strategic/METRICS_SNAPSHOT.json with verifiable repo metrics.

Run from repo root (any cwd is OK — script resolves root from __file__):

    python scripts/strategic_snapshot.py

Uses engine/.venv Python for pytest collection when available.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _venv_python(root: Path) -> Path | None:
    win = root / "engine" / ".venv" / "Scripts" / "python.exe"
    if win.is_file():
        return win
    nix = root / "engine" / ".venv" / "bin" / "python"
    if nix.is_file():
        return nix
    return None


def _pytest_python(root: Path) -> Path:
    """Prefer engine venv; fall back to current interpreter (CI with pip install)."""
    v = _venv_python(root)
    if v is not None:
        return v
    return Path(sys.executable)


def main() -> int:
    root = _repo_root()
    main_py = root / "engine" / "main.py"
    if not main_py.is_file():
        print("error: engine/main.py not found", file=sys.stderr)
        return 1

    text = main_py.read_text(encoding="utf-8", errors="replace")
    include_count = len(re.findall(r"app\.include_router\(", text))

    routers_dir = root / "engine" / "routers"
    router_modules: list[str] = []
    if routers_dir.is_dir():
        router_modules = sorted(
            p.stem for p in routers_dir.glob("*.py") if p.name != "__init__.py"
        )

    tests_dir = root / "engine" / "tests"
    test_modules = (
        len(list(tests_dir.glob("test_*.py"))) if tests_dir.is_dir() else 0
    )

    engine_py = 0
    eng = root / "engine"
    if eng.is_dir():
        engine_py = sum(
            1
            for p in eng.rglob("*.py")
            if ".venv" not in p.parts and "__pycache__" not in p.parts
        )

    pytest_collected: int | None = None
    pytest_py = _pytest_python(root)
    if tests_dir.is_dir():
        try:
            proc = subprocess.run(
                [
                    str(pytest_py),
                    "-m",
                    "pytest",
                    str(tests_dir),
                    "--collect-only",
                    "-q",
                ],
                cwd=str(root / "engine"),
                capture_output=True,
                text=True,
                timeout=240,
            )
            combined = (proc.stdout or "") + (proc.stderr or "")
            m = re.search(r"(\d+)\s+tests?\s+collected", combined, re.IGNORECASE)
            if m:
                pytest_collected = int(m.group(1))
        except (OSError, subprocess.TimeoutExpired):
            pytest_collected = None

    git_sha: str | None = None
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0:
            git_sha = proc.stdout.strip()
    except OSError:
        pass

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_short_sha": git_sha,
        "engine_main_py_include_router_calls": include_count,
        "engine_routers_python_modules": len(router_modules),
        "engine_routers_module_names": router_modules,
        "engine_tests_test_modules": test_modules,
        "engine_python_files_excluding_dot_venv": engine_py,
        "pytest_tests_collected": pytest_collected,
        "notes": "Regenerate: python scripts/strategic_snapshot.py (from repo root).",
    }

    out_path = root / "docs" / "strategic" / "METRICS_SNAPSHOT.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
