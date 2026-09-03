#!/usr/bin/env python3
"""Fail if active trading paths import draft Phase-1 domain authorities early.

Until the adoption manifest changes in a later governed WP, `engine/domain` is a
contract-review area only. Active risk/execution/router/strategy/broker code must
not import it. This avoids accidental authority migration through a convenient
helper import before parity, recovery, and runtime evidence exist.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
ACTIVE_DIRS = (
    "engine/agents",
    "engine/brokers",
    "engine/execution",
    "engine/portfolio",
    "engine/risk",
    "engine/routers",
    "engine/strategies",
)
ACTIVE_FILES = ("engine/main.py", "engine/config.py", "engine/pipeline.py")
BLOCKED_PREFIXES = ("domain", "engine.domain")


def _is_blocked_module(name: str | None) -> bool:
    if not name:
        return False
    return any(name == prefix or name.startswith(f"{prefix}.") for prefix in BLOCKED_PREFIXES)


def scan_file(path: Path) -> list[dict[str, Any]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        module: str | None = None
        if isinstance(node, ast.ImportFrom):
            module = node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if _is_blocked_module(alias.name):
                    violations.append(
                        {"path": str(path), "line": node.lineno, "module": alias.name}
                    )
        if isinstance(node, ast.ImportFrom) and _is_blocked_module(module):
            violations.append({"path": str(path), "line": node.lineno, "module": module})
    return violations


def scan_repository(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    files: list[Path] = []
    for relative in ACTIVE_DIRS:
        root = repo_root / relative
        if root.exists():
            files.extend(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)
    for relative in ACTIVE_FILES:
        path = repo_root / relative
        if path.exists():
            files.append(path)

    violations: list[dict[str, Any]] = []
    for path in sorted(set(files)):
        for violation in scan_file(path):
            violation["path"] = str(path.relative_to(repo_root)).replace("\\", "/")
            violations.append(violation)
    return {
        "check": "JARVIS_PHASE1_PREMATURE_INTEGRATION_BOUNDARY",
        "schema_version": 1,
        "adoption_active": False,
        "scanned_files": len(set(files)),
        "violations": violations,
        "pass": not violations,
        "note": "Remove/replace this ratchet only through the explicit authority-migration WP.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check pre-adoption Phase-1 import boundary.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = scan_repository(args.repo_root.resolve())
    except (OSError, SyntaxError) as exc:
        parser.error(str(exc))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Phase-1 integration boundary: {'PASS' if report['pass'] else 'FAIL'}")
        print(f"Scanned files: {report['scanned_files']}")
        for row in report["violations"]:
            print(f"[VIOLATION] {row['path']}:{row['line']} imports {row['module']}")
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    sys.exit(main())
