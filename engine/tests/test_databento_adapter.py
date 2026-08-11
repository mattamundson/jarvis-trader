"""
JARVIS TRADER — Databento cross-check adapter tests
====================================================
Covers data/databento_adapter.py. The `databento` package is NOT installed
in this venv by design (it's an optional, lazy-imported dependency — see
requirements.txt) — several tests below exercise that real absence rather
than mocking it, since it's the actual "dark by default" state described
in docs/decisions/market-data-vendor-roadmap-2026-07-28.md.
"""

from __future__ import annotations

import pandas as pd
import pytest

from data import databento_adapter as dba


class TestDarkByDefault:
    def test_get_adapter_none_without_key(self, monkeypatch):
        monkeypatch.setattr(dba, "DATABENTO_API_KEY", "")
        assert dba.get_adapter() is None

    def test_get_adapter_returns_instance_with_key(self, monkeypatch):
        monkeypatch.setattr(dba, "DATABENTO_API_KEY", "db-fake-key")
        adapter = dba.get_adapter()
        assert isinstance(adapter, dba.DatabentoAdapter)
        assert adapter.name == "databento"

    def test_reconcile_skipped_without_key(self, monkeypatch):
        monkeypatch.setattr(dba, "DATABENTO_API_KEY", "")
        result = dba.reconcile_vs_cache("MES")
        assert result["status"] == "skipped"
        assert "DATABENTO_API_KEY" in result["reason"]


class TestSymbolMap:
    def test_every_traded_instrument_is_mapped(self):
        # Mirrors FUTURES_MAP in market_data.py — every symbol JARVIS trades
        # (or has approved/rejected verdicts for) must resolve to a Databento
        # continuous symbol, or reconcile_vs_cache will silently no-op for it.
        for sym in ("ES", "MES", "NQ", "MNQ", "GC", "MGC", "CL", "MCL", "RTY", "M2K"):
            assert sym in dba.SYMBOL_MAP, f"{sym} missing from SYMBOL_MAP"

    def test_micro_and_parent_share_continuous_symbol(self):
        assert dba.SYMBOL_MAP["MES"] == dba.SYMBOL_MAP["ES"]
        assert dba.SYMBOL_MAP["MGC"] == dba.SYMBOL_MAP["GC"]

    def test_unmapped_symbol_raises_value_error(self):
        adapter = dba.DatabentoAdapter(api_key="db-fake-key")
        with pytest.raises(ValueError, match="No Databento continuous-symbol mapping"):
            adapter.fetch_minute_bars("ZZFAKE", start=None, end=None)  # type: ignore[arg-type]


class TestMissingPackage:
    """`databento` genuinely isn't installed yet (optional dep) — this
    exercises the real import-failure path, not a mock."""

    def test_fetch_raises_clear_runtime_error(self):
        adapter = dba.DatabentoAdapter(api_key="db-fake-key")
        from datetime import datetime, timezone

        with pytest.raises(RuntimeError, match="databento.*package is not installed"):
            adapter.fetch_minute_bars("MES", datetime.now(timezone.utc), datetime.now(timezone.utc))

    def test_reconcile_reports_error_status_not_exception(self, monkeypatch):
        monkeypatch.setattr(dba, "DATABENTO_API_KEY", "db-fake-key")
        fake_cache = pd.DataFrame({
            "timestamp": pd.to_datetime(["2026-07-27T14:30:00Z"]),
            "open": [5900.0], "high": [5901.0], "low": [5899.0],
            "close": [5900.5], "volume": [120],
        })
        monkeypatch.setattr(
            "data.bars_repository.load_bars", lambda symbol, timeframe: fake_cache
        )
        result = dba.reconcile_vs_cache("MES")
        assert result["status"] == "error"
        assert "not installed" in result["reason"]


class TestReconcileNoCache:
    def test_no_cache_status_when_bars_repository_empty(self, monkeypatch):
        monkeypatch.setattr(dba, "DATABENTO_API_KEY", "db-fake-key")
        monkeypatch.setattr(
            "data.bars_repository.load_bars",
            lambda symbol, timeframe: pd.DataFrame(),
        )
        result = dba.reconcile_vs_cache("MES")
        assert result["status"] == "no_cache"
