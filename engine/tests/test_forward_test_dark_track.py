"""R1/T4-T7: observe-only dark-track ledgers feed the lineage graduation track.

Relative-value spreads and the turn-of-month calendar anomaly write isolated JSONL
ledgers under ``data/`` (never the live DB). ``load_dark_track_trades`` folds them
into the closed-trade stream so they graduate on the SAME bar as the LLM lineages --
spreads carry a nested decision_identity already; the TOM daily ledger is adapted via
``tom_records_to_closed_trades``. Their composite symbols mean the mechanical
candidate loop and per-symbol context never pick them up.
"""

from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("API_KEY", "test-key")
_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

from backtest import forward_test as ft  # noqa: E402


def _write_jsonl(path: str, rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


# ── T5: TOM calendar adapter ──────────────────────────────────────────────────────


def test_tom_records_to_closed_trades_shape():
    recs = [{"date": "2026-06-01", "net_bps": 15.0}, {"date": "2026-06-30", "net_bps": -3.0}]
    out = ft.tom_records_to_closed_trades(recs, lineage="tom_spy_v1", symbol="SPY_TOM")
    assert len(out) == 2
    assert out[0]["symbol"] == "SPY_TOM"
    assert out[0]["pnl"] == 15.0
    assert out[0]["exit_time"] == "2026-06-01"
    # Stamped so trade_lineage() reads it as a graduation-eligible lineage.
    assert ft.trade_lineage(out[0]) == "tom_spy_v1::SPY_TOM"


def test_tom_records_skips_incomplete_rows():
    recs = [
        {"date": "2026-06-01", "net_bps": 15.0},
        {"date": "2026-06-02"},  # no net -> dropped
        {"net_bps": 5.0},  # no date -> dropped
    ]
    out = ft.tom_records_to_closed_trades(recs, lineage="tom_spy_v1", symbol="SPY_TOM")
    assert len(out) == 1


# ── T4: dark-ledger loading ───────────────────────────────────────────────────────


def test_load_dark_track_trades_reads_spread_root_subdir_and_tom(tmp_path):
    base = str(tmp_path)
    spread_root = os.path.join(base, "spread_paper_track")
    # Legacy ES-NQ root ledger (stamped nested).
    _write_jsonl(
        os.path.join(spread_root, "closed_trades.jsonl"),
        [
            {
                "symbol": "ES_NQ_SPREAD",
                "exit_time": "2026-06-01T00:00:00Z",
                "pnl": 12.0,
                "strategy_params": {
                    "decision_identity": {"lineage": "es_nq_spread_v1::ES_NQ_SPREAD"}
                },
            },
        ],
    )
    # Per-pair subdir ledger (globbed).
    _write_jsonl(
        os.path.join(spread_root, "MES-M2K", "closed_trades.jsonl"),
        [
            {
                "symbol": "MES_M2K_SPREAD",
                "exit_time": "2026-06-02T00:00:00Z",
                "pnl": 8.0,
                "strategy_params": {
                    "decision_identity": {"lineage": "mes_m2k_spread_v1::MES_M2K_SPREAD"}
                },
            },
        ],
    )
    # TOM daily ledger (adapted).
    _write_jsonl(
        os.path.join(base, "tom_paper_track", "tom_forward_ledger.jsonl"),
        [
            {"date": "2026-06-01", "net_bps": 15.0},
        ],
    )

    trades = ft.load_dark_track_trades(base=base)
    lineages = {ft.trade_lineage(t) for t in trades}
    assert lineages == {
        "es_nq_spread_v1::ES_NQ_SPREAD",
        "mes_m2k_spread_v1::MES_M2K_SPREAD",
        "tom_spy_v1::SPY_TOM",
    }


def test_load_dark_track_trades_empty_when_no_ledgers(tmp_path):
    assert ft.load_dark_track_trades(base=str(tmp_path)) == []


# ── T4: feed reaches the lineage track via run_forward_test ────────────────────────


def _reg_with_dark_lineages():
    return {
        "graduation_rule": {
            "min_forward_oos_windows": 6,
            "min_forward_pf_ci_lower": 1.10,
            "min_forward_p_edge": 0.95,
            "must_survive_family_fdr": False,
        },
        "lineages": [
            {
                "id": "mes_m2k_spread_v1",
                "status": "forward_testing",
                "strategy_type": "spread",
                "inception": "2026-06-24",
                "legs": ["MES", "M2K"],
                "composite_symbol": "MES_M2K_SPREAD",
            },
            {
                "id": "tom_spy_v1",
                "status": "forward_testing",
                "strategy_type": "calendar",
                "inception": "2026-06-24",
                "rule": "turn_of_month",
                "vehicle": "SPY",
            },
        ],
    }


def test_dark_trades_appear_as_lineages_in_report(monkeypatch):
    # One mechanical candidate on MES; dark trades use composite symbols only.
    spread = [
        {
            "symbol": "MES_M2K_SPREAD",
            "exit_time": f"2026-{1 + i:02d}-15T15:00:00Z",
            "pnl": 9.0,
            "strategy_params": {
                "decision_identity": {"lineage": "mes_m2k_spread_v1::MES_M2K_SPREAD"}
            },
        }
        for i in range(6)
    ]
    monkeypatch.setattr(ft, "load_dark_track_trades", lambda base=None: spread)

    class _DB:
        def get_closed_trades(self, limit=0):
            return []

    candidate_reg = {
        "graduation_rule": {},
        "candidates": [{"id": "mes_trend", "symbol": "MES", "status": "forward_testing"}],
    }
    # run_lineage_track loads the shipped decision_registry; the spread appears as a
    # lineage regardless of whether it is registered yet (presence, not graduation).
    report = ft.run_forward_test(registry=candidate_reg, db=_DB())
    assert any(lin["lineage"] == "mes_m2k_spread_v1::MES_M2K_SPREAD" for lin in report["lineages"])


def test_dark_trades_do_not_touch_mechanical_candidates_or_symbol_context(monkeypatch):
    spread = [
        {
            "symbol": "MES_M2K_SPREAD",
            "exit_time": f"2026-{1 + i:02d}-15T15:00:00Z",
            "pnl": 9.0,
            "strategy_params": {
                "decision_identity": {"lineage": "mes_m2k_spread_v1::MES_M2K_SPREAD"}
            },
        }
        for i in range(6)
    ]
    monkeypatch.setattr(ft, "load_dark_track_trades", lambda base=None: spread)

    class _DB:
        def get_closed_trades(self, limit=0):
            return []

    candidate_reg = {
        "graduation_rule": {},
        "candidates": [{"id": "mes_trend", "symbol": "MES", "status": "forward_testing"}],
    }
    report = ft.run_forward_test(registry=candidate_reg, db=_DB())
    # Composite-symbol spread never attributes to the MES candidate...
    cand = next(c for c in report["candidates"] if c["id"] == "mes_trend")
    assert cand["forward"]["n_oos_windows"] == 0
    # ...nor leaks into the MES symbol context.
    assert report["symbol_context"]["MES"]["n_oos_windows"] == 0


# ── T7: strategy_type surfacing ────────────────────────────────────────────────────


def test_lineage_row_carries_strategy_type():
    trades = [
        {
            "symbol": "MES_M2K_SPREAD",
            "exit_time": f"2026-{1 + i:02d}-15T15:00:00Z",
            "pnl": 9.0,
            "strategy_params": {
                "decision_identity": {"lineage": "mes_m2k_spread_v1::MES_M2K_SPREAD"}
            },
        }
        for i in range(3)
    ]
    out = ft.run_lineage_track(trades, decision_registry=_reg_with_dark_lineages())
    row = next(r for r in out if r["lineage"] == "mes_m2k_spread_v1::MES_M2K_SPREAD")
    assert row["strategy_type"] == "spread"


def test_unregistered_lineage_type_is_dash():
    trades = [
        {
            "symbol": "ES_NQ_SPREAD",
            "exit_time": "2026-01-15T15:00:00Z",
            "pnl": 9.0,
            "strategy_params": {"decision_identity": {"lineage": "es_nq_spread_v1::ES_NQ_SPREAD"}},
        },
    ]
    out = ft.run_lineage_track(trades, decision_registry=_reg_with_dark_lineages())
    row = next(r for r in out if r["lineage"] == "es_nq_spread_v1::ES_NQ_SPREAD")
    assert row["strategy_type"] == "-"


def test_markdown_lineage_table_has_type_column():
    report = {
        "generated_at": "now",
        "window_days": 30,
        "graduation_rule": {},
        "n_active_candidates": 0,
        "n_graduated": 0,
        "candidates": [],
        "lineages": [
            {
                "lineage": "mes_m2k_spread_v1::MES_M2K_SPREAD",
                "strategy_type": "spread",
                "pre_registered": True,
                "forward": {"n_oos_windows": 3, "p_edge": 1.0, "pf_ci_lower": 1.5},
                "survives_family_fdr": True,
                "graduated": False,
            }
        ],
        "n_lineages": 1,
        "n_lineages_graduated": 0,
        "symbol_context": {},
        "note": "test",
    }
    md = ft._markdown(report)
    assert "| type |" in md
    assert "spread" in md
