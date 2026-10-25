from __future__ import annotations

import json
from pathlib import Path

from backtest import run_mes_trend_rank11 as r11


def _sample_verdict() -> dict:
    return {"symbol": "MES", "verdict": "FAIL", "gate_v2_metrics": {"pf_ci_lower": 0.5}}


def test_write_verdict_doc_dry_run_output_does_not_touch_canonical(tmp_path, monkeypatch):
    monkeypatch.setattr(r11, "engine_root", tmp_path)
    output_path = tmp_path / "scratch" / "rank11_probe.json"

    written = r11._write_verdict_doc(_sample_verdict(), output_path=output_path, dry_run=True)

    canonical = tmp_path / "data" / "gate_v2_verdicts" / "MES_trend_rank11.json"
    assert written == output_path
    assert output_path.exists()
    assert json.loads(output_path.read_text(encoding="utf-8"))["verdict"] == "FAIL"
    assert not canonical.exists()


def test_write_verdict_doc_default_writes_canonical(tmp_path, monkeypatch):
    monkeypatch.setattr(r11, "engine_root", tmp_path)

    written = r11._write_verdict_doc(_sample_verdict())

    canonical = tmp_path / "data" / "gate_v2_verdicts" / "MES_trend_rank11.json"
    assert written == canonical
    assert canonical.exists()
    assert json.loads(canonical.read_text(encoding="utf-8"))["symbol"] == "MES"


def test_write_verdict_doc_dry_run_without_output_is_non_mutating(tmp_path, monkeypatch):
    monkeypatch.setattr(r11, "engine_root", tmp_path)

    written = r11._write_verdict_doc(_sample_verdict(), dry_run=True)

    canonical = tmp_path / "data" / "gate_v2_verdicts" / "MES_trend_rank11.json"
    assert written is None
    assert not canonical.exists()
