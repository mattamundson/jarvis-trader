"""
Unit tests for engine/analytics/post_trade.py

Pure-function tests over synthetic closed-trade dicts -- no DB, no engine, no
network, no clock. These keep the WS4B post-trade analytics green offline.
"""

from __future__ import annotations

from analytics.post_trade import (
    EXIT_MANUAL,
    EXIT_STOP,
    EXIT_TARGET,
    EXIT_UNKNOWN,
    derive_exit_reason,
    exit_attribution,
    losing_streak,
    pnl_waterfall,
    regime_attribution,
    slippage_attribution,
)


class _FakeSpec:
    """Stand-in for backtest.contract_specs.ContractSpec."""

    def __init__(self, tick_value: float):
        self.tick_value = tick_value


def _spec_lookup(symbol: str):
    table = {"MES": _FakeSpec(1.25), "MNQ": _FakeSpec(0.5)}
    return table.get(symbol.upper())


def _trade(**kw) -> dict:
    base = {
        "trade_id": "t",
        "symbol": "MES",
        "side": "buy",
        "quantity": 1.0,
        "entry_price": 100.0,
        "exit_price": 101.0,
        "pnl": 5.0,
        "entry_time": "2026-06-01T10:00:00Z",
        "exit_time": "2026-06-01T11:00:00Z",
        "status": "closed",
        "stop_loss": 98.0,
        "take_profit": 104.0,
        "bracket_status": None,
        "slippage_ticks": None,
        "regime": "TRENDING",
        "mae_pct": 0.01,
        "mfe_pct": 0.04,
        "mae_usd": -10.0,
        "mfe_usd": 40.0,
    }
    base.update(kw)
    return base


# ── derive_exit_reason ────────────────────────────────────────────────────────


def test_exit_reason_long_target():
    t = _trade(side="buy", exit_price=104.0, take_profit=104.0, stop_loss=98.0)
    assert derive_exit_reason(t) == EXIT_TARGET


def test_exit_reason_long_stop():
    t = _trade(side="buy", exit_price=98.0, take_profit=104.0, stop_loss=98.0)
    assert derive_exit_reason(t) == EXIT_STOP


def test_exit_reason_short_target():
    # short: target is BELOW entry
    t = _trade(side="sell", entry_price=100.0, exit_price=96.0, take_profit=96.0, stop_loss=103.0)
    assert derive_exit_reason(t) == EXIT_TARGET


def test_exit_reason_short_stop():
    t = _trade(side="sell", entry_price=100.0, exit_price=103.0, take_profit=96.0, stop_loss=103.0)
    assert derive_exit_reason(t) == EXIT_STOP


def test_exit_reason_manual_when_between_brackets():
    t = _trade(side="buy", exit_price=101.0, take_profit=104.0, stop_loss=98.0)
    assert derive_exit_reason(t) == EXIT_MANUAL


def test_exit_reason_bracket_status_keyword_wins():
    t = _trade(bracket_status="TARGET_FILLED", exit_price=101.0)
    assert derive_exit_reason(t) == EXIT_TARGET
    t2 = _trade(bracket_status="stopped_out", exit_price=101.0)
    assert derive_exit_reason(t2) == EXIT_STOP


def test_exit_reason_unknown_when_no_exit_price():
    t = _trade(exit_price=None)
    assert derive_exit_reason(t) == EXIT_UNKNOWN


# ── exit_attribution ──────────────────────────────────────────────────────────


def test_exit_attribution_groups_and_classified_pct():
    trades = [
        _trade(trade_id="a", side="buy", exit_price=104.0, take_profit=104.0, stop_loss=98.0, pnl=20.0),
        _trade(trade_id="b", side="buy", exit_price=98.0, take_profit=104.0, stop_loss=98.0, pnl=-10.0),
        _trade(trade_id="c", side="buy", exit_price=101.0, take_profit=104.0, stop_loss=98.0, pnl=3.0),
    ]
    out = exit_attribution(trades)
    assert out["by_reason"][EXIT_TARGET]["count"] == 1
    assert out["by_reason"][EXIT_STOP]["count"] == 1
    assert out["by_reason"][EXIT_MANUAL]["count"] == 1
    assert out["overall"]["count"] == 3
    assert out["overall"]["total_pnl"] == 13.0
    # all three classified (none unknown)
    assert out["classified_pct"] == 1.0


def test_exit_attribution_empty():
    out = exit_attribution([])
    assert out["overall"]["count"] == 0
    assert out["classified_pct"] is None


# ── slippage_attribution ──────────────────────────────────────────────────────


def test_slippage_attribution_usd_and_populated_count():
    trades = [
        _trade(trade_id="a", symbol="MES", slippage_ticks=2.0, quantity=1.0, pnl=10.0),
        _trade(trade_id="b", symbol="MES", slippage_ticks=4.0, quantity=2.0, pnl=-5.0),
        _trade(trade_id="c", symbol="MES", slippage_ticks=None, pnl=1.0),  # unpopulated
    ]
    out = slippage_attribution(trades, _spec_lookup)
    assert out["trade_count"] == 3
    assert out["populated_count"] == 2
    # MES tick_value 1.25: a=2*1.25*1=2.5 ; b=4*1.25*2=10.0 => 12.5
    assert out["total_slippage_usd"] == 12.5
    assert out["by_symbol"]["MES"]["count"] == 2
    assert out["by_symbol"]["MES"]["avg_ticks"] == 3.0


def test_slippage_attribution_no_spec_returns_none_usd():
    trades = [_trade(symbol="MES", slippage_ticks=2.0)]
    out = slippage_attribution(trades, spec_lookup=None)
    assert out["total_slippage_usd"] is None
    assert out["by_symbol"]["MES"]["avg_ticks"] == 2.0


# ── losing_streak ─────────────────────────────────────────────────────────────


def test_losing_streak_counts_runs_in_order():
    # chronological pnl: +, -, -, -, +, -  -> max loss streak 3, current streak -1
    pnls = [5, -2, -3, -1, 4, -6]
    trades = [
        _trade(trade_id=str(i), exit_time=f"2026-06-01T{10 + i:02d}:00:00Z", pnl=p)
        for i, p in enumerate(pnls)
    ]
    out = losing_streak(trades)
    assert out["max_consecutive_losses"] == 3
    assert out["max_consecutive_wins"] == 1
    assert out["current_streak"] == -1
    # worst run = -2 + -3 + -1 = -6 (the 3-loss run), vs the single -6 tail => -6 tie
    assert out["worst_drawdown_run_usd"] == -6.0


def test_losing_streak_scratch_breaks_run():
    pnls = [-1, 0, -1]  # the zero breaks the losing run
    trades = [
        _trade(trade_id=str(i), exit_time=f"2026-06-01T{10 + i:02d}:00:00Z", pnl=p)
        for i, p in enumerate(pnls)
    ]
    out = losing_streak(trades)
    assert out["max_consecutive_losses"] == 1


# ── pnl_waterfall ─────────────────────────────────────────────────────────────


def test_pnl_waterfall_steps_and_capture():
    t = _trade(symbol="MES", pnl=20.0, mfe_usd=40.0, mae_usd=-10.0, slippage_ticks=2.0, quantity=1.0)
    out = pnl_waterfall(t, _spec_lookup)
    labels = [s["label"] for s in out["steps"]]
    assert labels == ["Peak (MFE)", "Given back", "Realized"]
    assert out["steps"][0]["value"] == 40.0
    assert out["steps"][1]["value"] == -20.0  # 20 - 40
    assert out["steps"][2]["value"] == 20.0
    assert out["mfe_capture_ratio"] == 0.5  # 20/40
    assert out["slippage_usd"] == 2.5  # 2 * 1.25 * 1


def test_pnl_waterfall_tolerates_missing_excursion():
    t = _trade(pnl=7.0, mfe_usd=None, mae_usd=None, slippage_ticks=None)
    out = pnl_waterfall(t, _spec_lookup)
    assert out["mfe_capture_ratio"] is None
    assert out["steps"] == [{"label": "Realized", "value": 7.0}]


# ── regime_attribution ────────────────────────────────────────────────────────


def test_regime_attribution_groups_by_entry_regime():
    trades = [
        _trade(trade_id="a", regime="TRENDING", pnl=10.0),
        _trade(trade_id="b", regime="TRENDING", pnl=-4.0),
        _trade(trade_id="c", regime="RANGING", pnl=2.0),
        _trade(trade_id="d", regime=None, pnl=1.0),
    ]
    out = regime_attribution(trades)
    assert out["regimes_observed"] == 3
    assert out["by_regime"]["TRENDING"]["count"] == 2
    assert out["by_regime"]["TRENDING"]["total_pnl"] == 6.0
    assert out["by_regime"]["unknown"]["count"] == 1
    assert out["overall"]["count"] == 4


def test_profit_factor_undefined_is_none_not_inf():
    # all-winners set => profit factor would be infinite; must be JSON-safe None,
    # with wins/losses disambiguating from an empty set.
    out = regime_attribution([_trade(trade_id="w", regime="R", pnl=5.0)])
    blk = out["by_regime"]["R"]
    assert blk["profit_factor"] is None
    assert blk["wins"] == 1 and blk["losses"] == 0


# ── end-to-end endpoint smoke tests (real temp SQLite, real schema) ───────────


def _seed_closed_trades(db):
    """Insert synthetic closed trades straight into a migrated paper_trades."""
    rows = [
        # trade_id, symbol, side, qty, entry, exit, entry_time, exit_time, pnl,
        # stop_loss, take_profit, regime, slippage_ticks, mae_usd, mfe_usd
        ("A", "MES", "buy", 1.0, 100.0, 104.0, "2026-06-01T11:00:00Z", "2026-06-01T11:30:00Z", 20.0, 98.0, 104.0, "TRENDING", 2.0, -5.0, 25.0),
        ("B", "MES", "buy", 1.0, 100.0, 98.0, "2026-06-01T12:00:00Z", "2026-06-01T12:30:00Z", -10.0, 98.0, 104.0, "TRENDING", 4.0, -12.0, 5.0),
        ("C", "MES", "sell", 1.0, 100.0, 101.0, "2026-06-01T13:00:00Z", "2026-06-01T13:30:00Z", 3.0, 103.0, 96.0, "RANGING", None, -2.0, 8.0),
    ]
    with db._lock:
        conn = db._connect()
        try:
            for r in rows:
                conn.execute(
                    """INSERT INTO paper_trades
                       (trade_id, symbol, side, quantity, entry_price, exit_price,
                        entry_time, exit_time, pnl, status, stop_loss, take_profit,
                        regime, slippage_ticks, mae_usd, mfe_usd, idempotency_key)
                       VALUES (?,?,?,?,?,?,?,?,?, 'closed', ?,?,?,?,?,?, ?)""",
                    (*r, f"idem-{r[0]}"),
                )
            conn.commit()
        finally:
            conn.close()


def _post_trade_client(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import analytics_router as ar

    ar.set_db_manager(db)
    app = FastAPI()
    app.include_router(ar.router)
    return TestClient(app, raise_server_exceptions=True)


def test_endpoints_e2e(tmp_path):
    from database.manager import DatabaseManager

    db = DatabaseManager(db_path=str(tmp_path / "pt.db"))
    db.initialize()  # create tables + run migrations (idempotent)
    _seed_closed_trades(db)
    client = _post_trade_client(db)

    # exit-attribution: A=target, B=stop, C=manual
    ea = client.get("/analytics/exit-attribution")
    assert ea.status_code == 200
    body = ea.json()
    assert body["overall"]["count"] == 3
    assert body["by_reason"]["target"]["count"] == 1
    assert body["by_reason"]["stop"]["count"] == 1
    assert body["by_reason"]["manual"]["count"] == 1

    # slippage-attribution: 2 populated, MES tick_value=1.25 => (2+4)*1.25 = 7.5
    sa = client.get("/analytics/slippage-attribution").json()
    assert sa["populated_count"] == 2
    assert sa["total_slippage_usd"] == 7.5

    # losing-streak: chronological win/loss/win
    ls = client.get("/analytics/losing-streak").json()
    assert ls["max_consecutive_losses"] == 1
    assert ls["max_consecutive_wins"] == 1

    # by-regime
    rg = client.get("/analytics/trades/by-regime").json()
    assert rg["by_regime"]["TRENDING"]["count"] == 2
    assert rg["by_regime"]["RANGING"]["count"] == 1

    # pnl-breakdown for A, and 404 for unknown
    wf = client.get("/analytics/trades/A/pnl-breakdown")
    assert wf.status_code == 200
    assert wf.json()["realized_pnl"] == 20.0
    assert client.get("/analytics/trades/NOPE/pnl-breakdown").status_code == 404
