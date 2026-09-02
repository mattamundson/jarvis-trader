"""
JARVIS TRADER — Technical Analyst Agent
=========================================
First agent in the pipeline. Analyzes OHLCV data using technical indicators
and produces a structured JSON report consumed by the downstream research agents.

Runs every 15 minutes during market hours.
Model: Claude Sonnet 4.6 (fast, cost-efficient for repeated analysis)
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

try:
    import pandas_ta as ta  # 150+ technical indicators

    PANDAS_TA_AVAILABLE = True
except ImportError:
    ta = None
    PANDAS_TA_AVAILABLE = False

logger = logging.getLogger(__name__)

# Minimum bars required for a full intraday analysis
_MIN_INTRADAY_BARS = 50
# Minimum daily bars needed for a degraded-but-useful daily fallback
_MIN_DAILY_BARS = 5


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

        # 2. Compute all indicators (deterministic Python — no LLM)
        indicators = self._compute_indicators(df)

        # 2b. Composite signal enrichment for MES (and future composite instruments)
        try:
            from backtest.signals import COMPOSITE_INSTRUMENTS

            if symbol.upper() in COMPOSITE_INSTRUMENTS:
                from backtest.composite_signals import generate_composite_signals

                df_comp = generate_composite_signals(df.copy(), symbol=symbol.upper())
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
        report = await self._llm_synthesize(symbol, effective_timeframe, df, indicators)

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

        indicators["atr"] = float(df["ATRr_14"].iloc[-1]) if "ATRr_14" in df else None
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
        df.ta.vwap(append=True)

        indicators["obv"] = float(df["OBV"].iloc[-1]) if "OBV" in df else None
        indicators["vwap"] = float(df["VWAP_D"].iloc[-1]) if "VWAP_D" in df else None

        # Volume vs 20-period average
        vol_avg = float(df["volume"].rolling(20).mean().iloc[-1])
        indicators["volume_ratio"] = float(current["volume"]) / vol_avg if vol_avg > 0 else 1.0

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

    async def _llm_synthesize(
        self,
        symbol: str,
        timeframe: str,
        df: pd.DataFrame,
        indicators: dict,
    ) -> TechnicalReport:
        """
        Use LLM to synthesize indicator data into a structured trading report.
        The LLM adds pattern recognition and contextual reasoning — the numbers
        are computed deterministically above.

        Injects historical pattern recommendations from learning system (non-blocking fallback).
        """
        # Inject learning recommendations (non-blocking graceful fallback)
        learning_context = ""
        try:
            from database.manager import db_manager
            from learning.recommendations import (
                format_recommendations_for_prompt,
                get_recommendations,
            )

            recommendations = await get_recommendations(symbol, timeframe, db_manager=db_manager)
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

        prompt = f"""Analyze these technical indicators for {symbol} on {timeframe} timeframe:

{learning_context}

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
{self._format_composite_section(indicators)}
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
  "reasoning": "<2-3 sentence technical analysis>"
}}"""

        try:
            # Use JarvisLLMClient.call() so every LLM call is tracked in the
            # cost database (token counts, latency, USD cost per call).
            llm_result = await self._llm.call(
                model="claude-sonnet-4-6",
                system=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
                agent_name="technical_analyst",
            )
            if not llm_result.success:
                logger.error(f"LLM call failed for {symbol}: {llm_result.error}")
                return self._empty_report(symbol, timeframe)

            response_text = llm_result.content.strip()

            # Strip markdown code blocks if present
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]

            result = json.loads(response_text)

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
