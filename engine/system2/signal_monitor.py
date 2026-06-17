"""
System 2 — Signal Monitor
=========================
Continuously fetches 1h bars for ES and NQ, detects the three-stage
sequential signal pattern, and fires a callback when a setup completes.

Sequential signal pattern (must be in order, no bar skipping):
  Stage 1: compressed == True                   (Phase Compression active)
  Stage 2: atr_trigger_bull == True             (within 6 bars of compression)
  Stage 3: bullish_single == True on NEXT bar   (exactly +1 bar after ATR trigger)
  → ENTRY: close of Stage 3 bar

Session filter: EXTENDED HOURS ONLY — 16:00 to 09:30 ET
  (RTH 09:30–16:00 excluded — historically 3-4/7 gates, not tradeable)

Data source: yfinance (1h bars, max 730-day history)
Poll interval: Configurable, default 60s. In production set to align near bar close.
"""

import asyncio
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Callable, Coroutine, Optional
from zoneinfo import ZoneInfo

import pandas as pd
import numpy as np

# TOS indicators live in strategy_c
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strategy_c.tos_indicators import SatyATRLevels, PhaseCompression, CoreySinglefinder

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")

# ── Session constants ─────────────────────────────────────────────────────────
# Extended hours = after-hours (16:00–24:00) + overnight (00:00–09:30)
# RTH = 09:30–16:00 — DO NOT TRADE
_RTH_START = time(9, 30)
_RTH_END   = time(16, 0)


def _is_extended_hours(ts: datetime) -> bool:
    """Return True if timestamp falls in extended hours (not RTH)."""
    local = ts.astimezone(ET)
    t = local.time()
    # RTH = 09:30 <= t < 16:00  →  extended = everything else
    return not (_RTH_START <= t < _RTH_END)


# ── Signal dataclass ──────────────────────────────────────────────────────────
@dataclass
class System2Signal:
    """Fired when a complete sequential setup is detected."""
    symbol: str           # "ES" or "NQ"
    entry_price: float    # close of Singlefinder bar
    atr: float            # ATR14 at entry bar (used by order manager for stops/targets)
    direction: str        # "LONG" (bearish singles not traded in initial pass)
    bar_time: datetime    # timestamp of the entry bar (UTC)
    stage1_bar: datetime  # when compression was True
    stage2_bar: datetime  # when ATR trigger fired
    stage3_bar: datetime  # Singlefinder bar (= entry)
    prev_close: float     # prev_close at entry bar (for ATR level reference)

    # Derived levels (pre-computed for order manager convenience)
    stop_price: float = field(init=False)
    t1_price: float   = field(init=False)
    t2_price: float   = field(init=False)

    def __post_init__(self):
        # Stop: 0.75 × ATR below entry
        self.stop_price = round(self.entry_price - 0.75 * self.atr, 2)
        # T1: 0.80 × ATR above entry
        self.t1_price   = round(self.entry_price + 0.80 * self.atr, 2)
        # T2: 2.00 × ATR above entry
        self.t2_price   = round(self.entry_price + 2.00 * self.atr, 2)

    def summary(self) -> str:
        return (
            f"[System2Signal] {self.symbol} LONG @ {self.entry_price:.2f} | "
            f"Stop={self.stop_price:.2f}  T1={self.t1_price:.2f}  T2={self.t2_price:.2f} | "
            f"ATR={self.atr:.2f} | bar={self.bar_time.strftime('%Y-%m-%d %H:%M ET')}"
        )


# ── State machine per symbol ──────────────────────────────────────────────────
@dataclass
class _DetectionState:
    """Tracks sequential detection state for one symbol."""
    symbol: str
    # Stage 1 state
    last_compressed_bar: Optional[datetime] = None
    compressed_bar_index: Optional[int] = None
    # Stage 2 state
    atr_trigger_bar: Optional[datetime] = None
    atr_trigger_bar_index: Optional[int] = None
    # Stage 3 pending: we have ATR trigger, waiting exactly 1 bar for SF
    waiting_for_sf: bool = False
    # How many bars since stage 1 (to enforce 6-bar window for ATR trigger)
    bars_since_compression: int = 0

    def reset(self):
        self.last_compressed_bar = None
        self.compressed_bar_index = None
        self.atr_trigger_bar = None
        self.atr_trigger_bar_index = None
        self.waiting_for_sf = False
        self.bars_since_compression = 0


# ── Signal Monitor ────────────────────────────────────────────────────────────
class System2SignalMonitor:
    """
    Monitors ES and NQ on 1h bars for the sequential compression setup.

    Usage:
        monitor = System2SignalMonitor(on_signal=my_async_callback)
        await monitor.run()

    The on_signal callback receives a System2Signal and should be non-blocking
    (or itself async). The monitor continues polling after firing.

    Parameters
    ----------
    symbols        : list of futures root symbols to monitor (default: ES, NQ)
    poll_interval  : seconds between bar fetches (default: 60s)
    compression_window : max bars between Stage 1 and Stage 2 (default: 6)
    dry_run        : if True, log signals but don't invoke callback
    """

    DEFAULT_SYMBOLS = ["ES", "NQ"]

    def __init__(
        self,
        on_signal: Optional[Callable[[System2Signal], Coroutine]] = None,
        symbols: Optional[list] = None,
        poll_interval: int = 60,
        compression_window: int = 6,
        dry_run: bool = False,
    ):
        self.on_signal = on_signal
        self.symbols = symbols or self.DEFAULT_SYMBOLS
        self.poll_interval = poll_interval
        self.compression_window = compression_window
        self.dry_run = dry_run
        self._running = False
        self._states: dict[str, _DetectionState] = {
            sym: _DetectionState(symbol=sym) for sym in self.symbols
        }
        # Tick sizes for rounding
        self._tick: dict[str, float] = {"ES": 0.25, "NQ": 0.25}
        # yfinance ticker map (nearest front contract approximation)
        self._yf_map: dict[str, str] = {"ES": "ES=F", "NQ": "NQ=F"}

        # TOS indicator instances (shared, stateless compute)
        self._phase = PhaseCompression()
        self._atr   = SatyATRLevels()
        self._sf    = CoreySinglefinder()

    # ── Data fetch ────────────────────────────────────────────────────────────
    def _fetch_bars(self, symbol: str, lookback_bars: int = 120) -> Optional[pd.DataFrame]:
        """
        Fetch 1h OHLCV bars via yfinance.
        Returns None on error. Columns normalized to lowercase.
        """
        try:
            import yfinance as yf
            ticker = self._yf_map.get(symbol, f"{symbol}=F")
            raw = yf.download(ticker, period="60d", interval="1h",
                              progress=False, auto_adjust=True)
            if raw.empty:
                logger.warning(f"[{symbol}] yfinance returned empty DataFrame")
                return None

            # Flatten multi-level columns if present
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)

            df = raw.copy()
            df.columns = [c.lower() for c in df.columns]

            # Ensure datetime index is tz-aware UTC
            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC")
            else:
                df.index = df.index.tz_convert("UTC")

            # Filter to last lookback_bars for signal computation
            # (keep more for indicator warm-up)
            return df.tail(max(lookback_bars, 80))

        except Exception as e:
            logger.error(f"[{symbol}] Bar fetch failed: {e}")
            return None

    # ── Indicator computation ─────────────────────────────────────────────────
    def _compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply all three TOS indicators to a bar DataFrame."""
        df = self._atr.compute(df)
        df = self._phase.compute(df)
        df = self._sf.compute(df)
        return df

    # ── Session filter ────────────────────────────────────────────────────────
    def _filter_extended_hours(self, df: pd.DataFrame) -> pd.DataFrame:
        """Keep only bars that fall in extended hours (not RTH)."""
        mask = df.index.map(_is_extended_hours)
        filtered = df[mask].copy()
        logger.debug(f"Extended-hours filter: {len(df)} → {len(filtered)} bars")
        return filtered

    # ── Sequential detection ─────────────────────────────────────────────────
    def _detect_signals(self, symbol: str, df: pd.DataFrame) -> list[System2Signal]:
        """
        Scan the (filtered, indicator-enriched) DataFrame for completed setups.
        Returns a list of System2Signal objects (typically 0 or 1 per scan).

        Detection is stateful: self._states[symbol] tracks progress across calls.
        Only the last N bars are scanned each call (new bars since last poll).
        """
        state = self._states[symbol]
        signals: list[System2Signal] = []

        # We process bars in chronological order
        for i, (ts, row) in enumerate(df.iterrows()):
            compressed       = bool(row.get("compressed", False))
            atr_trigger_bull = bool(row.get("atr_trigger_bull", False))
            bullish_single   = bool(row.get("bullish_single", False))
            atr14            = float(row.get("atr14", 0.0))
            prev_close_val   = float(row.get("prev_close", row.get("close", 0.0)))
            close_price      = float(row["close"])
            bar_ts: datetime = ts if isinstance(ts, datetime) else ts.to_pydatetime()

            # ── Stage 1: compression ─────────────────────────────────────────
            if compressed:
                # Renew compression window on each compressed bar
                state.last_compressed_bar  = bar_ts
                state.compressed_bar_index = i
                state.bars_since_compression = 0
                state.waiting_for_sf = False
                state.atr_trigger_bar = None
                state.atr_trigger_bar_index = None
                continue  # compression bar itself is never an ATR trigger (same bar)

            # If we have an active compression, track elapsed bars
            if state.last_compressed_bar is not None:
                state.bars_since_compression += 1

            # ── Stage 3: waiting for Singlefinder exactly 1 bar after trigger ─
            if state.waiting_for_sf:
                if bullish_single and atr14 > 0:
                    # Setup complete — build signal
                    sig = System2Signal(
                        symbol      = symbol,
                        entry_price = close_price,
                        atr         = atr14,
                        direction   = "LONG",
                        bar_time    = bar_ts,
                        stage1_bar  = state.last_compressed_bar,
                        stage2_bar  = state.atr_trigger_bar,
                        stage3_bar  = bar_ts,
                        prev_close  = prev_close_val,
                    )
                    signals.append(sig)
                    logger.info(sig.summary())
                # Either fired or missed — reset and look for next setup
                state.reset()
                continue

            # ── Stage 2: ATR trigger (within compression_window bars) ─────────
            if (
                state.last_compressed_bar is not None
                and atr_trigger_bull
                and 1 <= state.bars_since_compression <= self.compression_window
            ):
                state.atr_trigger_bar       = bar_ts
                state.atr_trigger_bar_index = i
                state.waiting_for_sf        = True
                logger.debug(
                    f"[{symbol}] Stage 2 ATR trigger @ {bar_ts} "
                    f"(+{state.bars_since_compression} bars from compression)"
                )
                continue

            # If ATR trigger not seen within window, reset stage 1
            if (
                state.last_compressed_bar is not None
                and state.bars_since_compression > self.compression_window
                and not state.waiting_for_sf
            ):
                logger.debug(
                    f"[{symbol}] Compression window expired "
                    f"({state.bars_since_compression} bars), resetting"
                )
                state.reset()

        return signals

    # ── Main poll loop ────────────────────────────────────────────────────────
    async def run(self):
        """Main monitoring loop. Runs until stop() is called."""
        self._running = True
        logger.info(
            f"[System2Monitor] Starting. Symbols={self.symbols} "
            f"poll={self.poll_interval}s dry_run={self.dry_run}"
        )

        while self._running:
            for symbol in self.symbols:
                try:
                    await self._poll_symbol(symbol)
                except Exception as e:
                    logger.error(f"[{symbol}] Poll error: {e}", exc_info=True)

            await asyncio.sleep(self.poll_interval)

    async def _poll_symbol(self, symbol: str):
        """Fetch bars, compute indicators, run detection for one symbol."""
        df = self._fetch_bars(symbol)
        if df is None or df.empty:
            return

        df = self._compute_indicators(df)
        df = self._filter_extended_hours(df)

        if df.empty:
            logger.debug(f"[{symbol}] No extended-hours bars after filter")
            return

        signals = self._detect_signals(symbol, df)

        for sig in signals:
            if self.dry_run:
                logger.info(f"[DRY RUN] Signal detected: {sig.summary()}")
            else:
                if self.on_signal:
                    await self.on_signal(sig)

    def stop(self):
        """Graceful shutdown."""
        self._running = False
        logger.info("[System2Monitor] Shutdown requested")

    # ── One-shot scan (for testing / manual trigger) ──────────────────────────
    def scan_now(self, symbol: str) -> list[System2Signal]:
        """
        Synchronous single scan — returns any detected signals.
        Useful for smoke testing without running the async loop.
        """
        df = self._fetch_bars(symbol)
        if df is None or df.empty:
            return []
        df = self._compute_indicators(df)
        df = self._filter_extended_hours(df)
        if df.empty:
            return []
        return self._detect_signals(symbol, df)
