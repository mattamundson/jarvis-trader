"""Tests for the OOS-access-ledger (#234) wiring in study_wfo_runner.py.

Surgical: study_wfo_runner.py has no existing test file (heavy IO/CLI runner);
this covers only the new `_log_oos_access` helper added at the two
`_compute_gate_v2` call sites. Must never raise or affect verdict computation
even when the ledger is broken/missing or the quarterly cap is hit (matches
the file's own "never gates verdict" convention used for the regime-
conditional breakdown).
"""

from __future__ import annotations

from backtest import study_wfo_runner as swr


def test_log_oos_access_calls_ledger_with_purpose_and_symbol(monkeypatch):
    calls = []
    monkeypatch.setattr(
        swr, "record_if_within_budget", lambda purpose, **kw: calls.append(purpose)
    )
    swr._log_oos_access("MES", "gate_v2:saty:go")
    assert calls == ["gate_v2:saty:go:MES"]


def test_log_oos_access_swallows_budget_exceeded(monkeypatch, capsys):
    def _raise(*a, **kw):
        raise swr.OOSBudgetExceeded("2025_oos cap 3/3 used in 2026Q3")

    monkeypatch.setattr(swr, "record_if_within_budget", _raise)
    swr._log_oos_access("MES", "gate_v2:saty:go")  # must not raise
    assert "OOS-LEDGER" in capsys.readouterr().out


def test_log_oos_access_never_raises_when_ledger_broken(monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError("disk full")

    monkeypatch.setattr(swr, "record_if_within_budget", _boom)
    swr._log_oos_access("MES", "gate_v2:saty:go")  # must not raise


def test_log_oos_access_noop_when_import_failed(monkeypatch):
    monkeypatch.setattr(swr, "record_if_within_budget", None)
    swr._log_oos_access("MES", "gate_v2:saty:go")  # must not raise
