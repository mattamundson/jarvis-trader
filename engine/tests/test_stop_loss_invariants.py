"""
Stop-loss directional invariants.

Long positions must have stop_loss < entry_price.
Short positions must have stop_loss > entry_price.

Background: 2026-04-09 incident report flagged an MCL paper position with
stop_loss above entry on a long trade — guaranteed loss on any normal tick.
2026-04-16 audit found zero inverted stops in current SQLite (10 trades) or
JSONL (45 trades) records, so no live data fix is needed. These tests act as
a regression net so the bug can't silently return.

If these tests fail on real data, investigate the upstream stop-calculation
path immediately — likely a missing direction sign in
`composite_signals.py` or `paper_runner.py`.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest


ENGINE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ENGINE_DIR / "data" / "jarvis_trader.db"
JSONL_PATH = ENGINE_DIR / "portfolio" / "trades.jsonl"

LONG_SIDES = frozenset({"buy", "long", "buy_to_open"})
SHORT_SIDES = frozenset({"sell", "short", "sell_short", "sell_to_open"})


def _is_inverted(side: str | None, entry: float | None, stop: float | None) -> bool:
    """True iff the stop is on the wrong side of entry for the given direction."""
    if side is None or entry is None or stop is None:
        return False
    s = side.lower()
    if s in LONG_SIDES and stop > entry:
        return True
    if s in SHORT_SIDES and stop < entry:
        return True
    return False


@pytest.mark.skipif(not DB_PATH.exists(), reason="paper_trades DB not present in CI env")
def test_no_inverted_stops_in_sqlite():
    """Every persisted paper trade must have a directionally-correct stop."""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT trade_id, symbol, side, entry_price, stop_loss "
            "FROM paper_trades "
            "WHERE stop_loss IS NOT NULL AND entry_price IS NOT NULL"
        )
        violations: list[tuple] = [
            row for row in cur.fetchall()
            if _is_inverted(row[2], row[3], row[4])
        ]
    finally:
        conn.close()
    assert not violations, (
        f"{len(violations)} inverted stop(s) found in paper_trades. "
        f"First few: {violations[:5]}. "
        "This is the 2026-04-09 MCL incident regressing — investigate "
        "stop-calculation path in composite_signals.py / paper_runner.py."
    )


@pytest.mark.skipif(not JSONL_PATH.exists(), reason="trades.jsonl not present in CI env")
def test_no_inverted_stops_in_jsonl():
    """Same invariant for the JSONL append-only trade log."""
    violations: list[dict] = []
    with open(JSONL_PATH, encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                continue
            side = rec.get("side") or rec.get("action")
            if _is_inverted(side, rec.get("entry_price"), rec.get("stop_loss")):
                violations.append({"line": lineno, **rec})
    assert not violations, (
        f"{len(violations)} inverted stop(s) in trades.jsonl. "
        f"First: {violations[0] if violations else None}"
    )


class TestStopLossInvariantHelper:
    """Unit tests for the helper itself — make sure it doesn't have its own bug."""

    @pytest.mark.parametrize("side,entry,stop", [
        ("buy", 100.0, 95.0),         # long stop below — correct
        ("long", 50.0, 49.0),
        ("sell", 100.0, 105.0),       # short stop above — correct
        ("short", 50.0, 51.0),
        ("buy", 100.0, None),         # missing data — not inverted
        (None, 100.0, 95.0),
    ])
    def test_helper_accepts_valid_or_missing(self, side, entry, stop):
        assert not _is_inverted(side, entry, stop)

    @pytest.mark.parametrize("side,entry,stop", [
        ("buy", 100.0, 105.0),        # long stop ABOVE — wrong (the bug)
        ("long", 50.0, 51.0),
        ("buy_to_open", 84.20, 86.00),  # the original 2026-04-09 MCL case
        ("sell", 100.0, 95.0),        # short stop BELOW — wrong
        ("short", 50.0, 49.0),
    ])
    def test_helper_flags_inverted(self, side, entry, stop):
        assert _is_inverted(side, entry, stop)
