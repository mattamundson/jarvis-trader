"""MGC was previously absent from the /paper/validation/counts readiness
counter even though it's one of only two currently paper-active APPROVED
instruments (engine/CLAUDE.md: "requires 60+ live MGC trades for calibration").
Covers the fix: MGC now has a target and is not blocked.
"""

from __future__ import annotations

import asyncio

from routers.paper_validation_router import _Q2_BLOCKED_SYMBOLS, _Q2_PAPER_TARGETS


def test_mgc_present_with_60_trade_target_and_unblocked():
    assert _Q2_PAPER_TARGETS.get("MGC") == 60
    assert "MGC" not in _Q2_BLOCKED_SYMBOLS


def test_existing_targets_unchanged():
    # Surgical fix: only MGC was added, other symbols/targets untouched.
    assert _Q2_PAPER_TARGETS["MES"] == 30
    assert _Q2_PAPER_TARGETS["MCL"] == 60
    assert _Q2_PAPER_TARGETS["MNQ"] == 60
    assert _Q2_BLOCKED_SYMBOLS == {"MCL", "MNQ"}


class _FakeCursor:
    def __init__(self, count: int):
        self._count = count

    def fetchone(self):
        return (self._count,)


class _FakeConn:
    """Minimal context-manager stub matching `with get_db() as conn: conn.execute(...)`."""

    def __init__(self, counts_by_symbol: dict[str, int]):
        self._counts = counts_by_symbol

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, query: str, params: tuple):
        (symbol,) = params
        return _FakeCursor(self._counts.get(symbol, 0))


def test_counts_endpoint_includes_mgc(monkeypatch):
    from routers.paper_validation_router import get_paper_trade_counts

    fake = _FakeConn({"MES": 12, "MGC": 45, "MCL": 60, "MNQ": 3})
    monkeypatch.setattr("routers.paper_validation_router.get_db", lambda: fake)

    result = asyncio.run(get_paper_trade_counts())

    assert result["counts"]["MGC"] == {"closed": 45, "target": 60, "blocked": False}
    assert "MGC: 45/60" in result["display"]
    assert "MGC: 45/60 (blocked)" not in result["display"]
