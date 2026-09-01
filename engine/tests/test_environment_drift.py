"""Tests for the read-only environment drift detector."""

from __future__ import annotations

import json
from pathlib import Path

from scripts import check_environment_drift as drift


def test_parse_major_handles_node_and_plain_versions():
    assert drift.parse_major("v24.15.0") == 24
    assert drift.parse_major("10.33.2") == 10
    assert drift.parse_major("Python 3.12.10") == 3
    assert drift.parse_major("not-a-version") is None


def test_dashboard_port_check_reads_package_scripts(tmp_path, monkeypatch):
    dashboard = tmp_path / "dashboard"
    dashboard.mkdir()
    (dashboard / "package.json").write_text(
        json.dumps({"scripts": {"dev": "next dev --port 3010", "start": "next start --port 3010"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(drift, "DASHBOARD_ROOT", dashboard)

    result = drift.check_dashboard_port()

    assert result["passed"] is True
    assert result["severity"] == "fail"


def test_dashboard_port_check_fails_when_start_port_drifts(tmp_path, monkeypatch):
    dashboard = tmp_path / "dashboard"
    dashboard.mkdir()
    (dashboard / "package.json").write_text(
        json.dumps({"scripts": {"dev": "next dev --port 3010", "start": "next start --port 3011"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(drift, "DASHBOARD_ROOT", dashboard)

    result = drift.check_dashboard_port()

    assert result["passed"] is False
    assert "3010" in result["message"]


def test_build_report_marks_hard_failure(monkeypatch):
    def passing(name: str):
        return drift.check(name, True, "fail", "ok")

    monkeypatch.setattr(drift, "check_active_python", lambda: passing("active_python"))
    monkeypatch.setattr(drift, "check_venv_python", lambda: drift.check("venv", False, "fail", "bad"))
    monkeypatch.setattr(drift, "check_parallel_python", lambda: passing("parallel"))
    monkeypatch.setattr(drift, "check_node", lambda: passing("node"))
    monkeypatch.setattr(drift, "check_pnpm", lambda: passing("pnpm"))
    monkeypatch.setattr(drift, "check_dashboard_port", lambda: passing("dashboard_port"))
    monkeypatch.setattr(drift, "check_engine_port", lambda: passing("engine_port"))
    monkeypatch.setattr(drift, "check_trading_safety", lambda: passing("trading_safety"))
    monkeypatch.setattr(drift, "check_dashboard_guards", lambda run_guards: passing("guards"))

    report = drift.build_report()

    assert report["status"] == "fail"
    assert report["summary"]["hard_failures"] == 1


def test_main_can_print_without_writing(monkeypatch, capsys):
    monkeypatch.setattr(
        drift,
        "build_report",
        lambda run_guards=False: {
            "schema_version": 1,
            "created_at": "2026-09-01T00:00:00+00:00",
            "status": "pass",
            "repo_root": str(Path("repo")),
            "checks": [],
            "summary": {"total": 0, "passed": 0, "hard_failures": 0, "warnings": 0},
        },
    )

    exit_code = drift.main(["--no-write"])

    assert exit_code == 0
    assert '"status": "pass"' in capsys.readouterr().out
