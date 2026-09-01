"""
Tests for the trade-review closed loop:
  * strategy_ledger_router.load_ledger / find_verdict  (gate-v2 verdict ledger)
  * trades_router.get_trade_full_review                (per-trade join)

The full-review test seeds a real DatabaseManager (init_db on a temp file) with
one placed trade, its explaining decision (full 5-stage pipeline), and an A–F
review, then asserts the endpoint stitches all four loop stages together.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("API_KEY", "test-dummy-key-not-a-secret-0000")

from routers import strategy_ledger_router as L  # noqa: E402

# ── verdict ledger fixtures ─────────────────────────────────────────────────────


def _write_verdict(d: Path, name: str, **over) -> None:
    body = {
        "symbol": over.get("symbol", "MES"),
        "family": over.get("family", "trend"),
        "rank": over.get("rank", 1),
        "verdict": over.get("verdict", "PASS"),
        "passed_via": over.get("passed_via", "core"),
        "core_verdict": over.get("core_verdict", "PASS"),
        "alt_verdict": over.get("alt_verdict", "UNSCORED"),
        "created_at": over.get("created_at", "2026-05-01T00:00:00+00:00"),
        "gate_v2_metrics": {
            "pf_ci_lower": over.get("pf_ci_lower", 1.5),
            "p_edge": over.get("p_edge", 0.97),
            "mc_95th_dd_pct": over.get("mc_95th_dd_pct", 3.2),
            "dsr": over.get("dsr", 0.4),
            "wfo_consistency": over.get("wfo", "STRONG"),
            "fixed_params_min_pf": over.get("min_pf", 1.3),
            "cost_survives_through": over.get("cost", "pessimistic"),
        },
        "windows": over.get("windows", [{"oos_trades": 10}, {"oos_trades": 15}]),
    }
    (d / name).write_text(json.dumps(body), encoding="utf-8")


def test_load_ledger_parses_counts_and_oos(tmp_path):
    _write_verdict(tmp_path, "MES_trend_rank1.json", verdict="PASS")
    _write_verdict(tmp_path, "MCL_meanrev_rank1.json", symbol="MCL", family="meanrev", verdict="FAIL")
    (tmp_path / "broken.json").write_text("{not valid json", encoding="utf-8")

    rows = L.load_ledger(tmp_path)
    assert len(rows) == 2  # malformed file skipped, never crashes
    by_sym = {r["symbol"]: r for r in rows}
    assert by_sym["MES"]["verdict"] == "PASS"
    assert by_sym["MES"]["oos_trades"] == 25  # summed from windows
    assert by_sym["MES"]["next_gate"] == "forward proof"
    assert by_sym["MES"]["freshness_status"] == "reported"
    assert by_sym["MES"]["freshness_basis"] == "created_at"
    assert by_sym["MES"]["source_file_mtime"]
    assert by_sym["MCL"]["family"] == "meanrev"
    assert by_sym["MCL"]["next_gate"] == "repair thesis"


def test_strategy_ledger_response_includes_freshness_summary(tmp_path, monkeypatch):
    _write_verdict(tmp_path, "MES_trend_rank1.json", verdict="PASS")
    monkeypatch.setattr(L, "_verdicts_dir", lambda: tmp_path)

    body = L.get_strategy_ledger(symbol=None, verdict=None)
    assert body.ledger_freshness.status == "reported"
    assert body.ledger_freshness.basis == "created_at"
    assert body.ledger_freshness.entries_missing_created_at == 0
    assert body.ledger_freshness.entries_with_source_file_mtime == 1
    assert body.entries[0].next_gate == "forward proof"


def test_find_verdict_prefers_pass_then_rank(tmp_path, monkeypatch):
    _write_verdict(tmp_path, "MES_trend_rank3.json", rank=3, verdict="PASS")
    _write_verdict(tmp_path, "MES_trend_rank1.json", rank=1, verdict="FAIL")
    _write_verdict(tmp_path, "MES_meanrev_rank2.json", family="meanrev", rank=2, verdict="PASS")
    monkeypatch.setattr(L, "_verdicts_dir", lambda: tmp_path)

    # symbol-only: a PASS outranks a lower-rank FAIL
    v = L.find_verdict("MES")
    assert v["verdict"] == "PASS"
    # family-specific: confined to that family
    v2 = L.find_verdict("MES", "meanrev")
    assert v2["family"] == "meanrev" and v2["rank"] == 2
    assert L.find_verdict("NOPE") is None


# ── full-review join ────────────────────────────────────────────────────────────


@pytest.fixture
def seeded_db():
    from database.manager import DatabaseManager
    from routers import trades_router as T

    # Capture the trades_router module globals so the inject_dependencies() the
    # tests do is fully reverted on teardown — otherwise a temp DB (deleted
    # below) leaks into later tests in the full suite and breaks them.
    _saved = (T._db_manager, T._llm_client)

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    # construct directly (not init_db) so each test gets a fresh migrated schema —
    # init_db is a process-wide singleton that ignores db_path after the first call.
    db = DatabaseManager(db_path=path)
    db.initialize()

    db.insert_trade(
        trade_id="t-loop-1",
        symbol="MES",
        side="buy",
        quantity=1,
        entry_price=5300.0,
        entry_time="2026-06-12T17:40:35+00:00",
        status="open",
        strategy_params={"source": "scanner", "conviction": 0.65, "direction": "BUY"},
    )
    # explaining decision: same symbol, ~same time, with a full 5-stage pipeline
    db.insert_decision(
        symbol="MES",
        action="buy",
        confidence=0.65,
        regime="trending",
        reasoning="Scanner flagged MES long; debate bull-led.",
        timestamp="2026-06-12T17:40:35",
        full_pipeline_data={
            "analyst_reports": {"technical": "bullish"},
            "debate_result": {"winner": "bull"},
            "trade_decision": {"action": "buy"},
            "risk_decision": {"approved": True},
            "fund_decision": {"size": 1},
        },
    )
    db.upsert_trade_review(
        trade_id="t-loop-1", symbol="MES", direction="LONG",
        grade="B", review_status="complete", conviction=0.65,
    )
    yield db, path
    # restore module globals so this test never pollutes the rest of the suite
    T._db_manager, T._llm_client = _saved
    try:
        Path(path).unlink(missing_ok=True)
    except PermissionError:
        pass


def test_full_review_stitches_the_loop(seeded_db, tmp_path, monkeypatch):
    db, _ = seeded_db
    from routers import trades_router as T

    # point the ledger at a temp verdict so the backtest stage resolves
    _write_verdict(tmp_path, "MES_trend_rank7.json", rank=7, verdict="PASS")
    monkeypatch.setattr(L, "_verdicts_dir", lambda: tmp_path)

    T.inject_dependencies(db, None)
    resp = T.get_trade_full_review("t-loop-1")
    d = resp.model_dump()

    # placed + when
    assert d["trade"]["symbol"] == "MES"
    assert d["trade"]["entry_time"].startswith("2026-06-12T17:40")
    # which (attribution)
    assert d["attribution"]["source"] == "scanner"
    assert d["attribution"]["conviction"] == 0.65
    # why (matched decision + full 5-stage pipeline)
    assert d["why"] is not None
    assert d["why"]["action"] == "buy"
    assert d["why"]["match_delta_seconds"] < 60  # near-exact time match
    pipe = d["why"]["pipeline"]
    assert pipe is not None
    for stage in ("analyst_reports", "debate_result", "trade_decision", "risk_decision", "fund_decision"):
        assert stage in pipe
    # backtest verdict
    assert d["backtest"]["symbol"] == "MES" and d["backtest"]["verdict"] == "PASS"
    # forward stats (real, DB-derived; may be a degenerate window — just present)
    assert d["forward"] is not None and "total_trades" in d["forward"]
    # A–F grade
    assert d["review"]["grade"] == "B"


def test_full_review_404_on_unknown_trade(seeded_db):
    from fastapi import HTTPException

    db, _ = seeded_db
    from routers import trades_router as T

    T.inject_dependencies(db, None)
    with pytest.raises(HTTPException) as exc:
        T.get_trade_full_review("does-not-exist")
    assert exc.value.status_code == 404
