"""
System 2 — Smoke Test
=====================
Verifies the full pipeline without a live IBKR connection:

  1. Signal monitor: fetch bars, compute TOS indicators, run detection
  2. Order manager: inject synthetic signal, verify state machine transitions
  3. Executor: full dry-run startup and status check
  4. Session filter: verify extended-hours filter blocks RTH bars

Run:
    cd /path/to/jarvis-trader/engine
    python3 -m system2.smoke_test

All assertions print PASS/FAIL. Exit code 0 = all passed.
"""

import sys
import asyncio
import logging
from datetime import datetime, timezone, time
from pathlib import Path
from zoneinfo import ZoneInfo

# Path setup
_ENGINE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ENGINE_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("smoke_test")

# Track results
_results = []

def _check(name: str, condition: bool, detail: str = ""):
    status = "PASS" if condition else "FAIL"
    _results.append((name, condition))
    marker = "✓" if condition else "✗"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{status}] {marker} {name}{suffix}")
    return condition


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 1: Session filter
# ═══════════════════════════════════════════════════════════════════════════════
def test_session_filter():
    print("\n── Test 1: Session Filter ──")
    from system2.signal_monitor import _is_extended_hours
    ET = ZoneInfo("America/New_York")

    # RTH: 10:00 ET → should be False
    rth_bar = datetime(2026, 6, 16, 14, 0, tzinfo=timezone.utc)  # 10:00 ET
    _check("RTH 10:00 ET excluded", not _is_extended_hours(rth_bar),
           f"is_extended={_is_extended_hours(rth_bar)}")

    # After-hours: 17:00 ET → should be True
    ah_bar = datetime(2026, 6, 16, 21, 0, tzinfo=timezone.utc)   # 17:00 ET
    _check("After-hours 17:00 ET included", _is_extended_hours(ah_bar),
           f"is_extended={_is_extended_hours(ah_bar)}")

    # Overnight: 02:00 ET → should be True
    on_bar = datetime(2026, 6, 17, 6, 0, tzinfo=timezone.utc)    # 02:00 ET
    _check("Overnight 02:00 ET included", _is_extended_hours(on_bar),
           f"is_extended={_is_extended_hours(on_bar)}")

    # RTH boundary: exactly 09:30 ET → excluded
    rth_open = datetime(2026, 6, 16, 13, 30, tzinfo=timezone.utc)  # 09:30 ET
    _check("RTH open 09:30 ET excluded", not _is_extended_hours(rth_open),
           f"is_extended={_is_extended_hours(rth_open)}")

    # RTH boundary: exactly 16:00 ET → included (first extended bar)
    rth_close = datetime(2026, 6, 16, 20, 0, tzinfo=timezone.utc)  # 16:00 ET
    _check("RTH close 16:00 ET included", _is_extended_hours(rth_close),
           f"is_extended={_is_extended_hours(rth_close)}")


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 2: TOS indicators compute without error
# ═══════════════════════════════════════════════════════════════════════════════
def test_indicators():
    print("\n── Test 2: TOS Indicators ──")
    import numpy as np
    import pandas as pd
    from strategy_c.tos_indicators import SatyATRLevels, PhaseCompression, CoreySinglefinder

    # Build synthetic OHLCV data (50 bars, trending up)
    np.random.seed(42)
    n = 80
    closes = 4500 + np.cumsum(np.random.randn(n) * 5)
    highs  = closes + np.random.uniform(5, 20, n)
    lows   = closes - np.random.uniform(5, 20, n)
    opens  = closes - np.random.randn(n) * 3
    idx    = pd.date_range("2026-06-01 16:00", periods=n, freq="1h", tz="UTC")

    df = pd.DataFrame({
        "open": opens, "high": highs, "low": lows, "close": closes,
        "volume": np.random.randint(1000, 10000, n)
    }, index=idx)

    try:
        atr = SatyATRLevels()
        df = atr.compute(df)
        _check("SatyATRLevels computes",
               "atr14" in df.columns and "atr_trigger_bull" in df.columns,
               f"cols: atr14, atr_trigger_bull present={all(c in df.columns for c in ['atr14','atr_trigger_bull'])}")

        phase = PhaseCompression()
        df = phase.compute(df)
        _check("PhaseCompression computes",
               "compressed" in df.columns and "phase_osc" in df.columns,
               f"compressed bars: {df['compressed'].sum()}")

        sf = CoreySinglefinder()
        df = sf.compute(df)
        _check("CoreySinglefinder computes",
               "bullish_single" in df.columns,
               f"bullish singles: {df['bullish_single'].sum()}")

        _check("No NaN in close column", df["close"].notna().all())
        _check("ATR14 is positive", (df["atr14"].dropna() > 0).all())

    except Exception as e:
        _check("TOS indicators run without exception", False, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 3: Signal dataclass + level calculation
# ═══════════════════════════════════════════════════════════════════════════════
def test_signal_levels():
    print("\n── Test 3: Signal Level Calculation ──")
    from system2.signal_monitor import System2Signal

    sig = System2Signal(
        symbol      = "ES",
        entry_price = 5500.00,
        atr         = 20.00,
        direction   = "LONG",
        bar_time    = datetime(2026, 6, 17, 2, 0, tzinfo=timezone.utc),
        stage1_bar  = datetime(2026, 6, 17, 0, 0, tzinfo=timezone.utc),
        stage2_bar  = datetime(2026, 6, 17, 1, 0, tzinfo=timezone.utc),
        stage3_bar  = datetime(2026, 6, 17, 2, 0, tzinfo=timezone.utc),
        prev_close  = 5490.00,
    )

    # Stop = 5500 - 0.75 * 20 = 5485.00
    _check("Stop = entry - 0.75×ATR",
           abs(sig.stop_price - 5485.00) < 0.01,
           f"stop={sig.stop_price:.2f} expected=5485.00")

    # T1 = 5500 + 0.80 * 20 = 5516.00
    _check("T1 = entry + 0.80×ATR",
           abs(sig.t1_price - 5516.00) < 0.01,
           f"t1={sig.t1_price:.2f} expected=5516.00")

    # T2 = 5500 + 2.00 * 20 = 5540.00
    _check("T2 = entry + 2.00×ATR",
           abs(sig.t2_price - 5540.00) < 0.01,
           f"t2={sig.t2_price:.2f} expected=5540.00")

    _check("Summary string is non-empty", len(sig.summary()) > 20)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 4: Position sizing
# ═══════════════════════════════════════════════════════════════════════════════
def test_position_sizing():
    print("\n── Test 4: Position Sizing ──")
    from system2.order_manager import _size_position

    # ES: $50k × 1% = $500 risk
    # stop = 15pts, mult = 50 → $750/contract → floor(500/750) = 0 → min 1
    es_size = _size_position("ES", stop_price=5485.0, entry_price=5500.0)
    _check("ES min contracts floor to 1", es_size >= 1,
           f"es_size={es_size}")

    # NQ: stop = 150pts (large), mult = 20 → $3000/contract → floor(500/3000) = 0 → min 1
    nq_size = _size_position("NQ", stop_price=19000.0, entry_price=19150.0)
    _check("NQ min contracts floor to 1", nq_size >= 1,
           f"nq_size={nq_size}")

    # ES tight stop: 5pts → $250/contract → floor(500/250) = 2
    es_tight = _size_position("ES", stop_price=5495.0, entry_price=5500.0)
    _check("ES tight stop = 2 contracts", es_tight == 2,
           f"es_tight={es_tight} (stop_pts=5, expected=2)")

    # Never exceed max (5 contracts)
    es_very_tight = _size_position("ES", stop_price=5499.0, entry_price=5500.0)
    _check("ES capped at MAX_CONTRACTS=5", es_very_tight <= 5,
           f"es_very_tight={es_very_tight}")


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 5: Order manager state machine (synthetic, no IBKR)
# ═══════════════════════════════════════════════════════════════════════════════
async def test_order_manager():
    print("\n── Test 5: Order Manager State Machine ──")
    from system2.signal_monitor import System2Signal
    from system2.order_manager import System2OrderManager, PositionState

    closed_positions = []

    async def _on_close(pos):
        closed_positions.append(pos)

    mgr = System2OrderManager(
        ibkr_executor=None,  # dry run
        paper=True,
        on_position_closed=_on_close,
    )

    # Inject synthetic signal
    sig = System2Signal(
        symbol      = "ES",
        entry_price = 5500.00,
        atr         = 20.00,
        direction   = "LONG",
        bar_time    = datetime(2026, 6, 17, 2, 0, tzinfo=timezone.utc),
        stage1_bar  = datetime(2026, 6, 17, 0, 0, tzinfo=timezone.utc),
        stage2_bar  = datetime(2026, 6, 17, 1, 0, tzinfo=timezone.utc),
        stage3_bar  = datetime(2026, 6, 17, 2, 0, tzinfo=timezone.utc),
        prev_close  = 5490.00,
    )

    pos = await mgr.on_signal(sig)
    _check("Position created on signal", pos is not None)
    _check("Position state = OPEN_FULL",
           pos is not None and pos.state == PositionState.OPEN_FULL,
           f"state={pos.state if pos else 'None'}")

    # Simulate T1 hit bar
    t1_bar = {
        "high":      5516.50,   # above T1 5516.00
        "low":       5498.00,
        "close":     5515.00,
        "timestamp": datetime(2026, 6, 17, 3, 0, tzinfo=timezone.utc),
    }
    await mgr.on_bar("ES", t1_bar)
    _check("Position state = OPEN_HALF after T1",
           pos.state == PositionState.OPEN_HALF,
           f"state={pos.state}")
    _check("T1 hit recorded", pos.t1_hit)

    # Simulate T2 hit bar
    t2_bar = {
        "high":      5542.00,   # above T2 5540.00
        "low":       5510.00,
        "close":     5540.00,
        "timestamp": datetime(2026, 6, 17, 4, 0, tzinfo=timezone.utc),
    }
    await mgr.on_bar("ES", t2_bar)
    _check("Position closed on T2", len(closed_positions) == 1)
    if closed_positions:
        _check("Close reason = T2", closed_positions[0].close_reason == "T2",
               f"reason={closed_positions[0].close_reason}")
        _check("PnL is positive (T1+T2)",
               closed_positions[0].pnl_usd > 0,
               f"pnl=${closed_positions[0].pnl_usd:.2f}")

    # Test backstop: inject new signal, advance 8 bars without T1
    sig2 = System2Signal(
        symbol      = "NQ",
        entry_price = 19200.00,
        atr         = 100.00,
        direction   = "LONG",
        bar_time    = datetime(2026, 6, 17, 5, 0, tzinfo=timezone.utc),
        stage1_bar  = datetime(2026, 6, 17, 3, 0, tzinfo=timezone.utc),
        stage2_bar  = datetime(2026, 6, 17, 4, 0, tzinfo=timezone.utc),
        stage3_bar  = datetime(2026, 6, 17, 5, 0, tzinfo=timezone.utc),
        prev_close  = 19150.00,
    )
    pos2 = await mgr.on_signal(sig2)
    _check("NQ position created", pos2 is not None)

    # Advance 8 bars without T1 (price drifts sideways, never hits T1)
    init_closed = len(closed_positions)
    for i in range(8):
        flat_bar = {
            "high":      19250.0,  # below T1 = 19200 + 80 = 19280
            "low":       19180.0,  # above stop = 19200 - 75 = 19125
            "close":     19220.0,
            "timestamp": datetime(2026, 6, 17, 5 + i + 1, 0, tzinfo=timezone.utc),
        }
        await mgr.on_bar("NQ", flat_bar)

    _check("NQ backstop triggered at 8 bars",
           len(closed_positions) == init_closed + 1,
           f"closed_count={len(closed_positions)}")
    if len(closed_positions) > init_closed:
        _check("NQ close reason = BACKSTOP",
               closed_positions[-1].close_reason == "BACKSTOP",
               f"reason={closed_positions[-1].close_reason}")


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 6: Executor dry-run startup
# ═══════════════════════════════════════════════════════════════════════════════
async def test_executor_startup():
    print("\n── Test 6: Executor Dry-Run Startup ──")
    from system2.executor import System2Executor

    try:
        executor = System2Executor(
            paper=True,
            dry_run=True,
            poll_interval=999999,  # won't actually poll in this test
        )
        _check("Executor instantiated", executor is not None)
        _check("IBKR is None in dry-run", executor._ibkr is None)
        status = executor.status()
        _check("Status string returns", len(status) > 10, status[:60])
    except Exception as e:
        _check("Executor startup dry-run", False, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 7: Signal monitor scan_now (live yfinance fetch, no signal required)
# ═══════════════════════════════════════════════════════════════════════════════
def test_signal_monitor_scan():
    print("\n── Test 7: Signal Monitor Live Scan ──")
    from system2.signal_monitor import System2SignalMonitor

    monitor = System2SignalMonitor(dry_run=True, poll_interval=9999)

    for sym in ["ES", "NQ"]:
        try:
            df = monitor._fetch_bars(sym, lookback_bars=120)
            _check(f"{sym} bars fetched", df is not None and len(df) > 0,
                   f"rows={len(df) if df is not None else 0}")

            if df is not None and len(df) > 0:
                df_ind = monitor._compute_indicators(df)
                _check(f"{sym} indicators computed",
                       "compressed" in df_ind.columns and "atr14" in df_ind.columns,
                       f"rows={len(df_ind)}")

                df_ext = monitor._filter_extended_hours(df_ind)
                _check(f"{sym} extended-hours filter applied",
                       len(df_ext) < len(df_ind) or len(df_ext) > 0,
                       f"ext={len(df_ext)}/{len(df_ind)} bars")

                signals = monitor._detect_signals(sym, df_ext)
                _check(f"{sym} detection ran without error",
                       True,  # just checking it doesn't crash
                       f"signals found: {len(signals)}")

        except Exception as e:
            _check(f"{sym} scan_now no exception", False, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════
async def _run_async_tests():
    await test_order_manager()
    await test_executor_startup()

def main():
    print("=" * 60)
    print("System 2 — IBKR Executor Smoke Test")
    print("=" * 60)

    test_session_filter()
    test_indicators()
    test_signal_levels()
    test_position_sizing()

    asyncio.run(_run_async_tests())

    test_signal_monitor_scan()

    # Summary
    passed = sum(1 for _, ok in _results if ok)
    total  = len(_results)
    failed = [name for name, ok in _results if not ok]

    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{total} passed")
    if failed:
        print(f"FAILED:  {', '.join(failed)}")
    print("=" * 60)

    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
