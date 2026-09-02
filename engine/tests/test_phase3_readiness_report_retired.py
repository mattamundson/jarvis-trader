"""Regression test for retirement of the legacy Phase 3 live-readiness CLI."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "phase3_readiness_report.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("_phase3_readiness_report", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_legacy_phase3_go_is_forced_to_non_authorizing_no_go(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    script = _load_script()
    from readiness import phase3_criteria

    db_path = tmp_path / "legacy.db"
    db_path.touch()
    monkeypatch.setattr(
        phase3_criteria,
        "evaluate_with_edge_mode",
        lambda _path: {"summary": {"overall": "GO"}, "criteria": []},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["phase3_readiness_report.py", "--db", str(db_path), "--json"],
    )

    assert script.main() == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["legacy_result"] == "GO"
    assert payload["summary"]["overall"] == "NO-GO"
    assert payload["summary"]["live_authorization"] is False
    assert "M11" in payload["summary"]["authorization_reason"]
