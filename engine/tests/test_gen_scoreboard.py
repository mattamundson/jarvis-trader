from __future__ import annotations

import json
from pathlib import Path

import pytest

from backtest import gen_scoreboard


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_scoreboard_writes_canonical_scoreboard_path() -> None:
    assert gen_scoreboard.output_path.name == "SCOREBOARD.md"


def test_generate_includes_legacy_verdict_metrics_and_excludes_sidecars(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    verdicts = tmp_path / "gate_v2_verdicts"
    verdicts.mkdir()
    monkeypatch.setattr(gen_scoreboard, "verdicts_dir", verdicts)

    _write_json(
        verdicts / "MGC_trend_rank4.json",
        {
            "symbol": "MGC",
            "family": "trend",
            "rank": 4,
            "verdict": "PASS",
            "passed_via": "core",
            "created_at": "2026-09-20T17:56:24+00:00",
            "champion_params": {"fast": 50, "slow": 120, "atr_trail_mult": 2.0},
            "gate_v2_metrics": {
                "pf_ci_lower": 1.4674,
                "p_edge": 0.9997,
                "mc_95th_dd_pct": 2.9479,
                "dsr": 0.9918,
                "wfo_consistency": "MODERATE",
                "total_oos_trades": 67,
            },
        },
    )
    _write_json(
        verdicts / "MES_trend_rank7.json",
        {
            "symbol": "MES",
            "family": "trend",
            "rank": 7,
            "verdict": "FAIL",
            "passed_via": None,
            "created_at": "2026-09-19T06:00:02+00:00",
            "gate_v2": {
                "reasons": [
                    "FAIL mbb_pf_ci_lower=0.9247 < 1.1",
                    "FAIL p_positive_edge=0.8774 < 0.95",
                    "FAIL mc_95th_dd_pct=5.3969 > 5.0",
                    "FAIL dsr=0.0 < 0.1 (selection bias)",
                    "rolling_wfo=STRONG in ['MODERATE', 'STRONG']",
                    "fixed_params_min_pf=1.275 >= 1.2",
                    "cost_survives_through=catastrophic >= realistic",
                ],
            },
        },
    )
    _write_json(
        verdicts / "MES_DEEP_CACHE_PROVENANCE_2026-09-12.json",
        {"cache_file": "MES_2024-04-26_2026-09-10_1h.csv"},
    )

    content = gen_scoreboard.generate()

    assert "MGC | trend | 4 | ✅ PASS-core" in content
    assert "SMA 50/120 \\| trail=2.0" in content
    assert "MES | trend | 7 | ❌ FAIL" in content
    assert "0.9247" in content
    assert "0.8774" in content
    assert "5.40" in content
    assert "0.000" in content
    assert "STRONG" in content
    assert "MES_DEEP_CACHE_PROVENANCE" not in content
    assert "? | ? | ?" not in content


def test_generate_fixture_store_truth_counts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    verdicts = tmp_path / "gate_v2_verdicts"
    verdicts.mkdir()
    monkeypatch.setattr(gen_scoreboard, "verdicts_dir", verdicts)

    def verdict(symbol: str, family: str, rank: int, result: str, *, passed_via: str | None = None) -> dict:
        return {
            "symbol": symbol,
            "family": family,
            "rank": rank,
            "verdict": result,
            "passed_via": passed_via,
            "created_at": "2026-09-22T00:00:00+00:00",
            "gate_v2_metrics": {
                "pf_ci_lower": 1.4674 if result == "PASS" else 0.5296,
                "p_edge": 0.9997 if result == "PASS" else 0.7263,
                "mc_95th_dd_pct": 2.9479 if result == "PASS" else 3.2315,
                "dsr": 0.9918 if result == "PASS" else 0.3706,
                "wfo_consistency": "MODERATE" if result == "PASS" else "WEAK",
                "total_oos_trades": 67 if result == "PASS" else 17,
            },
        }

    payloads = {
        "MGC_trend_rank4.json": verdict("MGC", "trend", 4, "PASS", passed_via="core"),
        "MES_stc_trend_meta_rank1.json": verdict("MES", "stc_trend_meta", 1, "FAIL"),
        "MES_trend_rank7.json": verdict("MES", "trend", 7, "FAIL"),
        "MES_trend_rank11.json": verdict("MES", "trend", 11, "FAIL"),
        "MNQ_trend_rank1.json": verdict("MNQ", "trend", 1, "FAIL"),
        "SPY_stc_trend_meta_rank1.json": verdict("SPY", "stc_trend_meta", 1, "FAIL"),
        "MES_DEEP_CACHE_PROVENANCE_2026-09-12.json": {"cache_file": "sidecar.csv"},
    }
    for filename, payload in payloads.items():
        _write_json(verdicts / filename, payload)

    content = gen_scoreboard.generate()
    pass_count = sum(1 for line in content.splitlines() if "| ✅ PASS" in line)
    fail_count = sum(1 for line in content.splitlines() if "| ❌ FAIL" in line)

    assert pass_count == 1
    assert fail_count == 5
    assert "MGC | trend | 4 | ✅ PASS-core" in content
    assert "MES | trend | 11 | ❌ FAIL" in content
    assert "MNQ | trend | 1 | ❌ FAIL" in content
    assert "MES_DEEP_CACHE_PROVENANCE" not in content
