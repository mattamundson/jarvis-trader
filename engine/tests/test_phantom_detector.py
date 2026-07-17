"""Automated pre-EOD phantom detector (flag-only) — regression tests (2026-07-02).

Where mark_phantom_trades.py applies a HARD-CODED list of known-bad trade IDs,
this detector FINDS suspicious closed trades automatically so Amo has a fresh
list to confirm-mark before the 20:05 UTC EOD snapshot counts them. It never
mutates a row: it only classifies. The three signals are self-contained (no live
price feed — which is currently BLIND) and map onto the real historical phantom
causes:

  * duplicate_key          — the same fill booked twice (dedup-suffix retries).
  * pnl_price_inconsistent — stored pnl doesn't match (exit-entry)*dir*mult*qty
                             (frozen/contaminated price, or a fabricated pnl).
  * entry_price_outlier    — entry deviates from the robust median of that
                             symbol's other closed trades (the classic
                             MES 7398.5481-in-a-5600-market contamination),
                             using the trades themselves as the reference.

Already-resolved rows (status phantom/cancelled/void) are never re-flagged.
"""

from __future__ import annotations

import os
import sqlite3
import sys

import pytest

_TEST_ENV = {
    "API_KEY": "test-key",
    "POSTGRES_URL": "postgresql://test:test@localhost/test",
    "REDIS_URL": "redis://localhost",
    "POLYGON_API_KEY": "test-key",
    "ANTHROPIC_API_KEY": "test-key",
    "TRADINGVIEW_WEBHOOK_SECRET": "jarvis_test_secret_12345",
}
for _k, _v in _TEST_ENV.items():
    os.environ.setdefault(_k, _v)

_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

from analytics.phantom_detector import (  # noqa: E402
    Suspect,
    detect_suspect_closed_trades,
    detect_suspects,
)


def _trade(
    trade_id,
    *,
    symbol="MES",
    side="buy",
    qty=1,
    entry=5600.0,
    exit=5610.0,
    pnl=50.0,
    status="closed",
    key=None,
    exit_time="2026-07-02 15:00:00",
):
    return {
        "trade_id": trade_id,
        "symbol": symbol,
        "side": side,
        "quantity": qty,
        "entry_price": entry,
        "exit_price": exit,
        "pnl": pnl,
        "status": status,
        "idempotency_key": key if key is not None else f"idem-{trade_id}",
        "exit_time": exit_time,
    }


class TestDetectSuspectsPure:
    def test_clean_ledger_flags_nothing(self):
        # Three internally-consistent MES longs (+50 each), distinct keys, near price.
        trades = [
            _trade("t1", entry=5600, exit=5610, pnl=50),
            _trade("t2", entry=5602, exit=5612, pnl=50),
            _trade("t3", entry=5598, exit=5608, pnl=50),
        ]
        assert detect_suspects(trades) == []

    def test_duplicate_idempotency_key(self):
        # Same base key booked twice (retry suffix) → both flagged.
        trades = [
            _trade("t1", key="fill-abc"),
            _trade("t2", key="fill-abc-2"),
            _trade("t3", key="fill-xyz"),
        ]
        sus = {s.trade_id: s for s in detect_suspects(trades)}
        assert set(sus) == {"t1", "t2"}
        assert "duplicate_key" in sus["t1"].reasons
        assert sus["t1"].detail["duplicate_key"]["count"] == 2

    def test_pnl_price_inconsistent_frozen_exit(self):
        # Frozen exit==entry but a nonzero pnl booked (the -266.25 phantom shape).
        trades = [
            _trade("g1", entry=5600, exit=5610, pnl=50),
            _trade("g2", entry=5602, exit=5612, pnl=50),
            _trade("bad", entry=5600, exit=5600, pnl=-266.25),
        ]
        sus = {s.trade_id: s for s in detect_suspects(trades)}
        assert "bad" in sus
        assert "pnl_price_inconsistent" in sus["bad"].reasons
        assert sus["bad"].detail["pnl_price_inconsistent"]["expected_pnl"] == pytest.approx(0.0)

    def test_correct_short_is_not_flagged(self):
        # Short profits when price falls: (5600-5610)*(-1)*5*1 = 50. Consistent.
        trades = [
            _trade("s1", side="sell", entry=5610, exit=5600, pnl=50),
            _trade("s2", side="sell", entry=5612, exit=5602, pnl=50),
            _trade("s3", side="sell", entry=5608, exit=5598, pnl=50),
        ]
        assert detect_suspects(trades) == []

    def test_entry_price_outlier_vs_peers(self):
        # The classic contamination: one MES entry way off the same-day cluster,
        # where the contamination is the MINORITY (1 of 4) so the median is clean.
        trades = [
            _trade("r1", entry=5600, exit=5610, pnl=50),
            _trade("r2", entry=5602, exit=5612, pnl=50),
            _trade("r3", entry=5598, exit=5608, pnl=50),
            # Contaminated entry; keep its own pnl consistent so ONLY signal C fires.
            _trade("bad", entry=7398.5481, exit=7398.5481, pnl=0.0, key="fill-solo"),
        ]
        sus = {s.trade_id: s for s in detect_suspects(trades, enable_price_outlier=True)}
        assert set(sus) == {"bad"}
        assert "entry_price_outlier" in sus["bad"].reasons
        assert sus["bad"].detail["entry_price_outlier"]["peer_median"] == pytest.approx(5601.0)

    def test_price_outlier_is_off_by_default(self):
        # Same contamination, but the outlier signal is OFF by default → the
        # (internally pnl-consistent) contaminated row is NOT flagged. This pins
        # the honest default: no confident-but-wrong flag from a thin-day median.
        trades = [
            _trade("r1", entry=5600, exit=5610, pnl=50),
            _trade("r2", entry=5602, exit=5612, pnl=50),
            _trade("bad", entry=7398.5481, exit=7398.5481, pnl=0.0, key="fill-solo"),
        ]
        assert detect_suspects(trades) == []

    def test_resolved_statuses_never_flagged(self):
        # A phantom-marked duplicate must not re-appear as a suspect.
        trades = [
            _trade("t1", key="fill-abc"),
            _trade("t2", key="fill-abc-2", status="phantom"),
        ]
        assert detect_suspects(trades) == []

    def test_min_peers_guard_skips_outlier_without_reference(self):
        # Only 2 same-symbol trades → no robust reference → no outlier flag.
        trades = [
            _trade("t1", symbol="MGC", entry=2000, exit=2001, pnl=10, key="k1"),
            _trade("t2", symbol="MGC", entry=4705, exit=4705, pnl=0.0, key="k2"),
        ]
        # (2 peers < min_peers=3) → C silent; both consistent → B silent.
        assert detect_suspects(trades, enable_price_outlier=True) == []

    def test_entry_exit_excursion_flags_wrong_era_entry_with_no_peers(self):
        # The real 2026-07-17 phantom (paper_trades id=296): a 2024-era 5299.875
        # entry against a correct 7512.50 exit, booking a fictional -$11,063.12
        # that tripped the daily_loss_limit kill switch.
        #
        # Presented ALONE — no peers — because that is the real condition: MES
        # exits exactly 1 trade per day, so Signal C's min_peers=3 same-day group
        # never forms. Signal B is silent too: (5299.875-7512.5)*-1*5*1 is
        # -11063.12 to the cent, so the pnl is internally consistent. D is the
        # only signal that can see this, and it must see it unaided.
        trades = [_trade("phantom296", side="sell", entry=5299.875, exit=7512.5, pnl=-11063.12)]
        sus = {s.trade_id: s for s in detect_suspects(trades)}
        assert set(sus) == {"phantom296"}
        assert sus["phantom296"].reasons == ["entry_exit_excursion"]
        assert sus["phantom296"].detail["entry_exit_excursion"]["deviation_pct"] == pytest.approx(
            0.4175, abs=1e-4
        )

    def test_excursion_does_not_flag_worst_genuine_trade(self):
        # paper_trades id=292 — the LARGEST real intra-trade move in the whole
        # closed MES ledger (7483.0 -> 7615.25, +$659.75, dev 1.77%). If the
        # threshold ever false-positives on a real trade, it starts here.
        trades = [_trade("real292", entry=7483.0, exit=7615.25, pnl=661.25)]
        assert detect_suspects(trades) == []

    def test_excursion_skips_rows_without_a_usable_exit(self):
        # Open/partial rows carry exit_price NULL (and 0.0 shows up in the real
        # ledger too). Neither is contamination evidence — skip, never divide.
        trades = [
            _trade("open1", entry=7500.0, exit=None, pnl=None),
            _trade("zero1", entry=7500.0, exit=0.0, pnl=None, key="k-zero"),
        ]
        assert detect_suspects(trades) == []

    def test_excursion_never_reflags_resolved_rows(self):
        # id=296 is now status='phantom'. The suspect list must shrink as rows
        # are confirm-marked, not re-surface them at every EOD.
        trades = [
            _trade(
                "phantom296",
                side="sell",
                entry=5299.875,
                exit=7512.5,
                pnl=-11063.12,
                status="phantom",
            ),
        ]
        assert detect_suspects(trades) == []

    def test_commission_net_pnl_is_not_flagged_as_fabrication(self):
        # Real closed rows (ids 294/289/288/290 on 2026-07-17). tracker.py:423
        # stores pnl NET of a $1.50/unit round-trip commission while Signal B's
        # `expected` is GROSS, so each sits exactly commission*qty below expected
        # and used to trip pnl_price_inconsistent. Cost is not fabrication.
        trades = [
            # AAPL 1sh: gross -1.6369, stored -3.1369 (1 x $1.50).
            _trade("aapl294", symbol="AAPL", entry=327.02, exit=325.3831, pnl=-3.1369, key="k1"),
            # MES 1ct short: gross +43.75, stored +42.25.
            _trade("mes289", side="sell", entry=7563.0, exit=7554.25, pnl=42.25, key="k2"),
            # TSLA 2sh: gross -5.0562, stored -8.0562 (2 x $1.50).
            _trade(
                "tsla290", symbol="TSLA", qty=2, entry=393.12, exit=390.5919, pnl=-8.0562, key="k3"
            ),
        ]
        assert detect_suspects(trades) == []

    def test_fabricated_pnl_still_caught_through_the_commission_band(self):
        # The widened band must not become a hiding place. The real -266.25
        # frozen-exit phantom shape clears one commission by ~177x.
        trades = [_trade("bad", entry=5600, exit=5600, pnl=-266.25)]
        sus = {s.trade_id: s for s in detect_suspects(trades)}
        assert "pnl_price_inconsistent" in sus["bad"].reasons

    def test_reasons_accumulate_on_one_trade(self):
        # A duplicate that is ALSO price-inconsistent carries both reasons.
        trades = [
            _trade("t1", key="dup"),
            _trade("t2", key="dup-2", entry=5600, exit=5600, pnl=999.0),
            _trade("t3", key="other"),
        ]
        sus = {s.trade_id: s for s in detect_suspects(trades)}
        assert "duplicate_key" in sus["t2"].reasons
        assert "pnl_price_inconsistent" in sus["t2"].reasons


class TestDetectSuspectClosedTradesDb:
    """DB-backed wrapper: pull closed ledger, flag, optionally scope to a date."""

    def _mgr(self, tmp_path):
        from database.schema import DatabaseManager

        path = str(tmp_path / "phantom.db")
        db = DatabaseManager(db_path=path)
        db.initialize()
        return db, path

    def _ins(self, path, t):
        conn = sqlite3.connect(path)
        try:
            conn.execute(
                """INSERT INTO paper_trades
                   (trade_id, symbol, side, quantity, entry_price, exit_price,
                    entry_time, exit_time, pnl, status, idempotency_key)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    t["trade_id"],
                    t["symbol"],
                    t["side"],
                    t["quantity"],
                    t["entry_price"],
                    t["exit_price"],
                    t["exit_time"],
                    t["exit_time"],
                    t["pnl"],
                    t["status"],
                    t["idempotency_key"],
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def test_wrapper_scopes_to_date(self, tmp_path):
        db, path = self._mgr(tmp_path)
        # Yesterday: a clean cluster. Today: same cluster + one contaminated entry.
        for i, e in enumerate((5600, 5602, 5598)):
            self._ins(
                path,
                _trade(
                    f"y{i}",
                    entry=e,
                    exit=e + 10,
                    pnl=50,
                    exit_time="2026-07-01 15:00:00",
                    key=f"y{i}",
                ),
            )
        for i, e in enumerate((5600, 5602, 5598)):
            self._ins(
                path,
                _trade(
                    f"t{i}",
                    entry=e,
                    exit=e + 10,
                    pnl=50,
                    exit_time="2026-07-02 15:00:00",
                    key=f"t{i}",
                ),
            )
        self._ins(
            path,
            _trade(
                "bad",
                entry=7398.5481,
                exit=7398.5481,
                pnl=0.0,
                exit_time="2026-07-02 16:00:00",
                key="bad",
            ),
        )

        # Scoped to today → only today's contaminated trade surfaces (outlier
        # signal opted in; the contamination is the minority of the day's 4).
        today = detect_suspect_closed_trades(db, on_date="2026-07-02", enable_price_outlier=True)
        assert [s.trade_id for s in today] == ["bad"]
        # Yesterday's ledger is clean.
        assert (
            detect_suspect_closed_trades(db, on_date="2026-07-01", enable_price_outlier=True) == []
        )

    def test_wrapper_unscoped_returns_all_suspects(self, tmp_path):
        db, path = self._mgr(tmp_path)
        self._ins(path, _trade("t1", key="dup", exit_time="2026-07-02 15:00:00"))
        self._ins(path, _trade("t2", key="dup-2", exit_time="2026-07-02 15:01:00"))
        out = detect_suspect_closed_trades(db)
        assert {s.trade_id for s in out} == {"t1", "t2"}


def test_suspect_as_dict_roundtrip():
    s = Suspect(trade_id="x", symbol="MES", pnl=1.0, reasons=["duplicate_key"])
    d = s.as_dict()
    assert d["trade_id"] == "x" and d["reasons"] == ["duplicate_key"]


class TestEodPhantomWiring:
    """run_eod_snapshot attaches a flag-only suspect list without mutating rows."""

    def _mgr(self, tmp_path):
        from database.schema import DatabaseManager

        path = str(tmp_path / "eod_phantom.db")
        db = DatabaseManager(db_path=path)
        db.initialize()
        return db, path

    def _ins(self, path, t):
        conn = sqlite3.connect(path)
        try:
            conn.execute(
                """INSERT INTO paper_trades
                   (trade_id, symbol, side, quantity, entry_price, exit_price,
                    entry_time, exit_time, pnl, status, idempotency_key)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    t["trade_id"],
                    t["symbol"],
                    t["side"],
                    t["quantity"],
                    t["entry_price"],
                    t["exit_price"],
                    t["exit_time"],
                    t["exit_time"],
                    t["pnl"],
                    t["status"],
                    t["idempotency_key"],
                ),
            )
            conn.commit()
        finally:
            conn.close()

    @pytest.mark.asyncio
    async def test_eod_attaches_suspects(self, tmp_path, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock

        import schedulers.eod_scheduler as eod_mod
        from schedulers.eod_scheduler import EODScheduler

        # Neutralise the WFE snapshot (module-level; hits the absent engine API
        # with slow connection-retry backoff) so the test is deterministic.
        monkeypatch.setattr(eod_mod, "_save_wfe_snapshots", AsyncMock(return_value=None))

        db, path = self._mgr(tmp_path)
        # A duplicate fill booked twice → detector should flag both.
        self._ins(path, _trade("d1", key="fill-dup", exit_time="2026-07-02 15:00:00"))
        self._ins(path, _trade("d2", key="fill-dup-2", exit_time="2026-07-02 15:01:00"))

        tracker = MagicMock()
        tracker.get_performance = MagicMock(
            return_value={"total_pnl": 100.0, "num_trades": 2, "win_rate": 1.0, "max_dd": -0.01}
        )
        tracker.get_positions = MagicMock(return_value=[])
        scheduler = EODScheduler(db_manager=db, portfolio_tracker=tracker)

        snapshot = await scheduler.run_eod_snapshot()

        flagged = {s["trade_id"] for s in snapshot.get("suspects", [])}
        assert {"d1", "d2"} <= flagged
        # Flag-only: the rows are untouched (still status='closed').
        assert db.get_trade_history(status="closed", limit=10)
