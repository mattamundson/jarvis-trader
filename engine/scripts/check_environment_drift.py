"""Read-only environment drift detector for JARVIS.

The script emits JSON and exits non-zero when hard runtime expectations drift.
It does not start, stop, or restart services.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENGINE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ENGINE_ROOT.parent
DASHBOARD_ROOT = REPO_ROOT / "dashboard"
DEFAULT_OUTPUT = ENGINE_ROOT / "data" / "health" / "environment_drift_latest.json"

EXPECTED_PYTHON_PREFIX = "3.12"
MIN_NODE_MAJOR = 20
MIN_PNPM_MAJOR = 9
ENGINE_PORT = 8010
DASHBOARD_PORT = 3010
IBKR_PAPER_PORT = 4002


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def parse_major(version_text: str) -> int | None:
    parts = version_text.strip().split()
    if not parts:
        return None
    cleaned = parts[-1].lstrip("v")
    major = cleaned.split(".", 1)[0]
    return int(major) if major.isdigit() else None


def resolve_executable(name: str) -> str:
    return shutil.which(name) or name


def command_result(args: list[str], cwd: Path | None = None, timeout: int = 15) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        return {
            "ok": False,
            "returncode": None,
            "stdout": "",
            "stderr": str(exc),
            "command": args,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "returncode": None,
            "stdout": exc.stdout or "",
            "stderr": f"timeout after {timeout}s",
            "command": args,
        }

    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "command": args,
    }


def check(
    name: str,
    passed: bool,
    severity: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "passed": passed,
        "severity": severity,
        "message": message,
        "details": details or {},
    }


def check_active_python(expected_prefix: str = EXPECTED_PYTHON_PREFIX) -> dict[str, Any]:
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    passed = version.startswith(expected_prefix)
    return check(
        "active_python",
        passed,
        "fail",
        f"active interpreter is Python {version}; expected {expected_prefix}.x",
        {"executable": sys.executable, "version": version, "expected_prefix": expected_prefix},
    )


def check_venv_python(expected_prefix: str = EXPECTED_PYTHON_PREFIX) -> dict[str, Any]:
    venv_python = ENGINE_ROOT / ".venv" / "Scripts" / "python.exe"
    if not venv_python.exists():
        return check(
            "engine_venv_python",
            False,
            "fail",
            "engine/.venv Python executable is missing",
            {"path": str(venv_python)},
        )
    result = command_result([str(venv_python), "--version"], cwd=ENGINE_ROOT)
    version = result["stdout"] or result["stderr"]
    passed = result["ok"] and expected_prefix in version
    return check(
        "engine_venv_python",
        passed,
        "fail",
        f"engine/.venv reports {version!r}; expected Python {expected_prefix}.x",
        {"path": str(venv_python), "command": result, "expected_prefix": expected_prefix},
    )


def check_parallel_python(expected_prefix: str = EXPECTED_PYTHON_PREFIX) -> dict[str, Any]:
    parallel_python = ENGINE_ROOT / ".venv312-codex-loop" / "Scripts" / "python.exe"
    if not parallel_python.exists():
        return check(
            "parallel_python312_venv",
            False,
            "warn",
            "parallel Python 3.12 proof venv is missing",
            {"path": str(parallel_python)},
        )
    result = command_result([str(parallel_python), "--version"], cwd=ENGINE_ROOT)
    version = result["stdout"] or result["stderr"]
    passed = result["ok"] and expected_prefix in version
    return check(
        "parallel_python312_venv",
        passed,
        "warn",
        f"parallel proof venv reports {version!r}; expected Python {expected_prefix}.x",
        {"path": str(parallel_python), "command": result, "expected_prefix": expected_prefix},
    )


def check_node(min_major: int = MIN_NODE_MAJOR) -> dict[str, Any]:
    result = command_result([resolve_executable("node"), "--version"], cwd=DASHBOARD_ROOT)
    version_text = result["stdout"] or result["stderr"]
    major = parse_major(version_text)
    passed = bool(result["ok"] and major is not None and major >= min_major)
    return check(
        "node_version",
        passed,
        "fail",
        f"node version is {version_text!r}; expected major >= {min_major}",
        {"command": result, "major": major, "min_major": min_major},
    )


def check_pnpm(min_major: int = MIN_PNPM_MAJOR) -> dict[str, Any]:
    result = command_result([resolve_executable("pnpm"), "--version"], cwd=DASHBOARD_ROOT)
    version_text = result["stdout"] or result["stderr"]
    major = parse_major(version_text)
    passed = bool(result["ok"] and major is not None and major >= min_major)
    return check(
        "pnpm_version",
        passed,
        "fail",
        f"pnpm version is {version_text!r}; expected major >= {min_major}",
        {"command": result, "major": major, "min_major": min_major},
    )


def check_dashboard_port(expected_port: int = DASHBOARD_PORT) -> dict[str, Any]:
    package_path = DASHBOARD_ROOT / "package.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    scripts = package.get("scripts", {})
    dev = scripts.get("dev", "")
    start = scripts.get("start", "")
    needle = f"--port {expected_port}"
    passed = needle in dev and needle in start
    return check(
        "dashboard_port_config",
        passed,
        "fail",
        f"dashboard dev/start scripts must pin port {expected_port}",
        {"package": str(package_path), "dev": dev, "start": start, "expected": expected_port},
    )


def check_engine_port(expected_port: int = ENGINE_PORT) -> dict[str, Any]:
    claude_path = ENGINE_ROOT / "CLAUDE.md"
    content = claude_path.read_text(encoding="utf-8") if claude_path.exists() else ""
    passed = f"--port {expected_port}" in content or f"port {expected_port}" in content
    return check(
        "engine_port_config",
        passed,
        "fail",
        f"engine docs/start command must pin port {expected_port}",
        {"path": str(claude_path), "expected": expected_port},
    )


def check_trading_safety() -> dict[str, Any]:
    config_path = ENGINE_ROOT / "config.py"
    content = config_path.read_text(encoding="utf-8")
    has_live_false = "LIVE_TRADING_ENABLED: bool = Field(False" in content
    has_paper_port = f"IBKR_PORT: int = Field({IBKR_PAPER_PORT}" in content
    passed = has_live_false and has_paper_port
    return check(
        "trading_safety_defaults",
        passed,
        "fail",
        "config.py must default live trading off and IBKR to paper port 4002",
        {
            "path": str(config_path),
            "live_false": has_live_false,
            "paper_port": has_paper_port,
        },
    )


def check_dashboard_guards(run_guards: bool) -> dict[str, Any]:
    package_path = DASHBOARD_ROOT / "package.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    has_guard_script = "guards" in package.get("scripts", {})
    if not run_guards:
        return check(
            "dashboard_guards",
            has_guard_script,
            "warn",
            "dashboard package must expose a guards script; execution skipped",
            {"package": str(package_path), "ran": False},
        )
    result = command_result([resolve_executable("pnpm"), "run", "guards"], cwd=DASHBOARD_ROOT, timeout=120)
    return check(
        "dashboard_guards",
        bool(has_guard_script and result["ok"]),
        "fail",
        "dashboard guard script must pass",
        {"package": str(package_path), "ran": True, "command": result},
    )


def build_report(run_guards: bool = False) -> dict[str, Any]:
    checks = [
        check_active_python(),
        check_venv_python(),
        check_parallel_python(),
        check_node(),
        check_pnpm(),
        check_dashboard_port(),
        check_engine_port(),
        check_trading_safety(),
        check_dashboard_guards(run_guards=run_guards),
    ]
    hard_failures = [item for item in checks if not item["passed"] and item["severity"] == "fail"]
    warnings = [item for item in checks if not item["passed"] and item["severity"] == "warn"]
    status = "fail" if hard_failures else ("warn" if warnings else "pass")
    return {
        "schema_version": 1,
        "created_at": _now_iso(),
        "status": status,
        "repo_root": str(REPO_ROOT),
        "checks": checks,
        "summary": {
            "total": len(checks),
            "passed": sum(1 for item in checks if item["passed"]),
            "hard_failures": len(hard_failures),
            "warnings": len(warnings),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit JARVIS environment drift JSON")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--no-write", action="store_true", help="Print JSON only.")
    parser.add_argument(
        "--run-dashboard-guards",
        action="store_true",
        help="Also run pnpm run guards from the dashboard directory.",
    )
    args = parser.parse_args(argv)

    report = build_report(run_guards=args.run_dashboard_guards)
    payload = json.dumps(report, indent=2)
    print(payload)

    if not args.no_write:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")

    return 1 if report["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
