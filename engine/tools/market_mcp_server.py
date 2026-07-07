"""
JARVIS TRADER — Market MCP Server
====================================
Exposes JARVIS engine data as Claude Agent SDK MCP tools for use in
the SDK-powered pipeline (/pipeline/run/sdk).

All 6 tools run in-process and are made available to SDK subagents via
the McpSdkServerConfig returned by create_market_mcp_server().

Tool inventory:
  get_price_bars      — OHLCV bars + technical indicators via DataManager
  get_finnhub_news    — News headlines/sentiment via engine /sentiment/news/
  get_fred_macro      — VIX, 10Y yield, Fed Funds via engine /macro/snapshot
  get_social_sentiment— Reddit trending sentiment via engine /sentiment/reddit
  get_safety_status   — Kill switch / daily P&L / drawdown via /safety/status
  log_paper_trade     — Paper trade entry via engine /portfolio/paper/trade

Usage:
    from tools.market_mcp_server import create_market_mcp_server

    mcp_server = create_market_mcp_server(
        data_manager=data_manager,
        api_key=settings.JARVIS_API_KEY,
    )
    # Pass to ClaudeAgentOptions(mcp_servers={"market": mcp_server})
"""

import json
import logging

import httpx
from claude_agent_sdk import create_sdk_mcp_server, tool

logger = logging.getLogger(__name__)

_ENGINE_BASE = "http://localhost:8010"


def create_market_mcp_server(
    data_manager,
    api_key: str = "",
):
    """
    Factory: creates an in-process MCP server with 6 JARVIS market data tools.

    Dependencies are captured in closures — no module-level globals needed.
    Each tool is an async function; the SDK handles routing from the
    spawned claude subprocess back to these in-process coroutines.

    Args:
        data_manager: JARVIS DataManager for price bar access.
        api_key:      JARVIS engine API key (X-API-Key header for port 8010).

    Returns:
        McpSdkServerConfig — pass to ClaudeAgentOptions(mcp_servers={...}).
    """
    _hdrs = {"X-API-Key": api_key} if api_key else {}

    # ── Tool 1: Price Bars ────────────────────────────────────────────────────

    @tool(
        "get_price_bars",
        "Get OHLCV price bars and pre-computed technical indicators (STC, ATR, "
        "EMA) for a futures symbol. Returns the last `limit` bars as JSON.",
        {"symbol": str, "interval": str, "limit": int},
    )
    async def get_price_bars(args: dict) -> dict:
        symbol = str(args["symbol"]).upper()
        interval = str(args.get("interval", "1h"))
        limit = max(1, int(args.get("limit", 50)))
        # Rough lookback: 1h bars → ~6/day; 1d bars → 1/day
        bars_per_day = {"1m": 390, "5m": 78, "15m": 26, "1h": 6, "4h": 2, "1d": 1}.get(interval, 6)
        lookback_days = max(7, (limit // bars_per_day) + 5)

        try:
            df = await data_manager.get_bars(
                symbol=symbol,
                lookback_days=lookback_days,
                timeframe=interval,
                is_futures=True,
            )
            if df is None or df.empty:
                result = {"error": f"No price data available for {symbol}", "symbol": symbol}
            else:
                records = df.tail(limit).reset_index().to_dict(orient="records")
                # Serialise numpy / pandas types
                for rec in records:
                    for k, v in list(rec.items()):
                        if hasattr(v, "isoformat"):
                            rec[k] = v.isoformat()
                        elif hasattr(v, "item"):
                            rec[k] = v.item()
                        elif v != v:  # NaN check
                            rec[k] = None
                result = {"symbol": symbol, "interval": interval, "bars": records}
        except Exception as exc:
            logger.warning("[MarketMCP] get_price_bars error for %s: %s", symbol, exc)
            result = {"error": str(exc), "symbol": symbol}

        return {"content": [{"type": "text", "text": json.dumps(result)}]}

    # ── Tool 2: Finnhub News ──────────────────────────────────────────────────

    @tool(
        "get_finnhub_news",
        "Get recent financial news headlines and pre-computed sentiment for a "
        "symbol from the JARVIS news cache (Finnhub + Brave Search). "
        "Returns headline list with sentiment scores.",
        {"symbol": str},
    )
    async def get_finnhub_news(args: dict) -> dict:
        symbol = str(args["symbol"]).upper()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{_ENGINE_BASE}/sentiment/news/{symbol}",
                    headers=_hdrs,
                )
            data = resp.json() if resp.status_code == 200 else {"error": f"HTTP {resp.status_code}", "symbol": symbol}
        except Exception as exc:
            logger.warning("[MarketMCP] get_finnhub_news error for %s: %s", symbol, exc)
            data = {"error": str(exc), "symbol": symbol}
        return {"content": [{"type": "text", "text": json.dumps(data)}]}

    # ── Tool 3: FRED Macro ────────────────────────────────────────────────────

    @tool(
        "get_fred_macro",
        "Get current macroeconomic snapshot: VIX level, 10Y Treasury yield, "
        "unemployment rate, and Fed Funds rate. Data sourced from FRED / CBOE.",
        {},
    )
    async def get_fred_macro(args: dict) -> dict:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{_ENGINE_BASE}/macro/snapshot", headers=_hdrs)
            data = resp.json() if resp.status_code == 200 else {"error": f"HTTP {resp.status_code}"}
        except Exception as exc:
            logger.warning("[MarketMCP] get_fred_macro error: %s", exc)
            data = {"error": str(exc)}
        return {"content": [{"type": "text", "text": json.dumps(data)}]}

    # ── Tool 4: Social Sentiment ──────────────────────────────────────────────

    @tool(
        "get_social_sentiment",
        "Get Reddit retail sentiment from WallStreetBets and futures subreddits "
        "(via ApeWisdom). Returns top trending tickers with mention counts and "
        "momentum, plus a match for the requested symbol if present.",
        {"symbol": str},
    )
    async def get_social_sentiment(args: dict) -> dict:
        symbol = str(args["symbol"]).upper()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{_ENGINE_BASE}/sentiment/reddit", headers=_hdrs)
            if resp.status_code == 200:
                all_data = resp.json()
                tickers = all_data.get("tickers", [])
                match = next(
                    (t for t in tickers if t.get("ticker", "").upper() == symbol),
                    None,
                )
                data = {
                    "symbol": symbol,
                    "in_trending": match is not None,
                    "symbol_data": match,
                    "top_10_trending": tickers[:10],
                }
            else:
                data = {"error": f"HTTP {resp.status_code}", "symbol": symbol}
        except Exception as exc:
            logger.warning("[MarketMCP] get_social_sentiment error for %s: %s", symbol, exc)
            data = {"error": str(exc), "symbol": symbol}
        return {"content": [{"type": "text", "text": json.dumps(data)}]}

    # ── Tool 5: Safety Status ─────────────────────────────────────────────────

    @tool(
        "get_safety_status",
        "Get JARVIS safety layer state: kill_switch_active (bool), daily_pnl "
        "(float), drawdown_pct (float), live_trading_enabled (bool). "
        "MUST be called before recommending any non-HOLD trade action.",
        {},
    )
    async def get_safety_status(args: dict) -> dict:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{_ENGINE_BASE}/safety/status", headers=_hdrs)
            data = resp.json() if resp.status_code == 200 else {"error": f"HTTP {resp.status_code}"}
        except Exception as exc:
            logger.warning("[MarketMCP] get_safety_status error: %s", exc)
            # Fail CLOSED — if we can't check safety, assume kill switch is active
            data = {"kill_switch_active": True, "error": str(exc)}
        return {"content": [{"type": "text", "text": json.dumps(data)}]}

    # ── Tool 6: Log Paper Trade ───────────────────────────────────────────────

    @tool(
        "log_paper_trade",
        "Log an approved paper trade entry to the JARVIS paper tracker. "
        "Only call when the fund manager has approved a BUY or SELL and "
        "live_trading_enabled is false. Never call for HOLD decisions.",
        {
            "symbol": str,
            "direction": str,
            "entry_price": float,
            "stop_price": float,
            "target_price": float,
            "contracts": int,
            "conviction": float,
        },
    )
    async def log_paper_trade(args: dict) -> dict:
        try:
            payload = {
                "symbol": str(args["symbol"]).upper(),
                "direction": str(args["direction"]).upper(),
                "entry_price": float(args["entry_price"]),
                "stop_price": float(args["stop_price"]),
                "target_price": float(args["target_price"]),
                "contracts": int(args.get("contracts", 1)),
                "conviction": float(args.get("conviction", 5.0)),
                "source": "sdk_pipeline",
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{_ENGINE_BASE}/portfolio/paper/trade",
                    json=payload,
                    headers=_hdrs,
                )
            if resp.status_code in (200, 201):
                data = {"logged": True, **resp.json()}
            else:
                data = {"logged": False, "error": f"HTTP {resp.status_code}"}
        except Exception as exc:
            logger.warning("[MarketMCP] log_paper_trade error: %s", exc)
            data = {"logged": False, "error": str(exc)}
        return {"content": [{"type": "text", "text": json.dumps(data)}]}

    @tool(
        "get_options_greeks",
        "Get real-time Greeks (Delta, Gamma, Theta, Vega, IV) for a specific "
        "option contract. Format: UNDERLYING_YYMMDDCSTRIKE (e.g. AAPL_260522C190).",
        {"symbol": str},
    )
    async def get_options_greeks(args: dict) -> dict:
        symbol = str(args["symbol"]).upper()
        try:
            result = await data_manager.get_options_greeks(symbol)
        except Exception as exc:
            logger.warning("[MarketMCP] get_options_greeks error for %s: %s", symbol, exc)
            result = {"error": str(exc), "symbol": symbol}
        return {"content": [{"type": "text", "text": json.dumps(result)}]}

    return create_sdk_mcp_server(
        "jarvis-market-tools",
        version="1.0.0",
        tools=[
            get_price_bars,
            get_finnhub_news,
            get_fred_macro,
            get_social_sentiment,
            get_safety_status,
            log_paper_trade,
            get_options_greeks,
        ],
    )
