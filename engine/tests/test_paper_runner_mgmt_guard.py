"""Guard: one symbol's management error must not starve other symbols' cycle.

The per-symbol management block (_latest_mgmt_bar + manage_open_position) was
unguarded. A transient 5m feed error or a malformed position row (e.g. a NULL
stop -> float(None)) raised straight out of the `for symbol in ACTIVE_INSTRUMENTS`
loop, aborting management for every REMAINING symbol that cycle and leaving their
open positions' stops unevaluated. These tests drive run_one_cycle with two open
positions where the first raises, and assert the second is still managed.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backtest import paper_runner


def _signal_df() -> pd.DataFrame:
    idx = pd.DatetimeIndex(
        [pd.Timestamp("2026-06-05T13:00:00", tz="UTC"), pd.Timestamp("2026-06-05T14:00:00", tz="UTC")]
    )
    return pd.DataFrame(
        {
            "open": [100.0, 101.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.0],
            "close": [101.0, 102.0],
            "regime": ["bull", "bull"],
            "entry_signal": ["none", "none"],
            "bias": ["long", "long"],
            "stc_val": [40.0, 45.0],
            "atr": [1.2, 1.3],
        },
        index=idx,
    )


class _FakeTracker:
    def __init__(self, cfg):
        self.cfg = cfg

    def check_kill_conditions(self):
        return (False, None)


def _wire(monkeypatch, *, manage_side_effect):
    """Patch run_one_cycle's dependency surface for a 2-symbol, both-open cycle."""
    cfg = {
        "enabled": True,
        "strategy": "stc",
        "stc_params": {"stc_os": 20, "stc_ob": 80},
        "max_concurrent_positions": 1,
    }
    futures_map = {"AAA": "AAA1!", "BBB": "BBB1!"}
    active = ["AAA", "BBB"]
    configs = {"AAA": cfg, "BBB": cfg}

    def fake_import_signal_deps():
        return (
            futures_map,
            active,
            configs,
            _FakeTracker,
            lambda df, **k: _signal_df(),  # generate_signals
            lambda df, **k: _signal_df(),  # generate_instrument_signals
        )

    monkeypatch.setattr(paper_runner, "_import_signal_deps", fake_import_signal_deps)
    monkeypatch.setattr(paper_runner, "fetch_bars", lambda *a, **k: _signal_df())
    monkeypatch.setattr(
        paper_runner,
        "load_positions",
        lambda: {"AAA": {"side": "long"}, "BBB": {"side": "long"}},
    )
    monkeypatch.setattr(paper_runner, "_load_entry_eval", lambda: {})
    monkeypatch.setattr(paper_runner, "_load_data_error_state", lambda: {})
    monkeypatch.setattr(paper_runner, "save_positions", lambda *a, **k: None)
    monkeypatch.setattr(paper_runner, "_save_entry_eval", lambda *a, **k: None)
    monkeypatch.setattr(paper_runner, "_save_data_error_state", lambda *a, **k: None)
    monkeypatch.setattr(paper_runner, "_notify", lambda *a, **k: None)
    monkeypatch.setattr(paper_runner, "manage_open_position", manage_side_effect)


def test_one_symbol_mgmt_error_does_not_abort_others(monkeypatch):
    """AAA raises in management; BBB must still be managed in the same cycle."""

    def manage(symbol, pos, bar, ts, cfg, tracker):
        if symbol == "AAA":
            raise ValueError("transient 5m feed blip")
        return ({"side": "long"}, None)  # BBB holds

    _wire(monkeypatch, manage_side_effect=manage)

    summary = paper_runner.run_one_cycle(quiet=True)

    assert summary["AAA"]["action"] == "mgmt_error"  # caught, flagged
    assert summary["BBB"]["action"] == "holding"  # NOT starved by AAA's error


def test_null_stop_typeerror_is_contained(monkeypatch):
    """A malformed position (float(None) on a NULL stop) is contained per-symbol."""

    def manage(symbol, pos, bar, ts, cfg, tracker):
        if symbol == "AAA":
            float(None)  # simulate float(pos["stop"]) on a NULL stop -> TypeError
        return ({"side": "long"}, None)

    _wire(monkeypatch, manage_side_effect=manage)

    summary = paper_runner.run_one_cycle(quiet=True)

    assert summary["AAA"]["action"] == "mgmt_error"
    assert summary["BBB"]["action"] == "holding"
    assert summary["AAA"]["position"] is not None  # position stays tracked
