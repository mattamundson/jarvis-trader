"""
Technical analysis and sentiment endpoints

Provides technical analysis, OHLCV bars, LLM statistics, and sentiment scoring.
"""

import logging

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.models import (
    BarsResponse,
    RedditSentimentResponse,
    TechnicalAnalysisResponse,
)
from backtest.indicators import compute_vwap
from backtest.indicators import stc as compute_stc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["analysis"])

# Global references (injected from main.py)
technical_analyst = None
data_manager = None
cost_tracker = None


def inject_dependencies(ta, dm, ct):
    """Inject global dependencies from main.py"""
    global technical_analyst, data_manager, cost_tracker
    technical_analyst = ta
    data_manager = dm
    cost_tracker = ct


class AnalysisRequest(BaseModel):
    """Technical analysis request"""

    symbol: str
    timeframe: str = "15m"
    is_futures: bool = False


@router.post("/analyze/technical", response_model=TechnicalAnalysisResponse)
async def run_technical_analysis(req: AnalysisRequest):
    """Run the Technical Analyst agent on a symbol"""
    if not technical_analyst:
        raise HTTPException(503, "Technical analyst not available (no API key)")

    try:
        report = await technical_analyst.analyze(req.symbol, req.timeframe, req.is_futures)

        return {
            "symbol": report.symbol,
            "timestamp": report.timestamp.isoformat(),
            "timeframe": report.timeframe,
            "signal": report.signal,
            "confidence": report.confidence,
            "trend": report.trend,
            "regime": report.regime,
            "is_overbought": report.is_overbought,
            "is_oversold": report.is_oversold,
            "summary": report.summary,
            "reasoning": report.reasoning,
            "scores": {
                "trend": report.trend_score,
                "momentum": report.momentum_score,
                "volatility": report.volatility_score,
                "volume": report.volume_score,
            },
            "levels": {
                "current_price": report.current_price,
                "support": report.support_levels,
                "resistance": report.resistance_levels,
            },
            "raw_indicators": report.indicators,
        }
    except Exception as e:
        logger.error(f"[ANALYSIS] Technical analysis failed: {e}")
        raise HTTPException(500, f"Technical analysis failed: {e}") from e


@router.get("/analyze/bars/{symbol}", response_model=BarsResponse)
async def get_bars(
    symbol: str,
    timeframe: str | None = None,
    interval: str | None = None,
    days: int = 7,
    futures: bool = False,
    limit: int = 200,
):
    """Get OHLCV bars for a symbol, including VWAP and STC per bar.

    `interval` is accepted as an alias for `timeframe` (matches pandas/ohlcv convention).
    Precedence: explicit `timeframe` > `interval` > default `5m`.

    `limit` caps how many trailing bars are returned (default 200). Callers that
    need a long SMA warmup (e.g. the paper runner's SMA-200 crossover, which needs
    >200 1h bars) request more; clamped to 1000 to bound payload size.
    """
    if not data_manager:
        raise HTTPException(503, "Data manager not initialized")

    timeframe = timeframe or interval or "5m"

    try:
        df = await data_manager.get_bars(
            symbol, lookback_days=days, timeframe=timeframe, is_futures=futures
        )
        if df.empty:
            raise HTTPException(404, f"No data available for {symbol}")

        # Compute VWAP (session-reset daily)
        try:
            df["vwap"] = compute_vwap(df, session_reset=True)
        except Exception as vwap_err:
            logger.warning(f"[ANALYSIS] VWAP computation failed for {symbol}: {vwap_err}")
            df["vwap"] = float("nan")

        # Compute STC oscillator (STC 23/50/10/3 matching strategy config)
        try:
            df["stc"] = compute_stc(df["close"], fast=23, slow=50, k_period=10, d_period=3)
        except Exception as stc_err:
            logger.warning(f"[ANALYSIS] STC computation failed for {symbol}: {stc_err}")
            df["stc"] = float("nan")

        # Compute EMA ribbon (8/21/34) for chart overlay — exponential moving averages
        try:
            df["ema_8"] = df["close"].ewm(span=8, adjust=False).mean()
            df["ema_21"] = df["close"].ewm(span=21, adjust=False).mean()
            df["ema_34"] = df["close"].ewm(span=34, adjust=False).mean()
        except Exception as ema_err:
            logger.warning(f"[ANALYSIS] EMA computation failed for {symbol}: {ema_err}")
            df["ema_8"] = float("nan")
            df["ema_21"] = float("nan")
            df["ema_34"] = float("nan")

        # Tail `limit` bars (clamped) and build response, NaN -> None for JSON safety
        tail_df = df.tail(max(1, min(limit, 1000)))
        bars_records = tail_df.to_dict(orient="records")
        for bar in bars_records:
            for key in ("vwap", "stc", "ema_8", "ema_21", "ema_34"):
                val = bar.get(key)
                if val is not None and (isinstance(val, float) and (val != val)):  # nan check
                    bar[key] = None
                elif val is not None and isinstance(val, float) and not np.isfinite(val):
                    bar[key] = None

        # Compute summary fields from last bar
        last_close = float(tail_df["close"].iloc[-1]) if len(tail_df) else None
        last_vwap = (
            float(tail_df["vwap"].iloc[-1])
            if len(tail_df) and not tail_df["vwap"].isna().iloc[-1]
            else None
        )

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "bars": bars_records,
            "count": len(df),
            "vwap_current": last_vwap,
            "vwap_trend": (
                "above"
                if last_close is not None and last_vwap is not None and last_close > last_vwap
                else (
                    "below"
                    if last_close is not None and last_vwap is not None and last_close < last_vwap
                    else None
                )
            ),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ANALYSIS] Failed to get bars for {symbol}: {e}")
        raise HTTPException(500, f"Failed to get bars: {e}") from e


@router.get("/llm/stats")
async def get_llm_stats(days_back: int = 0):
    """
    Get LLM API usage and cost statistics for a given day.

    Query Parameters:
        days_back: 0 for today, 1 for yesterday, etc. (default: 0)

    Returns:
        date: ISO date string
        total_calls: Total LLM API calls made
        total_cost_usd: Total cost in USD
        success_rate: Percentage of successful calls (0-1)
        avg_latency_ms: Average API latency in milliseconds
        per_model: Dict[model_name] -> {calls, input_tokens, output_tokens, cost_usd}
        per_agent: Dict[agent_name] -> {calls, cost_usd}
        per_provider: Dict[provider] -> {calls, input_tokens, output_tokens, cost_usd}
            where provider is direct|vertex|google|vertex-gemini|ollama|external
    """
    if not cost_tracker:
        raise HTTPException(500, "Cost tracker not initialized")
    try:
        return await cost_tracker.get_daily_summary(days_back=days_back)
    except Exception as e:
        logger.error(f"[LLM-STATS] Daily summary failed: {e}")
        raise HTTPException(500, f"Failed to get LLM stats: {e}") from e


@router.get("/sentiment/reddit", response_model=RedditSentimentResponse)
async def get_reddit_sentiment(filter: str = "all-stocks"):
    """Get trending tickers from Reddit"""
    if not data_manager:
        raise HTTPException(503, "Data manager not initialized")

    try:
        tickers = await data_manager.reddit.get_trending_tickers(filter)
        return {"filter": filter, "tickers": tickers[:20]}
    except Exception as e:
        logger.error(f"[SENTIMENT] Reddit sentiment failed: {e}")
        raise HTTPException(500, f"Failed to get Reddit sentiment: {e}") from e


@router.get("/analytics/performance/rolling")
async def rolling_performance(days: int = 30):
    """Return rolling performance metrics over the given number of days."""
    from datetime import datetime, timedelta, timezone

    if days <= 0:
        days = 30
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    # Return stub metrics — real data populated when db_manager is available
    return {
        "days": days,
        "start_date": cutoff.date().isoformat(),
        "end_date": datetime.now(timezone.utc).date().isoformat(),
        "total_trades": 0,
        "win_rate": 0.0,
    }
