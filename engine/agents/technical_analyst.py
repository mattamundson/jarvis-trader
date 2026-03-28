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
from typing import Optional

import pandas as pd
import pandas_ta as ta  # 150+ technical indicators

logger = logging.getLogger(__name__)


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
    trend_score: float      # Based on MA crossovers, ADX
    momentum_score: float   # RSI, MACD, Stochastic
    volatility_score: float # ATR, Bollinger Band position
    volume_score: float     # Volume vs average, OBV

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

        # 1. Fetch OHLCV data
        df = await self._data.get_bars(symbol, lookback_days=30, timeframe=timeframe, is_futures=is_futures)
        if df.empty or len(df) < 50:
            logger.warning(f"Insufficient data for {symbol} ({len(df)} bars)")
            return self._empty_report(symbol, timeframe)

        # 2. Compute all indicators (deterministic Python — no LLM)
        indicators = self._compute_indicators(df)

        # 3. LLM synthesis
        report = await self._llm_synthesize(symbol, timeframe, df, indicators)
        return report

    def _compute_indicators(self, df: pd.DataFrame) -> dict:
        """
        Compute technical indicators using pandas-ta.
        All deterministic — no LLM involved here.
        """
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
        indicators["macd_signal"] = float(df["MACDs_12_26_9"].iloc[-1]) if "MACDs_12_26_9" in df else None
        indicators["macd_histogram"] = float(df["MACDh_12_26_9"].iloc[-1]) if "MACDh_12_26_9" in df else None
        indicators["stoch_k"] = float(df["STOCHk_14_3_3"].iloc[-1]) if "STOCHk_14_3_3" in df else None
        indicators["stoch_d"] = float(df["STOCHd_14_3_3"].iloc[-1]) if "STOCHd_14_3_3" in df else None
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
                indicators["bb_pct_b"] = (float(current["close"]) - indicators["bb_lower"]) / bb_range

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
            (float(current["close"]) - float(df["close"].iloc[-20])) / float(df["close"].iloc[-20]) * 100
            if len(df) >= 20 else 0.0
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
        """
        prompt = f"""Analyze these technical indicators for {symbol} on {timeframe} timeframe:

Current Price: ${indicators.get('current_price', 'N/A')}
Price Change (20 bars): {indicators.get('price_change_pct', 'N/A'):.1f}%

TREND:
- SMA 20: {indicators.get('sma_20', 'N/A')}
- SMA 50: {indicators.get('sma_50', 'N/A')}
- SMA 200: {indicators.get('sma_200', 'N/A')}
- EMA 9: {indicators.get('ema_9', 'N/A')}
- ADX (trend strength): {indicators.get('adx', 'N/A')} (>25 = trending, <20 = ranging)

MOMENTUM:
- RSI: {indicators.get('rsi', 'N/A')} (>70 overbought, <30 oversold)
- MACD: {indicators.get('macd', 'N/A')} | Signal: {indicators.get('macd_signal', 'N/A')} | Histogram: {indicators.get('macd_histogram', 'N/A')}
- Stochastic %K: {indicators.get('stoch_k', 'N/A')} | %D: {indicators.get('stoch_d', 'N/A')}
- Williams %R: {indicators.get('williams_r', 'N/A')}

VOLATILITY:
- ATR (14): {indicators.get('atr', 'N/A')}
- Bollinger Upper: {indicators.get('bb_upper', 'N/A')}
- Bollinger Mid: {indicators.get('bb_mid', 'N/A')}
- Bollinger Lower: {indicators.get('bb_lower', 'N/A')}
- BB %B (0=lower, 1=upper): {indicators.get('bb_pct_b', 'N/A')}

VOLUME:
- Volume Ratio (vs 20-avg): {indicators.get('volume_ratio', 'N/A'):.2f}x
- OBV trend: {'rising' if indicators.get('obv', 0) > 0 else 'falling'}

KEY LEVELS:
- Support: {indicators.get('support_levels', [])}
- Resistance: {indicators.get('resistance_levels', [])}

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
            import anthropic
            client = anthropic.Anthropic(api_key=self._llm.api_key)
            message = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}]
            )
            response_text = message.content[0].text.strip()

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
