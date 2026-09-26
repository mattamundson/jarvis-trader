"""
JARVIS TRADER — Pydantic v2 Response Models
=============================================
Strongly-typed response models for all API endpoints.
Enables automatic validation, OpenAPI schema generation,
and client code generation.
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

JARVIS_SUPPORTED_PERIODS = {"1d", "5d", "1mo", "3mo", "6mo", "ytd", "1y", "2y", "5y", "10y", "max"}

# ── Enums ────────────────────────────────────────────────────────────────────


class StatusEnum(str, Enum):
    """System status values."""

    ok = "ok"
    degraded = "degraded"
    error = "error"
    healthy = "healthy"
    kill_switch_active = "kill_switch_active"
    circuit_breaker_tripped = "circuit_breaker_tripped"


class HealthStatusEnum(str, Enum):
    """Health status values."""

    healthy = "healthy"
    degraded = "degraded"
    error = "error"


class SignalEnum(str, Enum):
    """Trading signal values."""

    buy = "buy"
    sell = "sell"
    hold = "hold"
    neutral = "neutral"
    bullish = "bullish"
    bearish = "bearish"


class TvMcpStatus(str, Enum):
    """TradingView MCP connection status."""

    not_running = "not_running"
    connecting = "connecting"
    healthy = "healthy"
    degraded = "degraded"
    disabled = "disabled"


class OrderActionEnum(str, Enum):
    """Order action values."""

    buy = "buy"
    sell = "sell"
    sell_short = "sell_short"
    buy_to_cover = "buy_to_cover"


# ── Base Models ──────────────────────────────────────────────────────────────


class BaseResponse(BaseModel):
    """Base response model with common fields."""

    model_config = ConfigDict(from_attributes=True)


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Detailed error information")
    status_code: int = Field(..., description="HTTP status code")


class PaginatedResponse(BaseModel):
    """Base for paginated responses."""

    count: int = Field(..., description="Total number of items")
    page: int = Field(1, description="Current page number")
    page_size: int = Field(50, description="Items per page")


# ── Health Check Models ──────────────────────────────────────────────────────


class PaperTradingStatus(BaseModel):
    """Paper trading subsystem status."""

    paper_kill_switch: bool = Field(False, description="Paper trading kill switch state")
    safety_kill_switch: bool = Field(False, description="Safety layer kill switch state")
    open_positions: int = Field(0, description="Number of open paper positions")
    scheduler_running: bool = Field(False, description="Whether the scheduler is running")
    scheduler_jobs: List[str] = Field(
        default_factory=list, description="Active scheduler job names"
    )


class CacheStatus(BaseModel):
    """Cache subsystem status."""

    data_files: int = Field(0, description="Number of cached data files")
    results_files: int = Field(0, description="Number of cached result files")


class HealthResponse(BaseModel):
    """Basic health check endpoint response."""

    status: str = Field(..., description="System status")
    version: str = Field(..., description="API version")
    timestamp: str = Field(..., description="Current timestamp")
    live_trading: bool = Field(False, description="Whether live trading is active")
    kill_switch_active: bool = Field(False, description="Whether kill switch is active")
    paper_mode: bool = Field(True, description="Whether paper trading mode is active")
    database: str = Field("disconnected", description="Database connection status")
    ibkr_connected: bool = Field(
        False,
        description="Whether IBKR is connected (OR of execution + data connectors — kept for backward compat)",
    )
    ibkr_execution_connected: Optional[bool] = Field(
        None,
        description="Whether the IBKR execution (paper/live trading) connector is connected — this is the path /brokers/positions queries. NOTE: this is the connector's CACHED belief; it can read True after the Gateway logs out. Trust execution_connected_verified for enforcement decisions.",
    )
    execution_connected_verified: Optional[bool] = Field(
        None,
        description="Reconciled execution truth = ibkr_execution_connected AND ibgateway_alive. The field stop-enforcement/dashboard should trust — cannot report execution-ready while the Gateway port is dead.",
    )
    ib_execution_stale: Optional[bool] = Field(
        None,
        description="True when the execution connector's cached belief is 'connected' but the Gateway port is dead (logged out) — the silent stop-enforcement hazard (2026-06-01 class) made observable.",
    )
    ibkr_data_connected: Optional[bool] = Field(
        None,
        description="Whether the IBKR market-data connector is connected — independent lifecycle from the execution connector",
    )
    ibgateway_alive: Optional[bool] = Field(
        None,
        description="Whether IB Gateway is accepting TCP connections on the configured IB port (process-level liveness). Distinct from ibkr_*_connected: the Gateway can be up (port open) while a connector has dropped (recoverable via POST /data/reconnect), or the Gateway itself can be down (port closed) — the failure mode that left trade #178's stop unenforced for 13h.",
    )
    ibgateway_port: Optional[int] = Field(
        None, description="The IB port probed for ibgateway_alive (4002 paper / 4001 live)"
    )
    ibkr_broker_probe_ok: Optional[bool] = Field(
        True,
        description="Whether the IBKR health-check RPC probes (latency/net_liq/open_orders) all responded. False = socket up but RPCs failing (degraded broker); distinct from ibkr_*_connected which is socket-level only.",
    )
    ibkr_degraded_reason: Optional[str] = Field(
        None,
        description="Which broker probe(s) failed (e.g. 'latency:TimeoutError'), populated only when ibkr_broker_probe_ok=false",
    )
    schwab_connected: bool = Field(False, description="Whether Schwab is connected")
    tos_rtd_connected: bool = Field(
        False,
        description=(
            "Whether the thinkorswim desktop RTD feed (Tier 0 market-data source) "
            "has an active RTD session. False when TOS is not running or the adapter "
            "failed to start — quotes then fall through to IBKR/Polygon."
        ),
    )
    tos_rtd_details: Optional[dict] = Field(
        None,
        description=(
            "thinkorswim RTD session detail (source, server_started, heartbeat_ok, "
            "heartbeat_age_s, observed_topics, priced_topics, last_error). "
            "Populated only when the adapter is injected."
        ),
    )
    uptime_seconds: float = Field(0, description="Server uptime in seconds")
    paper_trading: Optional[PaperTradingStatus] = Field(None, description="Paper trading status")
    cache: Optional[CacheStatus] = Field(None, description="Cache status")
    llm_available: Optional[bool] = Field(
        True, description="Whether Anthropic API key is configured"
    )
    llm_path_healthy: Optional[bool] = Field(
        True,
        description="Whether the last-observed LLM call succeeded (false = credits/auth outage)",
    )
    vertex_failover_count: int = Field(
        0,
        description="Cumulative count (process lifetime) of Anthropic credit-exhaustion failovers routed to Claude-on-Vertex.",
    )
    google_fallback_count: int = Field(
        0,
        description="Cumulative count (process lifetime) of LLM calls served by the Gemini fallback (proactive routing + credit-exhaustion fallback).",
    )
    llm_path_details: Optional[Dict[str, Any]] = Field(
        None, description="Populated only when llm_path_healthy=false"
    )
    llm_providers: Optional[Dict[str, Any]] = Field(
        None,
        description="Provider-redundancy summary: active leg, providers_available count, and single_leg_warning (true when the serving leg has no backup behind it). Added in 94e9e5b; response dict populated it but this response_model field was missing, so FastAPI stripped it from /health until 2026-06-06.",
    )
    pending_approvals: Optional[Dict[str, Any]] = Field(
        None,
        description="Approval-queue visibility: {count, oldest_age_min}. A candidate that queues but is never approved (e.g. silently failing notifications) stalls the live-fill path; surfaced so a stuck queue is observable.",
    )
    futures_sentiment: Optional[Dict[str, Any]] = Field(
        None,
        description="Corey #market-updates freshness + structured-bias extraction health: {quality, age_days, latest_timestamp, threshold_days, extraction_quality, extraction_lag_days, latest_bias_date}. extraction_quality='degraded' flags the LLM structured-bias path falling behind ingestion (the 2026-06-29 credit-exhaustion outage that ran two days undetected). Like llm_providers above, _health_inner populated this but the response_model field was missing, so FastAPI stripped it from /health — added 2026-06-30.",
    )
    tradingview_mcp_healthy: Optional[bool] = Field(
        True,
        description="Whether TradingView Desktop CDP port 9222 responds (false = TV MCP bar source unavailable)",
    )
    tradingview_mcp_details: Optional[str] = Field(
        None, description="Short diagnostic populated only when tradingview_mcp_healthy=false"
    )
    tv_mcp_status: Optional[str] = Field(
        None, description="TV MCP status: not_running | connecting | healthy | degraded | disabled"
    )
    brier_30d_rolling: Optional[float] = Field(
        None,
        description="30-day rolling mean Brier score across agents with ≥ min_trades closed signals. 0 = perfect calibration, 1 = always confidently wrong. None when no agent has enough data.",
    )
    batch_jobs_health: Optional[Dict[str, Any]] = Field(
        None,
        description="Anthropic Message Batches summary: {jobs_by_status, unconsumed_results}. Non-blocking — batches are async by design, so this never flips top-level status to degraded, only surfaces counts for observability. Populated by engine/llm/batch_client.py's JarvisBatchClient.get_batch_health_summary(). Field must exist here or _health_inner's dict key gets silently stripped by FastAPI's response_model, same class of bug as llm_providers/futures_sentiment above.",
    )
    market_data_fresh: Optional[bool] = Field(
        True,
        description="P3-1: whether every currently-authorized/tradeable symbol's `market:latest:{symbol}` Redis fabric entry is within MARKET_DATA_STALE_AFTER_S (900s, same threshold as /system/data-integrity). False flips top-level status to degraded. True (not stale) when the fabric can't be reached at all — a different, defense-in-depth signal (ibgateway_alive/tv_mcp_healthy) already covers total data-path outage.",
    )
    market_data_stale_symbols: Optional[List[str]] = Field(
        None,
        description="Symbols (subset of the authorized/tradeable set) whose Redis fabric entry is present but stale. Empty/None when market_data_fresh=True.",
    )


class SubsystemStatus(BaseModel):
    """Individual subsystem status — accepts any extra fields from subsystem dicts.

    `extra="allow"` is load-bearing: subsystems attach observability fields the
    dashboard reads (ib_gateway.data_source / watchdog / per_symbol_freshness,
    llm.provider / fallback_active). With `extra="ignore"` those were silently
    dropped by the response model and never reached the client.
    """

    model_config = ConfigDict(extra="allow")

    status: str = Field(..., description="Subsystem status")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional details")
    error: Optional[str] = Field(None, description="Error message if any")
    kill_switch_active: Optional[bool] = Field(None, description="Kill switch state")
    all_clear: Optional[bool] = Field(None, description="Whether all checks pass")
    open_positions: Optional[int] = Field(None, description="Open positions count")
    daily_pnl: Optional[float] = Field(None, description="Daily P&L")


class FullHealthResponse(BaseModel):
    """Comprehensive health check with subsystem status."""

    overall: str = Field(..., description="Overall system health")
    timestamp: str = Field(..., description="Current timestamp")
    uptime_seconds: float = Field(0, description="Server uptime in seconds")
    version: str = Field(..., description="API version")
    phase: str = Field("paper_trading", description="Current trading phase")
    subsystems: Dict[str, SubsystemStatus] = Field(
        default_factory=dict, description="Subsystem health details"
    )


# ── IB Gateway Models ───────────────────────────────────────────────────────


class IBConnectionTestResponse(BaseModel):
    """IB Gateway connection test result."""

    connected: bool = Field(..., description="Whether connection is active")
    gateway_version: Optional[str] = Field(None, description="Gateway version")
    server: Optional[str] = Field(None, description="Server address")
    client_id: Optional[int] = Field(None, description="Client ID")
    latency_ms: Optional[float] = Field(None, description="Connection latency in ms")
    error: Optional[str] = Field(None, description="Error message if connection failed")


class IBConnectResponse(BaseModel):
    """IB Gateway connection attempt response."""

    status: str = Field(..., description="Connection status")
    message: str = Field(..., description="Status message")
    connected: bool = Field(False, description="Whether connection succeeded")


# ── Safety & Risk Models ────────────────────────────────────────────────────


class SafetyStatusResponse(BaseModel):
    """Current safety layer state."""

    kill_switch_active: bool = Field(False, description="Kill switch state")
    kill_switch_reason: Optional[str] = Field(None, description="Kill switch reason")
    daily_pnl: float = Field(0, description="Today's P&L")
    daily_limit: float = Field(-5000, description="Daily loss limit")
    daily_pnl_pct: float = Field(0, description="Daily P&L as percentage")
    daily_limit_pct: float = Field(-0.10, description="Daily loss limit as percentage")
    daily_limit_breached: bool = Field(False, description="Whether daily limit is breached")
    drawdown_pct: float = Field(0, description="Current drawdown percentage")
    drawdown_limit_pct: float = Field(-0.20, description="Max drawdown limit")
    drawdown_breached: bool = Field(False, description="Whether drawdown limit is breached")
    portfolio_equity: float = Field(0, description="Current portfolio equity")
    starting_balance: float = Field(0, description="Starting balance")
    pnl_source: str = Field("sqlite", description="P&L data source")
    current_balance: float = Field(0, description="Current balance")
    orders_last_minute: Optional[int] = Field(
        None, description="Orders recorded in the last minute"
    )
    consecutive_losses: Optional[int] = Field(
        None, description="Consecutive losing trades (loss tracker)"
    )
    equity_peak: Optional[float] = Field(None, description="Peak equity from safety snapshot")
    daily_realized_pnl: Optional[float] = Field(None, description="Daily realized P&L component")
    orders_per_minute_limit: Optional[int] = Field(
        None, description="Configured max orders per minute (rate throttle)"
    )
    last_kill_switch_ts: Optional[str] = Field(
        None,
        description="ISO-8601 UTC timestamp of the most recent kill-switch activation. Survives deactivate + restart. None if it has never fired.",
    )
    last_kill_switch_reason_value: Optional[str] = Field(
        None, description="Reason value of the most recent kill-switch activation (history)"
    )
    time_since_kill_switch_sec: Optional[float] = Field(
        None,
        description="Seconds since the last kill-switch activation, or None if it has never fired. Lets a consumer tell a just-recovered-from-halt system from one running clean for hours.",
    )


class CircuitBreakerStatus(BaseModel):
    """Detailed circuit breaker snapshot."""

    daily_pnl: float = Field(0, description="Today's P&L")
    daily_limit: float = Field(-5000, description="Daily loss limit")
    daily_pnl_pct: float = Field(0, description="Daily P&L percentage")
    daily_limit_pct: float = Field(-0.10, description="Daily limit percentage")
    daily_limit_breached: bool = Field(False, description="Daily limit breach status")
    drawdown_pct: float = Field(0, description="Current drawdown")
    drawdown_limit_pct: float = Field(-0.20, description="Max drawdown limit")
    drawdown_breached: bool = Field(False, description="Drawdown breach status")
    kill_switch_active: bool = Field(False, description="Kill switch state")
    kill_switch_reason: Optional[str] = Field(None, description="Kill switch reason")
    pnl_source: str = Field("sqlite", description="P&L data source")
    current_balance: float = Field(0, description="Current balance")
    starting_balance: float = Field(0, description="Starting balance")
    orders_last_minute: int = Field(0, description="Orders in last minute")
    all_clear: bool = Field(True, description="Whether all checks pass")


class SafetyConfigResponse(BaseModel):
    """Risk configuration (read-only)."""

    max_daily_loss_pct: float = Field(-0.10, description="Maximum daily loss percentage")
    max_drawdown_pct: float = Field(-0.20, description="Maximum drawdown percentage")
    max_orders_per_minute: int = Field(30, description="Max orders per minute")
    min_order_size: float = Field(1.0, description="Minimum order size")


class KillSwitchToggleResponse(BaseModel):
    """Kill switch activation/deactivation result."""

    status: str = Field(..., description="Kill switch status")
    reason: Optional[str] = Field(None, description="Activation reason")
    activated_at: Optional[str] = Field(None, description="Activation timestamp")


# ── Analysis Models ──────────────────────────────────────────────────────────


class TechnicalAnalysisResponse(BaseModel):
    """Technical analysis results."""

    symbol: str = Field(..., description="Analyzed symbol")
    timestamp: str = Field(..., description="Analysis timestamp")
    timeframe: str = Field("5m", description="Timeframe used")
    signal: float = Field(
        ...,
        description="Trading signal — numeric score from the TechnicalAnalyst (e.g. -1..1)",
    )
    confidence: float = Field(..., description="Signal confidence (0-1)")
    trend: Optional[str] = Field(None, description="Current trend")
    regime: Optional[str] = Field(None, description="Market regime")
    is_overbought: bool = Field(False, description="Whether asset is overbought")
    is_oversold: bool = Field(False, description="Whether asset is oversold")
    summary: Optional[str] = Field(None, description="Analysis summary")
    reasoning: Optional[str] = Field(None, description="Detailed reasoning")
    scores: Optional[Dict[str, float]] = Field(None, description="Component scores")
    levels: Optional[Dict[str, Any]] = Field(None, description="Support/resistance levels")
    raw_indicators: Optional[Dict[str, Any]] = Field(None, description="Raw indicator values")


class BarsResponse(BaseModel):
    """Historical OHLCV data with VWAP and STC per bar."""

    symbol: str = Field(..., description="Symbol")
    timeframe: str = Field(..., description="Timeframe")
    bars: List[Dict[str, Any]] = Field(
        default_factory=list, description="OHLCV bars (each bar includes vwap and stc fields)"
    )
    count: int = Field(0, description="Number of bars")
    vwap_current: Optional[float] = Field(None, description="Current VWAP value (last bar)")
    vwap_trend: Optional[str] = Field(None, description="'above' or 'below' — price vs VWAP")


class RedditSentimentResponse(BaseModel):
    """Reddit trending tickers."""

    filter: str = Field("all-stocks", description="Filter applied")
    tickers: List[Dict[str, Any]] = Field(default_factory=list, description="Trending tickers")


class NewsSentimentResponse(BaseModel):
    """News sentiment via Finnhub."""

    symbol: str = Field(..., description="Symbol analyzed")
    sentiment: Dict[str, Any] = Field(default_factory=dict, description="Sentiment data")


class JarvisQuickAnalysisRequest(BaseModel):
    """Quick Gemini-backed Jarvis snapshot request."""

    symbol: str = Field(..., min_length=1, max_length=20, description="Ticker symbol")
    period: str = Field(default="5d", description="Historical period to analyze")

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("symbol cannot be empty")
        return normalized

    @field_validator("period")
    @classmethod
    def normalize_period(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in JARVIS_SUPPORTED_PERIODS:
            allowed = ", ".join(sorted(JARVIS_SUPPORTED_PERIODS))
            raise ValueError(f"period must be one of: {allowed}")
        return normalized


class JarvisQuickAnalysisResponse(BaseResponse):
    """Quick Gemini-backed Jarvis snapshot response."""

    symbol: str = Field(..., description="Analyzed ticker symbol")
    period: str = Field(..., description="Historical period used")
    analysis: str = Field(..., description="Generated Jarvis analysis text")
    model: str = Field(..., description="LLM model used to generate the analysis")
    generated_at: str = Field(..., description="UTC timestamp for when the analysis was generated")


# ── Portfolio Models ─────────────────────────────────────────────────────────


class Position(BaseModel):
    """Single portfolio position."""

    symbol: str = Field(..., description="Position symbol")
    quantity: float = Field(..., description="Position quantity")
    average_price: float = Field(..., description="Average entry price")
    current_price: float = Field(0, description="Current market price")
    unrealized_pnl: float = Field(0, description="Unrealized P&L")


class PortfolioResponse(BaseModel):
    """Current portfolio state."""

    total_equity: float = Field(0, description="Total portfolio equity")
    cash_balance: float = Field(0, description="Cash balance")
    unrealized_pnl: float = Field(0, description="Total unrealized P&L")
    realized_pnl: float = Field(0, description="Total realized P&L")
    daily_pnl: float = Field(0, description="Today's P&L")
    margin_used: float = Field(0, description="Margin in use")
    margin_available: float = Field(0, description="Available margin")
    positions: List[Position] = Field(default_factory=list, description="Open positions")


# ── Paper Trading Models ────────────────────────────────────────────────────


class PaperPositionsResponse(BaseModel):
    """Open paper trading positions."""

    positions: List[Dict[str, Any]] = Field(default_factory=list, description="Open positions")
    count: int = Field(0, description="Number of positions")


class PaperTradeResponse(BaseModel):
    """Trade submission result."""

    status: str = Field(..., description="Trade status")
    trade_id: Optional[str] = Field(None, description="Trade identifier")
    symbol: Optional[str] = Field(None, description="Traded symbol")
    action: Optional[str] = Field(None, description="Trade action")
    quantity: Optional[float] = Field(None, description="Trade quantity")
    entry_price: Optional[float] = Field(None, description="Entry price")


class PaperPerformanceResponse(BaseModel):
    """Paper trading performance metrics."""

    performance: Dict[str, Any] = Field(default_factory=dict, description="Performance metrics")


# ── Signals Models ───────────────────────────────────────────────────────────


class PendingSignalsResponse(BaseModel):
    """Signals from daily scanner."""

    signals: List[Dict[str, Any]] = Field(default_factory=list, description="Pending signals")
    count: int = Field(0, description="Number of signals")


# ── Kill Switch Models ───────────────────────────────────────────────────────


class PaperKillSwitchStatus(BaseModel):
    """Paper trading kill switch state."""

    active: bool = Field(False, description="Whether kill switch is active")
    reason: Optional[str] = Field(None, description="Activation reason")
    activated_at: Optional[str] = Field(None, description="Activation timestamp")


class PaperKillSwitchToggleResponse(BaseModel):
    """Paper trading kill switch toggle result."""

    status: str = Field(..., description="Toggle status")
    reason: Optional[str] = Field(None, description="Activation reason")
    activated_at: Optional[str] = Field(None, description="Activation timestamp")


class ResetSignalsResponse(BaseModel):
    """Pending signals reset result."""

    status: str = Field(..., description="Reset status")
    signals_cleared: int = Field(0, description="Number of signals cleared")


# ── Historical Data Models ───────────────────────────────────────────────────


class TradeHistoryResponse(BaseModel):
    """Historical trades."""

    trades: List[Dict[str, Any]] = Field(default_factory=list, description="Trade records")
    count: int = Field(0, description="Number of trades")


class DailyPnLResponse(BaseModel):
    """Daily P&L history."""

    daily_pnl: List[Dict[str, Any]] = Field(default_factory=list, description="Daily P&L records")
    days: int = Field(0, description="Number of trading days")
    count: int = Field(0, description="Number of records")


class DecisionHistoryResponse(BaseModel):
    """Agent decisions."""

    decisions: List[Dict[str, Any]] = Field(default_factory=list, description="Decision records")
    count: int = Field(0, description="Number of decisions in this page (bounded by limit)")
    total: int = Field(0, description="True total decision row count, ignoring limit")


class StatsSummaryResponse(BaseModel):
    """Performance statistics."""

    total_trades: int = Field(0, description="Total number of trades")
    winning_trades: int = Field(0, description="Number of winning trades")
    losing_trades: int = Field(0, description="Number of losing trades")
    win_rate: float = Field(0, description="Win rate (0-1)")
    total_pnl: float = Field(0, description="Total P&L")
    avg_win: float = Field(0, description="Average winning trade")
    avg_loss: float = Field(0, description="Average losing trade")
    profit_factor: float = Field(0, description="Profit factor")
    best_trade: float = Field(0, description="Best single trade")
    worst_trade: float = Field(0, description="Worst single trade")


class DrawdownResponse(BaseModel):
    """Drawdown metrics."""

    current_drawdown_pct: float = Field(0, description="Current drawdown percentage")
    max_drawdown_pct: float = Field(0, description="Maximum drawdown percentage")
    peak_equity: float = Field(0, description="Peak equity value")
    current_equity: float = Field(0, description="Current equity value")


# ── WebSocket Models ─────────────────────────────────────────────────────────


class WebSocketClient(BaseModel):
    """Connected WebSocket client info."""

    client_id: str = Field(..., description="Client identifier")
    connected_at: str = Field(..., description="Connection timestamp")
    event_types_subscribed: List[str] = Field(
        default_factory=list, description="Subscribed event types"
    )


class WebSocketStatusResponse(BaseModel):
    """WebSocket manager status."""

    manager_active: bool = Field(False, description="Whether manager is active")
    connected_clients: int = Field(0, description="Number of connected clients")
    clients: List[WebSocketClient] = Field(default_factory=list, description="Client details")
    events_sent_total: int = Field(0, description="Total events sent")
    events_sent_last_hour: int = Field(0, description="Events sent in last hour")
