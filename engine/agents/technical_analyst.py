"""
JARVIS TRADER — Technical Analyst Agent
=========================================
First agent in the pipeline. Analyzes OHLCV data using technical indicators
and produces a structured JSON report consumed by the downstream research agents.

Runs every 15 minutes during market hours.
Model: Claude Sonnet 4.6 (fast, cost-efficient for repeated analysis)
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

try:
    import pandas_ta as ta  # 150+ technical indicators

    PANDAS_TA_AVAILABLE = True
except ImportError:
    ta = None
    PANDAS_TA_AVAILABLE = False

from llm.client import resolve_agent_model
from utils.llm_json import parse_llm_json

logger = logging.getLogger(__name__)

# Minimum bars required for a full intraday analysis
_MIN_INTRADAY_BARS = 50
# Minimum daily bars needed for a degraded-but-useful daily fallback.
# Must be >= 15 so pandas_ta can produce ATRr_14 (requires 14 + 1 warmup bars).
_MIN_DAILY_BARS = 20


@dataclass
class TechnicalReport:
    """Structured output from the Technical Analyst agent"""

    symbol: str
    timestamp: datetime
    timeframe: str

    # Signal: -1.0 (strong sell) to +1.0 (strong buy)
    signal: float
    confidence: float  # 0.0 to 1.0

    # Individual indicator scores
    trend_score: float  # Based on MA crossovers, ADX
    momentum_score: float  # RSI, MACD, Stochastic
    volatility_score: float  # ATR, Bollinger Band position
    volume_score: float  # Volume vs average, OBV

    # Key levels
    support_levels: list[float] = field(default_factory=list)
    resistance_levels: list[float] = field(default_factory=list)
    current_price: float = 0.0

    # Human-readable analysis
    summary: str = ""
    reasoning: str = ""
    indicators: dict = field(default_factory=dict)

    # Market context
    is_overbought: bool = False
    is_oversold: bool = False
    trend: str = "neutral"  # "uptrend", "downtrend", "neutral", "ranging"
    regime: str = "unknown"  # "trending", "mean_reverting", "volatile"

    # Enhanced signal context (added for pipeline quality)
    stc_context: str = ""  # Human-readable STC signal state with actionable guidance
    mtf_alignment: str = ""  # One-line MTF summary: "4h and 1h STC aligned bullish" etc.
    regime_readiness: str = "UNKNOWN"  # READY | CAUTION | NOT_READY based on 5-layer alignment

    # StarkTPO deterministic signals (populated when bar data is available)
    stark_signal: str = ""  # e.g. "LONG_VAL_BOUNCE", "SHORT_VAH_REJECT", "HOLD", ""
    stark_structure: str = ""  # e.g. "INSIDE_VALUE", "BREAKOUT", "GAP_IMBALANCE", ""
    stark_poc: float = 0.0
    stark_vah: float = 0.0
    stark_val: float = 0.0

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "timeframe": self.timeframe,
            "signal": self.signal,
            "confidence": self.confidence,
            "trend_score": self.trend_score,
            "momentum_score": self.momentum_score,
            "volatility_score": self.volatility_score,
            "volume_score": self.volume_score,
            "support_levels": self.support_levels,
            "resistance_levels": self.resistance_levels,
            "current_price": self.current_price,
            "summary": self.summary,
            "reasoning": self.reasoning,
            "indicators": self.indicators,
            "is_overbought": self.is_overbought,
            "is_oversold": self.is_oversold,
            "trend": self.trend,
            "regime": self.regime,
            "stc_context": self.stc_context,
            "mtf_alignment": self.mtf_alignment,
            "regime_readiness": self.regime_readiness,
            "stark_signal": self.stark_signal,
            "stark_structure": self.stark_structure,
            "stark_poc": self.stark_poc,
            "stark_vah": self.stark_vah,
            "stark_val": self.stark_val,
        }


class TechnicalAnalystAgent:
    """
    Computes technical indicators and uses an LLM to synthesize them
    into a structured trading signal.

    Two-stage approach:
    1. Python computes all indicators deterministically (fast, no LLM)
    2. LLM synthesizes indicators into natural language analysis + signal score
    """

    SYSTEM_PROMPT = """You are a professional technical analyst for JARVIS TRADER,
an autonomous trading system.

Analyze the provided technical indicators and market data for the given symbol.
Produce a concise, structured analysis covering:
1. Overall trend direction and strength
2. Momentum signals (RSI, MACD, Stochastic)
3. Key support and resistance levels
4. Volume analysis
5. Market regime (trending/mean-reverting/volatile)
6. A composite signal score from -1.0 (strong sell) to +1.0 (strong buy)
7. Confidence level from 0.0 to 1.0

Respond with valid JSON only. Do not add any explanation outside the JSON.
"""

    def __init__(self, llm_client, data_manager):
        self._llm = llm_client
        self._data = data_manager

    async def analyze(
        self,
        symbol: str,
        timeframe: str = "15m",
        is_futures: bool = False,
        historical_context: str = "",
    ) -> TechnicalReport:
        """Full technical analysis pipeline for a symbol"""

        # 1. Fetch OHLCV data (intraday preferred)
        df = await self._data.get_bars(
            symbol, lookback_days=30, timeframe=timeframe, is_futures=is_futures
        )

        using_daily_fallback = False
        effective_timeframe = timeframe

        if df.empty or len(df) < _MIN_INTRADAY_BARS:
            logger.warning(
                f"Insufficient intraday data for {symbol} "
                f"({len(df) if not df.empty else 0} bars on {timeframe}). "
                f"Falling back to daily bars."
            )
            # --- Daily fallback: fetch ~1 year of daily bars for indicator depth ---
            df = await self._fetch_daily_fallback(symbol)
            if df.empty or len(df) < _MIN_DAILY_BARS:
                logger.error(f"Daily fallback also empty for {symbol} — returning empty report")
                # Last-ditch: still try to populate current_price via data_manager
                price = await self._fetch_current_price(symbol)
                report = self._empty_report(symbol, timeframe)
                report.current_price = price
                return report
            using_daily_fallback = True
            effective_timeframe = "1d (fallback)"

        # 2. Compute all indicators (deterministic Python — no LLM).
        # Offloaded to a worker thread so the deterministic CPU work doesn't block
        # the event loop. A failure here must degrade gracefully (empty/safe report),
        # never propagate out of analyze() and crash the pipeline caller — same
        # contract as the daily-fallback path above.
        try:
            indicators = await asyncio.to_thread(self._compute_indicators, df)
        except Exception as exc:  # noqa: BLE001 — degrade-not-crash is the invariant
            logger.error(
                f"Indicator computation failed for {symbol} on {effective_timeframe} "
                f"({exc!r}) — returning empty report"
            )
            price = await self._fetch_current_price(symbol)
            report = self._empty_report(symbol, timeframe)
            report.current_price = price
            return report

        # 2-rv. 20-bar annualized realized volatility (1h bars only).
        # Tags each pipeline run so paper trades accumulate rv_at_entry for
        # forward validation of the RV filter (gate: 60+ live trades).
        if not using_daily_fallback and len(df) >= 22:
            _log_ret = np.log(df["close"] / df["close"].shift(1))
            _rv_ann = _log_ret.rolling(20).std() * np.sqrt(252 * 24) * 100.0
            _rv_last = _rv_ann.iloc[-1]
            indicators["rv_20_ann_pct"] = round(float(_rv_last), 4) if pd.notna(_rv_last) else None
        else:
            indicators["rv_20_ann_pct"] = None

        # 2a. TradingView Live Indicator Injection (non-blocking)
        # Reads all JARVIS Pine Script indicators from TradingView Desktop
        # via MCP bridge. Falls back gracefully when TV is not running.
        try:
            from data.tradingview_feed import TradingViewFeed

            _tv_feed = TradingViewFeed()
            _tv_indicators = _tv_feed.get_all_indicators(symbol)
            if _tv_indicators:
                indicators.update(_tv_indicators)
                logger.info(
                    "[TechnicalAnalyst] %s — TV live data injected: "
                    "stc=%.1f composite=%.2f regime=%s",
                    symbol,
                    _tv_indicators.get("tv_stc") or 0,
                    _tv_indicators.get("tv_composite") or 0,
                    _tv_indicators.get("tv_regime") or "n/a",
                )
            else:
                indicators["tv_data_quality"] = "unavailable"
        except Exception as _tv_err:
            logger.debug("[TechnicalAnalyst] TV bridge error (non-fatal): %s", _tv_err)
            indicators["tv_data_quality"] = "unavailable"

        # 2a-gamma. Derive gamma-regime hints from the overlay levels. Additive:
        # when gamma fields are None (overlay not loaded), the hints stay None.
        _gamma_hints = _compute_gamma_regime_hints(indicators)
        indicators.update(_gamma_hints)
        if _gamma_hints.get("gex_regime"):
            logger.info(
                "[TechnicalAnalyst] %s — gamma regime=%s nearest_wall=%s@%.2f",
                symbol,
                _gamma_hints["gex_regime"],
                _gamma_hints.get("nearest_wall_side") or "n/a",
                _gamma_hints.get("nearest_wall") or 0.0,
            )

        # 2b. Composite signal enrichment for MES (and future composite instruments)
        try:
            from backtest.signals import COMPOSITE_INSTRUMENTS

            if symbol.upper() in COMPOSITE_INSTRUMENTS:
                from backtest.composite_signals import generate_composite_signals

                df_comp = await asyncio.to_thread(
                    generate_composite_signals, df.copy(), symbol=symbol.upper()
                )
                last = df_comp.iloc[-1]
                composite_meta = {}
                for col in (
                    "composite_regime",
                    "composite_score",
                    "stc_contrib",
                    "orb_contrib",
                    "vwap_contrib",
                    "composite_rr",
                    "entry_signal",
                    "bias",
                ):
                    if col in df_comp.columns:
                        val = last[col]
                        # Convert numpy types to native Python
                        if hasattr(val, "item"):
                            val = val.item()
                        # Replace nan/inf with None to keep JSON-serializable
                        import math

                        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
                            val = None
                        composite_meta[col] = val
                indicators["composite"] = composite_meta
                logger.info(f"Composite metadata added for {symbol}: {composite_meta}")
        except Exception as e:
            logger.debug(f"Composite signals not available for {symbol}: {e}")

        # 2c. StarkTPO deterministic signal (non-blocking)
        # Runs the Auction Market Theory / TPO profile on the intraday bar data.
        # Results are stored in indicators so they survive to _llm_synthesize and
        # are also hoisted to the top-level TechnicalReport fields (stark_signal,
        # stark_structure) so trader.py can access them via technical.get("stark_signal").
        _stark_result: dict = {}
        try:
            from strategies.stark_tpo_strategy import StarkTPOStrategy

            _stark = StarkTPOStrategy()
            # Normalise column names to lowercase before passing to StarkTPO
            _df_tpo = df.copy()
            _df_tpo.columns = [c.lower() for c in _df_tpo.columns]
            _stark_result = await asyncio.to_thread(_stark.evaluate_structure, _df_tpo)
            if _stark_result.get("ready"):
                indicators["stark_signal"] = _stark_result.get("actionable_signal", "HOLD")
                indicators["stark_structure"] = _stark_result.get("structure", "UNKNOWN")
                indicators["stark_poc"] = _stark_result.get("tpo_poc", 0.0)
                indicators["stark_vah"] = _stark_result.get("tpo_vah", 0.0)
                indicators["stark_val"] = _stark_result.get("tpo_val", 0.0)
                logger.info(
                    "[TechnicalAnalyst] %s — StarkTPO: signal=%s structure=%s "
                    "poc=%.2f vah=%.2f val=%.2f",
                    symbol,
                    indicators["stark_signal"],
                    indicators["stark_structure"],
                    indicators["stark_poc"] or 0.0,
                    indicators["stark_vah"] or 0.0,
                    indicators["stark_val"] or 0.0,
                )
            else:
                logger.debug(
                    "[TechnicalAnalyst] %s — StarkTPO: not ready (insufficient bars)", symbol
                )
        except Exception as _stark_err:
            logger.debug("[TechnicalAnalyst] StarkTPO skipped (non-fatal): %s", _stark_err)

        # 3. Always ensure current_price is populated.
        #    _compute_indicators sets it from the last close, but if that's still
        #    zero (e.g. pandas_ta not available and column missing), fall back to
        #    data_manager.get_current_price.
        if not indicators.get("current_price"):
            indicators["current_price"] = await self._fetch_current_price(symbol)

        # 3b. CRITICAL: If price is still 0 after all fallbacks, return a
        #     zero-weight abstention instead of sending price=$0 to the LLM.
        #     An LLM seeing price=$0.0 will produce a low-confidence bearish
        #     signal (0.25-0.35) which then drags down the whole pipeline.
        #     Missing price = abstention, NOT a bearish signal.
        current_price = indicators.get("current_price", 0.0)
        if not current_price or current_price <= 0.0:
            logger.warning(
                f"[TechnicalAnalyst] {symbol}: current_price=0 after all fallbacks — "
                "returning zero-weight abstention (not a bearish signal)"
            )
            report = self._no_price_report(symbol, timeframe)
            return report

        # 4. LLM synthesis
        report = await self._llm_synthesize(
            symbol, effective_timeframe, df, indicators, historical_context=historical_context
        )

        # 5. Tag the report when we used daily bars
        if using_daily_fallback:
            report.timeframe = timeframe  # preserve original timeframe in schema
            note = " [Using daily bars — market closed/after-hours]"
            if not report.summary.endswith(note):
                report.summary = report.summary + note

        return report

    # ------------------------------------------------------------------
    # Helper: fetch daily OHLCV bars via data_manager (daily fallback)
    # ------------------------------------------------------------------
    async def _fetch_daily_fallback(self, symbol: str) -> pd.DataFrame:
        """
        Fetch up to 1 year of daily bars via data_manager.get_bars().
        Returns a normalized DataFrame with lowercase OHLCV columns.
        """
        try:
            df = await self._data.get_bars(
                symbol, lookback_days=365, timeframe="1d", is_futures=True
            )
            if df is None or df.empty:
                logger.warning(f"data_manager daily fetch returned empty for {symbol}")
                return pd.DataFrame()
            df = df.copy()
            df.columns = [c.lower() for c in df.columns]
            logger.info(f"Daily fallback: fetched {len(df)} daily bars for {symbol}")
            return df
        except Exception as e:
            logger.error(f"_fetch_daily_fallback failed for {symbol}: {e}")
            return pd.DataFrame()

    # ------------------------------------------------------------------
    # Helper: fetch current price via data_manager with layered fallbacks
    # ------------------------------------------------------------------
    async def _fetch_current_price(self, symbol: str) -> float:
        """
        Returns the best available price for symbol via data_manager.get_current_price().
        Falls back to 0.0 on any error.
        """
        try:
            result = await self._data.get_current_price(symbol)
            price = result.get("last_price") or 0.0
            if price > 0:
                logger.info(
                    f"Current price for {symbol} from data_manager: {price} "
                    f"(source={result.get('source', 'unknown')})"
                )
                return float(price)
        except Exception as e:
            logger.warning(f"_fetch_current_price failed for {symbol}: {e}")
        return 0.0

    @staticmethod
    def _format_composite_section(indicators: dict) -> str:
        """Format composite signal metadata for the LLM prompt (if available)."""
        comp = indicators.get("composite")
        if not comp:
            return ""
        lines = [
            "",
            "COMPOSITE SIGNAL (STC+ORB+VWAP regime-adaptive):",
            f"- Regime: {comp.get('composite_regime', 'N/A')}",
            f"- Score: {comp.get('composite_score', 'N/A')} (>0.40 triggers entry)",
            f"- Entry Signal: {comp.get('entry_signal', 'N/A')}",
            f"- Bias: {comp.get('bias', 'N/A')}",
            f"- STC contributed: {comp.get('stc_contrib', False)}",
            f"- ORB contributed: {comp.get('orb_contrib', False)}",
            f"- VWAP contributed: {comp.get('vwap_contrib', False)}",
            f"- R:R at T1: {comp.get('composite_rr', 'N/A')}",
            "",
        ]
        return "\n".join(lines)

    @staticmethod
    def _format_hp_context(hp_result) -> str:
        """Format a Hidden Pivots scan result as a compact LLM prompt block."""
        if hp_result is None:
            return ""
        lines = [
            "",
            "HIDDEN PIVOTS SCAN (Rick Ackerman structural methodology):",
        ]
        if hp_result.pattern:
            lines.append(
                f"- Pattern: {hp_result.pattern} (conf {hp_result.confidence:.0%}) | Bias: {hp_result.bias}"
            )
        else:
            lines.append(f"- Pattern: none detected | Bias: {hp_result.bias}")

        if hp_result.trigger_price:
            lines.append(f"- Trigger level: ${hp_result.trigger_price:.2f}")
        if hp_result.hp_ou_level:
            lines.append(f"- HP o/u inflection: ${hp_result.hp_ou_level:.2f}")
        if hp_result.tight_stop:
            lines.append(f"- Tight stop: ${hp_result.tight_stop:.2f}")
        if hp_result.targets:
            targets_str = " / ".join(f"${t:.2f}" for t in hp_result.targets[:3])
            lines.append(f"- Targets: {targets_str}")

        lines.append(f"- EMA alignment: {hp_result.ema_alignment}")
        lines.append(f"- Oscillator state: {hp_result.oscillator_state}")
        lines.append(f"- RS/RW: {hp_result.rs_rw_label} ({hp_result.rs_rw_score:+.2f})")
        if hp_result.soh:
            lines.append("- SOH (Sit On Hands): TRUE — structural warning, avoid new entries")
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _build_stc_context(indicators: dict, symbol: str) -> str:
        """
        Build a human-readable STC signal context block for the LLM prompt.
        Uses canonical JARVIS thresholds: OS=15, OB=83.
        Also computes ATR stop distance (0.70x ATR) in dollar terms for MES (1 contract = $5/pt).

        Returns a formatted string block; empty string if STC not available.
        """
        stc_val = indicators.get("stc")
        if stc_val is None:
            return ""

        stc_prev = indicators.get("stc_prev")
        atr = indicators.get("atr")
        current_price = indicators.get("current_price", 0.0)

        # STC signal state
        STC_OS = 15
        STC_OB = 83
        stc_val_fmt = f"{stc_val:.1f}"

        # Detect crossover events (prev bar on opposite side of threshold)
        cross_below_ob = stc_prev is not None and stc_prev > STC_OB and stc_val <= STC_OB
        cross_above_os = stc_prev is not None and stc_prev < STC_OS and stc_val >= STC_OS

        if cross_below_ob:
            stc_state = (
                f"STC OVERBOUGHT CROSS-BELOW ({stc_val_fmt}) — EXIT TRIGGER ACTIVE: "
                f"STC just crossed below {STC_OB} (was {stc_prev:.1f}); canonical exit signal for longs. "
                f"Do NOT open new longs here."
            )
        elif cross_above_os:
            stc_state = (
                f"STC OVERSOLD CROSS-ABOVE ({stc_val_fmt}) — ENTRY TRIGGER ACTIVE: "
                f"STC just crossed above {STC_OS} (was {stc_prev:.1f}); canonical long entry signal. "
                f"Confirm regime alignment before executing."
            )
        elif stc_val > STC_OB:
            stc_state = (
                f"STC OVERBOUGHT ({stc_val_fmt} > {STC_OB}) — potential exit long / "
                f"caution on new longs. Watch for cross below {STC_OB} as exit trigger."
            )
        elif stc_val < STC_OS:
            stc_state = (
                f"STC OVERSOLD ({stc_val_fmt} < {STC_OS}) — potential entry long. "
                f"Watch for cross above {STC_OS} as entry trigger."
            )
        else:
            stc_state = (
                f"STC NEUTRAL ({stc_val_fmt}, between {STC_OS}–{STC_OB}) — "
                f"mid-range, no actionable STC trigger. Await OS/OB threshold cross."
            )

        # ATR stop context
        atr_lines = ""
        if atr and atr > 0:
            stop_distance = atr * 0.70
            # MES-specific dollar value: $5 per point
            sym_upper = symbol.upper()
            point_values = {"MES": 5.0, "MNQ": 2.0, "MCL": 100.0, "MGC": 10.0}
            pt_val = point_values.get(sym_upper, 0.0)
            if pt_val > 0 and current_price > 0:
                stop_dollar = stop_distance * pt_val
                atr_lines = (
                    f"\nATR CONTEXT: ATR(14)={atr:.2f} pts | "
                    f"0.70x ATR stop = {stop_distance:.2f} pts "
                    f"(${stop_dollar:.0f} per 1 {sym_upper} contract)"
                )
            else:
                atr_lines = (
                    f"\nATR CONTEXT: ATR(14)={atr:.2f} | 0.70x ATR stop = {stop_distance:.2f}"
                )

        return f"\nSTC SIGNAL STATE: {stc_state}{atr_lines}\n"

    def _compute_indicators(self, df: pd.DataFrame) -> dict:
        """
        Compute technical indicators using pandas-ta.
        All deterministic — no LLM involved here.
        """
        if not PANDAS_TA_AVAILABLE:
            logger.warning("pandas_ta not installed — returning minimal indicator set")
            df_tmp = df.copy()
            df_tmp.columns = [c.lower() for c in df_tmp.columns]
            current = df_tmp.iloc[-1]
            return {
                "current_price": float(current.get("close", 0.0)),
                "support_levels": [],
                "resistance_levels": [],
            }
        df = df.copy()
        df.columns = [c.lower() for c in df.columns]

        # Ensure required columns
        for col in ["open", "high", "low", "close", "volume"]:
            if col not in df.columns:
                df[col] = 0.0

        indicators = {}
        current = df.iloc[-1]

        # ── Trend Indicators ─────────────────────────────────────────────
        df.ta.sma(length=20, append=True)
        df.ta.sma(length=50, append=True)
        df.ta.sma(length=200, append=True)
        df.ta.ema(length=9, append=True)
        df.ta.ema(length=21, append=True)
        df.ta.adx(append=True)

        indicators["sma_20"] = float(df["SMA_20"].iloc[-1]) if "SMA_20" in df else None
        indicators["sma_50"] = float(df["SMA_50"].iloc[-1]) if "SMA_50" in df else None
        indicators["sma_200"] = float(df["SMA_200"].iloc[-1]) if "SMA_200" in df else None
        indicators["ema_9"] = float(df["EMA_9"].iloc[-1]) if "EMA_9" in df else None
        indicators["ema_21"] = float(df["EMA_21"].iloc[-1]) if "EMA_21" in df else None
        indicators["adx"] = float(df["ADX_14"].iloc[-1]) if "ADX_14" in df else None

        # ── Momentum Indicators ──────────────────────────────────────────
        df.ta.rsi(append=True)
        df.ta.macd(append=True)
        df.ta.stoch(append=True)
        df.ta.cci(append=True)
        df.ta.willr(append=True)

        indicators["rsi"] = float(df["RSI_14"].iloc[-1]) if "RSI_14" in df else None
        indicators["macd"] = float(df["MACD_12_26_9"].iloc[-1]) if "MACD_12_26_9" in df else None
        indicators["macd_signal"] = (
            float(df["MACDs_12_26_9"].iloc[-1]) if "MACDs_12_26_9" in df else None
        )
        indicators["macd_histogram"] = (
            float(df["MACDh_12_26_9"].iloc[-1]) if "MACDh_12_26_9" in df else None
        )
        indicators["stoch_k"] = (
            float(df["STOCHk_14_3_3"].iloc[-1]) if "STOCHk_14_3_3" in df else None
        )
        indicators["stoch_d"] = (
            float(df["STOCHd_14_3_3"].iloc[-1]) if "STOCHd_14_3_3" in df else None
        )
        indicators["cci"] = float(df["CCI_14_0.015"].iloc[-1]) if "CCI_14_0.015" in df else None
        indicators["williams_r"] = float(df["WILLR_14"].iloc[-1]) if "WILLR_14" in df else None

        # ── Volatility Indicators ────────────────────────────────────────
        df.ta.atr(append=True)
        df.ta.bbands(append=True)

        if "ATRr_14" in df and not pd.isna(df["ATRr_14"].iloc[-1]):
            indicators["atr"] = float(df["ATRr_14"].iloc[-1])
        elif len(df) >= 2:
            # Fallback: simple True Range average when pandas_ta needs more warmup bars.
            # TR = max(H-L, |H-prev_C|, |L-prev_C|)
            hi = df["high"]
            lo = df["low"]
            cl = df["close"]
            tr = pd.concat(
                [hi - lo, (hi - cl.shift(1)).abs(), (lo - cl.shift(1)).abs()], axis=1
            ).max(axis=1)
            period = min(14, len(tr) - 1)
            indicators["atr"] = float(tr.iloc[-period:].mean()) if period > 0 else None
            logger.debug(
                "[TechnicalAnalyst] ATRr_14 unavailable (%d bars) — using %d-bar TR mean fallback",
                len(df),
                period,
            )
        else:
            indicators["atr"] = None
        indicators["bb_upper"] = float(df["BBU_5_2.0"].iloc[-1]) if "BBU_5_2.0" in df else None
        indicators["bb_mid"] = float(df["BBM_5_2.0"].iloc[-1]) if "BBM_5_2.0" in df else None
        indicators["bb_lower"] = float(df["BBL_5_2.0"].iloc[-1]) if "BBL_5_2.0" in df else None

        # BB %B (position within bands)
        if all(indicators.get(k) for k in ["bb_upper", "bb_lower"]):
            bb_range = indicators["bb_upper"] - indicators["bb_lower"]
            if bb_range > 0:
                indicators["bb_pct_b"] = (
                    float(current["close"]) - indicators["bb_lower"]
                ) / bb_range

        # ── Volume Indicators ────────────────────────────────────────────
        df.ta.obv(append=True)
        # pandas_ta's vwap() emits `print("[!] VWAP requires an ordered DatetimeIndex.")`
        # straight to stdout when the index isn't a DatetimeIndex (it falls back to a
        # numeric index in that case — no actual computation harm). Pre-check the
        # index ourselves so the library never reaches its print path; if the index
        # is wrong we just skip VWAP rather than spamming logs every ~5 minutes.
        # Background: 2026-04-16 log-noise audit (Roadmap T1.3).
        import pandas as _pd

        if isinstance(df.index, _pd.DatetimeIndex):
            df.ta.vwap(append=True)
        # else: VWAP unavailable for this frame — leave indicators["vwap"] as None below

        indicators["obv"] = float(df["OBV"].iloc[-1]) if "OBV" in df else None
        indicators["vwap"] = float(df["VWAP_D"].iloc[-1]) if "VWAP_D" in df else None

        # Volume vs 20-period average
        vol_avg = float(df["volume"].rolling(20).mean().iloc[-1])
        indicators["volume_ratio"] = float(current["volume"]) / vol_avg if vol_avg > 0 else 1.0

        # ── STC (Schaff Trend Cycle) ─────────────────────────────────────
        # Compute STC using pandas_ta. Canonical JARVIS thresholds: OS=15, OB=83.
        try:
            df.ta.stc(append=True)
            stc_col = next((c for c in df.columns if c.startswith("STC_")), None)
            if stc_col:
                indicators["stc"] = float(df[stc_col].iloc[-1])
                # Previous bar value to detect crossovers
                if len(df) >= 2:
                    indicators["stc_prev"] = float(df[stc_col].iloc[-2])
        except Exception:
            pass  # STC is enrichment — never block analysis

        # ── Price Context ────────────────────────────────────────────────
        indicators["current_price"] = float(current["close"])
        indicators["price_change_pct"] = (
            (float(current["close"]) - float(df["close"].iloc[-20]))
            / float(df["close"].iloc[-20])
            * 100
            if len(df) >= 20
            else 0.0
        )

        # Simple support/resistance (recent swing lows/highs)
        recent = df.tail(50)
        lows = recent["low"].nsmallest(3).tolist()
        highs = recent["high"].nlargest(3).tolist()
        indicators["support_levels"] = sorted([round(x, 2) for x in lows])
        indicators["resistance_levels"] = sorted([round(x, 2) for x in highs], reverse=True)

        return indicators

    async def _get_discord_context(self, symbol: str, current_price: float, atr: float) -> str:
        """
        Fetch active Discord signal context for the LLM prompt.
        Returns formatted block when a signal is active; '' otherwise. Never raises.
        """
        try:
            from zoneinfo import ZoneInfo

            from discord.signal_context import DiscordSignalContext

            ctx = DiscordSignalContext()
            features = ctx.get_features(
                symbol=symbol,
                timestamp=datetime.now(tz=ZoneInfo("America/Chicago")),
                price=max(float(current_price), 0.01),
                atr=max(float(atr), 1.0),
                jarvis_bias="NEUTRAL",
            )
            if features.get("discord_signal_active", 0) < 0.5:
                return ""
            win_rate = features.get("discord_win_rate_context", 0.0)
            prox_entry = features.get("discord_proximity_entry", 0.0)
            prox_target = features.get("discord_proximity_target", 0.0)
            alignment = features.get("discord_alignment", 0.0)
            align_str = (
                "ALIGNED" if alignment > 0.5 else ("OPPOSED" if alignment < -0.5 else "NEUTRAL")
            )
            return (
                f"\nDISCORD INTELLIGENCE (Corey Auction Tools — 30-day context):\n"
                f"- Signal Active: YES | Bot Win Rate: {win_rate:.0%}\n"
                f"- Proximity to Entry: {prox_entry:+.2f} ATR | To Target: {prox_target:.2f} ATR\n"
                f"- Alignment with Jarvis Bias: {align_str}\n"
            )
        except Exception as exc:
            logger.debug(f"[DISCORD_CTX] skipped: {exc}")
            return ""

    async def _llm_synthesize(
        self,
        symbol: str,
        timeframe: str,
        df: pd.DataFrame,
        indicators: dict,
        historical_context: str = "",
    ) -> TechnicalReport:
        """
        Use LLM to synthesize indicator data into a structured trading report.
        The LLM adds pattern recognition and contextual reasoning — the numbers
        are computed deterministically above.

        Injects historical pattern recommendations from learning system (non-blocking fallback).
        If historical_context is provided (injected by pipeline Stage 1), it is used directly
        to avoid a redundant DB read. Otherwise, falls back to internal fetch.
        """
        # Use pipeline-injected context if available; otherwise fetch from DB
        learning_context = historical_context
        if not learning_context:
            try:
                from database.manager import db_manager
                from learning.recommendations import (
                    format_recommendations_for_prompt,
                    get_recommendations,
                )

                recommendations = await get_recommendations(
                    symbol, timeframe, db_manager=db_manager
                )
                if recommendations:
                    learning_context = format_recommendations_for_prompt(recommendations)
                    logger.info(
                        f"[LEARNING] {len(recommendations)} recommendations injected for {symbol}"
                    )
                else:
                    logger.debug(f"[LEARNING] No active recommendations for {symbol}")
            except Exception as lc_err:
                logger.debug(f"[LEARNING] Recommendation injection skipped: {lc_err}")
                # Continue normally without learning context

        # Discord sentiment multiplier from Corey Auction Tools commentary
        discord_sentiment_line = ""
        try:
            from discord.sentiment_provider import SentimentProvider

            _sp = SentimentProvider()
            today = datetime.now().date()
            sentiment_score = _sp.get_sentiment(today)
            sentiment_mult = _sp.get_regime_multiplier(today)
            if sentiment_score != 0.0:
                bias_word = (
                    "BULLISH"
                    if sentiment_score > 0.1
                    else ("BEARISH" if sentiment_score < -0.1 else "NEUTRAL")
                )
                discord_sentiment_line = (
                    f"\nDISCORD EXPERT SENTIMENT (Corey Auction Tools): {bias_word} "
                    f"(score {sentiment_score:+.2f}) | Regime Confidence Multiplier: {sentiment_mult:.2f}x"
                )
        except Exception:
            pass  # Sentiment is enrichment — never block analysis

        # Inject active Discord signal context (non-blocking)
        discord_signal_str = await self._get_discord_context(
            symbol,
            float(indicators.get("current_price", 0.0) or 0.0),
            float(indicators.get("atr", 1.0) or 1.0),
        )

        # Build deterministic STC context block (OS=15, OB=83 canonical thresholds)
        stc_context_str = self._build_stc_context(indicators, symbol)

        # Run Hidden Pivots scan (deterministic, no LLM, no I/O — fast)
        hp_context_str = ""
        try:
            from analysis.hidden_pivots import full_hidden_pivots_scan

            hp_result = await asyncio.to_thread(
                full_hidden_pivots_scan, symbol=symbol, df=df, timeframe=timeframe
            )
            hp_context_str = self._format_hp_context(hp_result)
        except Exception as hp_err:
            logger.debug("[TechnicalAnalyst] Hidden Pivots scan skipped: %s", hp_err)

        # Build TradingView live data context block for prompt
        tv_data_quality = indicators.get("tv_data_quality", "live")
        if tv_data_quality == "live":
            tv_context = f"""
TRADINGVIEW LIVE DATA (real-time from TradingView Desktop):
- Composite Score: {indicators.get('tv_composite', 'n/a')} (range -1 to +1)
- Regime: {indicators.get('tv_regime', 'n/a')}
- STC (TV): {indicators.get('tv_stc', 'n/a')} — {indicators.get('tv_stc_state', 'n/a')}
- Phase Oscillator: {indicators.get('tv_phase', 'n/a')} ({'COMPRESSED' if indicators.get('tv_compressed') else 'normal'})
- Corey Auction Score: {indicators.get('tv_corey_score', 'n/a')}
- IB Levels: High={indicators.get('tv_ib_high', 'n/a')} Low={indicators.get('tv_ib_low', 'n/a')}
  Extensions: IBU50={indicators.get('tv_ibu50', 'n/a')} IBU100={indicators.get('tv_ibu100', 'n/a')} IBD50={indicators.get('tv_ibd50', 'n/a')} IBD100={indicators.get('tv_ibd100', 'n/a')}
- ATR (TV): {indicators.get('tv_atr', 'n/a')} | Bands: -{indicators.get('tv_atr_neg1','n/a')} / +{indicators.get('tv_atr_pos1','n/a')}
- POC: {indicators.get('tv_poc', 'n/a')} | VAH: {indicators.get('tv_vah', 'n/a')} | VAL: {indicators.get('tv_val', 'n/a')}
- VWAP: {indicators.get('tv_vwap', 'n/a')}
- ORB: High={indicators.get('tv_orb_high', 'n/a')} Low={indicators.get('tv_orb_low', 'n/a')}
- Keltner (1h): Upper={indicators.get('tv_kc_upper', 'n/a')} Mid={indicators.get('tv_kc_mid', 'n/a')} Lower={indicators.get('tv_kc_lower', 'n/a')} Alignment={indicators.get('tv_kc_alignment', 'n/a')}
- Pivot Points: PP={indicators.get('tv_pp', 'n/a')} R1={indicators.get('tv_r1', 'n/a')} S1={indicators.get('tv_s1', 'n/a')}
- OTE Zone: Bull={indicators.get('tv_ote_bull_low', 'n/a')}-{indicators.get('tv_ote_bull_high', 'n/a')} {'(IN ZONE)' if indicators.get('tv_in_bull_ote') else ''}
- Market Cycle: {indicators.get('tv_cycle_phase', 'n/a')}
- Gap: {indicators.get('tv_gap_direction', 'none')} {'(FILLED)' if not indicators.get('tv_gap_exists') else '(OPEN)'}
- VPOC Today: {indicators.get('tv_vpoc_today', 'n/a')}
"""
        else:
            tv_context = "TRADINGVIEW LIVE DATA: Not available (TradingView Desktop not running)\n"

        prompt = f"""Analyze these technical indicators for {symbol} on {timeframe} timeframe:

{learning_context}{discord_sentiment_line}{discord_signal_str}{stc_context_str}{tv_context}
Current Price: ${indicators.get("current_price", "N/A")}
Price Change (20 bars): {indicators.get("price_change_pct", "N/A"):.1f}%

TREND:
- SMA 20: {indicators.get("sma_20", "N/A")}
- SMA 50: {indicators.get("sma_50", "N/A")}
- SMA 200: {indicators.get("sma_200", "N/A")}
- EMA 9: {indicators.get("ema_9", "N/A")}
- ADX (trend strength): {indicators.get("adx", "N/A")} (>25 = trending, <20 = ranging)

MOMENTUM:
- RSI: {indicators.get("rsi", "N/A")} (>70 overbought, <30 oversold)
- MACD: {indicators.get("macd", "N/A")} | Signal: {indicators.get("macd_signal", "N/A")} | Histogram: {indicators.get("macd_histogram", "N/A")}
- Stochastic %K: {indicators.get("stoch_k", "N/A")} | %D: {indicators.get("stoch_d", "N/A")}
- Williams %R: {indicators.get("williams_r", "N/A")}

VOLATILITY:
- ATR (14): {indicators.get("atr", "N/A")}
- Bollinger Upper: {indicators.get("bb_upper", "N/A")}
- Bollinger Mid: {indicators.get("bb_mid", "N/A")}
- Bollinger Lower: {indicators.get("bb_lower", "N/A")}
- BB %B (0=lower, 1=upper): {indicators.get("bb_pct_b", "N/A")}

VOLUME:
- Volume Ratio (vs 20-avg): {indicators.get("volume_ratio", "N/A"):.2f}x
- OBV trend: {"rising" if indicators.get("obv", 0) > 0 else "falling"}

KEY LEVELS:
- Support: {indicators.get("support_levels", [])}
- Resistance: {indicators.get("resistance_levels", [])}
{self._format_composite_section(indicators)}{discord_sentiment_line}{hp_context_str}
INSTRUCTIONS FOR RESPONSE:
1. mtf_alignment: Provide a one-line MTF summary, e.g. "4h and 1h STC aligned bullish",
   "MTF misaligned: 4h bearish / 1h overbought", or "insufficient MTF data".
2. regime_readiness: Based on the 5-layer regime filter (trend, momentum, volatility,
   volume, structure), output one of: READY (4-5 layers aligned), CAUTION (2-3 layers
   aligned), or NOT_READY (0-1 layers aligned). Be strict — partial alignment = CAUTION.

Respond with JSON in exactly this format:
{{
  "signal": <float -1.0 to 1.0>,
  "confidence": <float 0.0 to 1.0>,
  "trend": "<uptrend|downtrend|neutral|ranging>",
  "regime": "<trending|mean_reverting|volatile>",
  "trend_score": <float -1.0 to 1.0>,
  "momentum_score": <float -1.0 to 1.0>,
  "volatility_score": <float -1.0 to 1.0>,
  "volume_score": <float -1.0 to 1.0>,
  "is_overbought": <bool>,
  "is_oversold": <bool>,
  "summary": "<one sentence summary>",
  "reasoning": "<2-3 sentence technical analysis>",
  "mtf_alignment": "<one-line MTF summary>",
  "regime_readiness": "<READY|CAUTION|NOT_READY>"
}}"""

        try:
            # Use JarvisLLMClient.call() so every LLM call is tracked in the
            # cost database (token counts, latency, USD cost per call).
            # max_tokens=1600: the 14-field JSON (incl. multi-sentence summary/
            # reasoning/mtf_alignment strings) truncates at 1024 on slower local
            # models, yielding unparseable half-JSON that degrades health.
            # Matches the trader/fund_manager decision tier (2026-08-17).
            llm_result = await self._llm.call(
                model=resolve_agent_model(self._llm, "claude-sonnet-4-6"),
                system=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1600,
                agent_name="technical_analyst",
            )
            if not llm_result.success:
                logger.error(f"LLM call failed for {symbol}: {llm_result.error}")
                return self._empty_report(symbol, timeframe)

            response_text = llm_result.content.strip()

            # Tolerant extraction: markdown fences, leading/trailing prose, and
            # trailing commas now recover instead of failing to a zero-signal
            # report (see utils.llm_json — 2026-06-04 synthesis-failure wave).
            result = parse_llm_json(response_text)

            return TechnicalReport(
                symbol=symbol,
                timestamp=datetime.now(),
                timeframe=timeframe,
                signal=float(result.get("signal", 0.0)),
                confidence=float(result.get("confidence", 0.5)),
                trend_score=float(result.get("trend_score", 0.0)),
                momentum_score=float(result.get("momentum_score", 0.0)),
                volatility_score=float(result.get("volatility_score", 0.0)),
                volume_score=float(result.get("volume_score", 0.0)),
                support_levels=indicators.get("support_levels", []),
                resistance_levels=indicators.get("resistance_levels", []),
                current_price=indicators.get("current_price", 0.0),
                summary=result.get("summary", ""),
                reasoning=result.get("reasoning", ""),
                indicators=indicators,
                is_overbought=result.get("is_overbought", False),
                is_oversold=result.get("is_oversold", False),
                trend=result.get("trend", "neutral"),
                regime=result.get("regime", "unknown"),
                # Enhanced signal context fields
                stc_context=stc_context_str.strip(),
                mtf_alignment=result.get("mtf_alignment", ""),
                regime_readiness=result.get("regime_readiness", "UNKNOWN"),
                # StarkTPO fields — sourced from indicators (set in step 2c)
                stark_signal=indicators.get("stark_signal", ""),
                stark_structure=indicators.get("stark_structure", ""),
                stark_poc=float(indicators.get("stark_poc") or 0.0),
                stark_vah=float(indicators.get("stark_vah") or 0.0),
                stark_val=float(indicators.get("stark_val") or 0.0),
            )

        except Exception as e:
            logger.error(f"LLM synthesis failed for {symbol}: {e}")
            return self._empty_report(symbol, timeframe)

    def _empty_report(self, symbol: str, timeframe: str) -> TechnicalReport:
        return TechnicalReport(
            symbol=symbol,
            timestamp=datetime.now(),
            timeframe=timeframe,
            signal=0.0,
            confidence=0.0,
            trend_score=0.0,
            momentum_score=0.0,
            volatility_score=0.0,
            volume_score=0.0,
            summary="Insufficient data",
            reasoning="Could not compute technical analysis — data unavailable",
        )

    def _no_price_report(self, symbol: str, timeframe: str) -> TechnicalReport:
        """
        Return a zero-weight abstention report when current price is unavailable.

        This is NOT a bearish signal — it is an explicit abstention.
        The pipeline orchestrator should skip zero-weight agents when computing
        final confidence so that missing price data does not suppress the signal.

        Key difference from _empty_report:
          - weight=0.0 is set in indicators so the pipeline can detect this case
          - reason='no_price_data' is set for downstream filtering
          - confidence=0.0 with signal=0.0 (neutral, not bearish)
        """
        return TechnicalReport(
            symbol=symbol,
            timestamp=datetime.now(),
            timeframe=timeframe,
            signal=0.0,
            confidence=0.0,
            trend_score=0.0,
            momentum_score=0.0,
            volatility_score=0.0,
            volume_score=0.0,
            summary="No price data — technical analyst abstaining",
            reasoning="current_price is None or 0.0; cannot compute meaningful technical signal. "
            "This is an abstention, not a bearish signal. Downstream agents should "
            "ignore this report when computing confidence.",
            indicators={"weight": 0.0, "reason": "no_price_data", "current_price": 0.0},
        )


# ---------------------------------------------------------------------------
# Gamma-regime hints — derived from "MY FREE GAMMA LEVELS" overlay
# ---------------------------------------------------------------------------
def _compute_gamma_regime_hints(indicators: dict) -> dict:
    """
    Derive regime/stop hints from gamma levels plotted on the chart.

    Bias we encode:
      - Below GEX flip ("negative gamma") → dealers short gamma, hedging
        amplifies moves → vol expansion → use wider stops, expect
        trend-continuation behavior.
      - Above GEX flip ("positive gamma") → dealers long gamma, hedging
        dampens moves → vol compression → tighter stops, mean-reverting
        behavior near call/put walls.

    All returned keys are None when the gamma overlay isn't loaded, so the
    LLM synthesis stage can safely branch on any key. Keys are namespaced
    under `gamma_*` to keep them distinct from raw `tv_gex_*` inputs.
    """
    price = indicators.get("current_price")
    gex_flip = indicators.get("tv_gex_flip")
    call_wall = indicators.get("tv_call_wall")
    put_wall = indicators.get("tv_put_wall")
    hvl = indicators.get("tv_hvl")

    out = {
        "gex_regime": None,
        "nearest_wall": None,
        "nearest_wall_side": None,
        "nearest_wall_distance_pct": None,
        "above_hvl": None,
        "suggested_stop_policy": None,
    }

    if price is None or price <= 0:
        return out

    if gex_flip is not None:
        if price >= gex_flip:
            out["gex_regime"] = "positive"
            out["suggested_stop_policy"] = "tight"
        else:
            out["gex_regime"] = "negative"
            out["suggested_stop_policy"] = "wide"

    candidates = []
    if call_wall is not None:
        candidates.append(("call_wall", call_wall))
    if put_wall is not None:
        candidates.append(("put_wall", put_wall))
    if candidates:
        side, level = min(candidates, key=lambda kv: abs(kv[1] - price))
        out["nearest_wall"] = level
        out["nearest_wall_side"] = side
        out["nearest_wall_distance_pct"] = abs(level - price) / price if price else None

    if hvl is not None:
        out["above_hvl"] = price > hvl

    return out
