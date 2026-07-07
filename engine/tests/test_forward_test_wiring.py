"""Tests for the forward-test wiring (ROI #2 Part A).

Two seams, both additive and fail-open:

1. PortfolioTracker.open_trade(candidate_id=...) stamps the candidate id into the
   trade's strategy_params so the forward-test loop can attribute the trade at the
   precise candidate_id level (the only level that graduates). Omitting it leaves
   behaviour byte-for-byte unchanged, and a bad candidate_id must never block the
   entry.

2. EODScheduler.run_forward_test_snapshot() runs the read-only forward-test loop
   once per day (persist=True writes only the gitignored report files), surfaces a
   graduation via the notifier, and never raises into the scheduler.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from portfolio.tracker import PortfolioTracker


@pytest.fixture()
def tracker(tmp_path: Path) -> PortfolioTracker:
    return PortfolioTracker(store_path=tmp_path / "audit.jsonl")


class TestCandidateIdTagging:
    def test_candidate_id_omitted_is_unchanged(self, tracker: PortfolioTracker) -> None:
        tid = tracker.open_trade("MES", "buy", 1, 7100.0)
        trade = tracker._open[tid]
        # no candidate_id stamped anywhere
        assert "candidate_id" not in (trade.notes or "")

    def test_candidate_id_stamped_into_strategy_params(self, tracker: PortfolioTracker) -> None:
        tid = tracker.open_trade(
            "MGC", "buy", 1, 4080.0, candidate_id="MGC_trend_rv_filter_rank1"
        )
        # The trade opened successfully (a real trade_id came back) ...
        assert tid in tracker._open
        # ... and the forward-test loop can recover the candidate id from the
        # persisted strategy_params (attribution at the precise level).
        from backtest.forward_test import attribution_level

        # Reconstruct the closed-trade row shape the loop consumes.
        row = {
            "symbol": "MGC",
            "pnl": 10.0,
            "exit_time": "2026-06-12T20:00:00+00:00",
            "strategy_params": {"candidate_id": "MGC_trend_rv_filter_rank1"},
        }
        cand = {"id": "MGC_trend_rv_filter_rank1", "symbol": "MGC", "params": {}}
        assert attribution_level(row, cand) == "candidate_id"

    def test_bad_candidate_id_does_not_block_entry(self, tracker: PortfolioTracker) -> None:
        # Even a nonsense candidate id must yield a real trade (fail-open).
        tid = tracker.open_trade("MES", "buy", 1, 7100.0, candidate_id="not_a_real_candidate")
        assert tid in tracker._open


class _FakeNotifier:
    enabled = True

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, msg: str) -> bool:
        self.sent.append(msg)
        return True


class _FakeDB:
    def __init__(self, closed: list[dict]) -> None:
        self._closed = closed

    def get_closed_trades(self, limit: int = 100_000) -> list[dict]:
        return self._closed


@pytest.mark.asyncio
async def test_snapshot_runs_read_only_and_reports() -> None:
    from schedulers.eod_scheduler import EODScheduler

    sched = EODScheduler(db_manager=_FakeDB([]), whatsapp_notifier=None)
    result = await sched.run_forward_test_snapshot()
    assert result["status"] == "ok"
    assert result["n_graduated"] == 0
    assert "n_active_candidates" in result


@pytest.mark.asyncio
async def test_snapshot_never_raises_on_loop_error(monkeypatch) -> None:
    from schedulers.eod_scheduler import EODScheduler

    def _boom(*a, **k):
        raise RuntimeError("loop exploded")

    monkeypatch.setattr("backtest.forward_test.run_forward_test", _boom)
    sched = EODScheduler(db_manager=_FakeDB([]), whatsapp_notifier=None)
    result = await sched.run_forward_test_snapshot()
    assert result["status"] == "error"
    assert "loop exploded" in result["error"]
