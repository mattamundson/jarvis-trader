"""Guard test for the honest paper-P&L surface (engine/analytics/pnl_truth.py).

Every case pins one honesty property. The centerpiece is
``test_missing_source_degrades_and_never_fabricates_zero``: a missing source must
return ``None``, NOT ``0.0`` — that single assertion is what stops the phantom-P&L
class from ever silently returning. If this file goes red, the system has started
lying about money again.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from analytics.pnl_truth import compute_pnl_truth, pnl_truth_from_sqlite


def _closed(pnl: float | None, status: str = "closed") -> dict:
    return {"status": status, "pnl": pnl}


def test_trusted_happy_path_sums_only_closed() -> None:
    truth = compute_pnl_truth([_closed(20.0), _closed(-5.0), {"status": "open", "pnl": None}])
    assert truth.trusted
    assert truth.realized_pnl == 20.0 - 5.0
    assert truth.closed_trades == 2  # the open row is ignored, not summed


def test_empty_ledger_is_trusted_zero() -> None:
    # Zero trades genuinely is zero realized P&L — a real number, not a guess.
    truth = compute_pnl_truth([])
    assert truth.trusted
    assert truth.realized_pnl == 0.0
    assert truth.closed_trades == 0


def test_missing_source_degrades_and_never_fabricates_zero() -> None:
    truth = compute_pnl_truth(None)
    assert not truth.trusted
    assert truth.status == "DEGRADED"
    assert truth.realized_pnl is None  # the anti-fabrication invariant
    assert "no_source" in truth.reasons


def test_closed_trade_missing_pnl_degrades() -> None:
    # A closed trade with no P&L means the ledger is incomplete — don't pretend.
    truth = compute_pnl_truth([_closed(20.0), _closed(None)])
    assert not truth.trusted
    assert truth.realized_pnl is None
    assert any(r.startswith("closed_trade_missing_pnl") for r in truth.reasons)


def test_phantom_rows_excluded_and_counted() -> None:
    # 4982.50 is the real incident value from mark_phantom_trades.py — it must not
    # leak into realized P&L, but the row is real and gets counted as excluded.
    truth = compute_pnl_truth(
        [_closed(20.0), _closed(4982.50, status="phantom"), _closed(-5.0, status="cancelled")]
    )
    assert truth.trusted
    assert truth.realized_pnl == 20.0
    assert truth.closed_trades == 1
    assert truth.excluded_trades == 2


def test_cross_source_divergence_degrades() -> None:
    truth = compute_pnl_truth([_closed(15.0)], cross_source_pnl=999.0)
    assert not truth.trusted
    assert truth.realized_pnl is None
    assert any(r.startswith("source_divergence") for r in truth.reasons)


def test_cross_source_agreement_is_trusted() -> None:
    truth = compute_pnl_truth([_closed(15.0)], cross_source_pnl=15.0)
    assert truth.trusted
    assert truth.realized_pnl == 15.0
    assert "cross_source" in truth.sources_present


def _make_db(path: Path, rows: list[tuple[str, float | None]]) -> None:
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE paper_trades (status TEXT, pnl REAL)")
    con.executemany("INSERT INTO paper_trades (status, pnl) VALUES (?, ?)", rows)
    con.commit()
    con.close()


def test_sqlite_adapter_trusted(tmp_path: Path) -> None:
    db = tmp_path / "ledger.db"
    _make_db(db, [("closed", 12.5), ("closed", -2.5), ("phantom", 4982.5), ("open", None)])
    truth = pnl_truth_from_sqlite(db)
    assert truth.trusted
    assert truth.realized_pnl == 10.0
    assert truth.excluded_trades == 1


def test_sqlite_adapter_missing_db_degrades(tmp_path: Path) -> None:
    truth = pnl_truth_from_sqlite(tmp_path / "does_not_exist.db")
    assert not truth.trusted
    assert truth.realized_pnl is None
    assert "db_not_found" in truth.reasons
