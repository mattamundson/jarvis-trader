"""Tests for the OOS-access-ledger wiring in study_wfo_runner.py.

Surgical: study_wfo_runner.py has no existing test file (heavy IO/CLI runner);
this covers only the new `_log_oos_access` helper added at the two
`_compute_gate_v2` call sites. Must never raise or affect verdict computation
even when the ledger is broken/missing (diagnostic-only, matches the file's
own "never gates verdict" convention for the regime-conditional breakdown).
"""

from __future__ import annotations

from backtest import study_wfo_runner as swr


def test_log_oos_access_calls_ledger_with_symbol_and_purpose(monkeypatch):
    calls = []
    monkeypatch.setattr(
        swr, "_record_oos_access", lambda symbol, purpose, **kw: calls.append((symbol, purpose))
    )
    swr._log_oos_access("MES", "gate_v2:saty:go")
    assert calls == [("MES", "gate_v2:saty:go")]


def test_log_oos_access_never_raises_when_ledger_broken(monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError("disk full")

    monkeypatch.setattr(swr, "_record_oos_access", _boom)
    swr._log_oos_access("MES", "gate_v2:saty:go")  # must not raise


def test_log_oos_access_noop_when_import_failed(monkeypatch):
    monkeypatch.setattr(swr, "_record_oos_access", None)
    swr._log_oos_access("MES", "gate_v2:saty:go")  # must not raise
