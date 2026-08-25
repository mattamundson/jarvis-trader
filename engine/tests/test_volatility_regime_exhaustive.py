from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from analysis.volatility_regime import (
    RegimeThresholds,
    add_vix_context,
    build_regime_frame,
    classify_premium_state,
    classify_regime,
    classify_term_state,
    latest_regime_snapshot,
    prepare_price_frame,
)
from scripts.vol_regime_study import run as run_vol_regime_study


def _cache_df(days: int = 140, *, start: float = 100.0, step: float = 0.25) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=days, freq="B")
    closes = [start + i * step for i in range(days)]
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": 1_000,
        }
    )


def _vix_df(days: int = 140, *, base: float = 18.0) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=days, freq="B")
    return pd.DataFrame({"date": dates, "close": [base + (i % 30) * 0.1 for i in range(days)]})


def test_duplicate_and_misordered_dates_keep_last_sorted_value() -> None:
    raw = pd.DataFrame(
        {
            "date": ["2026-01-03", "2026-01-01", "2026-01-01", "2026-01-02"],
            "close": [103.0, 100.0, 101.0, 102.0],
        }
    )
    frame = prepare_price_frame(raw, symbol="SPY")
    assert [d.date().isoformat() for d in frame.index] == ["2026-01-01", "2026-01-02", "2026-01-03"]
    assert frame.loc[pd.Timestamp("2026-01-01"), "close"] == 101.0


def test_term_state_threshold_boundaries_are_flat_inside_band() -> None:
    thresholds = RegimeThresholds(term_flat_band=0.005)
    assert classify_term_state(0.005, thresholds) == "flat"
    assert classify_term_state(-0.005, thresholds) == "flat"
    assert classify_term_state(0.0051, thresholds) == "contango"
    assert classify_term_state(-0.0051, thresholds) == "backwardation"


def test_premium_state_threshold_boundaries() -> None:
    thresholds = RegimeThresholds(rich_iv_rv_spread=0.04, cheap_iv_rv_spread=-0.02)
    assert classify_premium_state(pd.Series({"iv_rv_spread": 0.04}), thresholds) == "premium_rich"
    assert classify_premium_state(pd.Series({"iv_rv_spread": -0.02}), thresholds) == "premium_cheap"
    assert classify_premium_state(pd.Series({"iv_rv_spread": 0.0}), thresholds) == "premium_fair"
    assert classify_premium_state(pd.Series({"iv_rv_spread": None}), thresholds) == "unknown"


def test_regime_precedence_extreme_vix_overrides_trend_up() -> None:
    row = pd.Series(
        {
            "trend_state": "trend_up",
            "rv_20d": 0.10,
            "vix_percentile": 0.91,
            "term_state": "contango",
            "iv_rv_spread": -0.03,
        }
    )
    assert classify_regime(row) == "crash_risk"


def test_missing_vix_context_is_explicit_unknown_not_crash() -> None:
    frame = prepare_price_frame(_cache_df(80), symbol="SPY")
    out = add_vix_context(frame, vix=None, vix3m=None)
    assert set(out["term_state"].dropna().unique()) == {"unknown"}
    assert "vix" not in out.columns
    assert "iv_rv_spread" not in out.columns


def test_partial_vix_alignment_leaves_unmatched_rows_null() -> None:
    price = _cache_df(100)
    vix = _vix_df(50)
    frame = build_regime_frame(price, symbol="SPY", vix=vix, vix3m=None)
    assert frame["vix"].notna().sum() == 50
    assert frame["vix"].isna().sum() == 50
    assert set(frame["term_state"].dropna().unique()) == {"unknown"}


def test_latest_snapshot_is_json_safe() -> None:
    frame = build_regime_frame(_cache_df(120), symbol="QQQ", vix=_vix_df(120), vix3m=_vix_df(120, base=21.0))
    snap = latest_regime_snapshot(frame)
    encoded = json.dumps(snap)
    assert "QQQ" in encoded
    assert snap["date"] == "2025-06-17"
    assert "regime" in snap


def test_cli_run_writes_artifacts_and_data_gaps(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    out = tmp_path / "out"
    cache.mkdir()
    _cache_df(125).to_csv(cache / "SPY_daily.csv", index=False)
    _cache_df(125, start=200.0, step=0.5).to_csv(cache / "QQQ_daily.csv", index=False)

    result = run_vol_regime_study(["SPY", "QQQ"], cache, out)

    assert "VIX daily cache missing" in result["data_gaps"][0]
    assert (out / "vol_regime_study.json").exists()
    for symbol in ["SPY", "QQQ"]:
        assert result["symbols"][symbol]["rows"] == 125
        assert Path(result["symbols"][symbol]["summary_csv"]).exists()
        assert Path(result["symbols"][symbol]["frame_csv"]).exists()


def test_cli_run_uses_vix_and_vix3m_when_available(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    out = tmp_path / "out"
    cache.mkdir()
    _cache_df(130).to_csv(cache / "SPY_daily.csv", index=False)
    _vix_df(130, base=16.0).to_csv(cache / "VIX_daily.csv", index=False)
    _vix_df(130, base=20.0).to_csv(cache / "VIX3M_daily.csv", index=False)

    result = run_vol_regime_study(["SPY"], cache, out)
    frame = pd.read_csv(result["symbols"]["SPY"]["frame_csv"])

    assert result["data_gaps"] == []
    assert frame["vix"].notna().sum() == 130
    assert frame["vix3m"].notna().sum() == 130
    assert "contango" in set(frame["term_state"].dropna())
