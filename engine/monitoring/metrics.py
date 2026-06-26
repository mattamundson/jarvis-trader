"""
Prometheus Metrics for JARVIS TRADER
=====================================
Centralizes custom metrics tracking for the trading pipeline, LLM costs, orders, and risk.

Metrics exposed:
- jarvis_pipeline_runs_total: Counter for pipeline executions
- jarvis_pipeline_duration_seconds: Histogram for pipeline execution duration
- jarvis_llm_calls_total: Counter for LLM API calls
- jarvis_llm_cost_usd: Counter for total LLM costs
- jarvis_orders_total: Counter for submitted orders
- jarvis_daily_pnl_usd: Gauge for daily P&L
- jarvis_equity_usd: Gauge for current equity
- jarvis_kill_switch_active: Gauge for kill switch status (0 or 1)
- jarvis_safety_events_total: Counter for safety layer events
- jarvis_consecutive_losses: Gauge for consecutive losing trades
"""

from prometheus_client import Counter, Gauge, Histogram

# ── Pipeline Metrics ──────────────────────────────────────────────────────
pipeline_runs = Counter(
    name="jarvis_pipeline_runs_total",
    documentation="Total number of trading pipeline runs",
    labelnames=["symbol", "decision"],
)

pipeline_duration = Histogram(
    name="jarvis_pipeline_duration_seconds",
    documentation="Duration of trading pipeline execution in seconds",
    labelnames=["symbol"],
    buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
)

# ── LLM Metrics ───────────────────────────────────────────────────────────
llm_calls = Counter(
    name="jarvis_llm_calls_total",
    documentation="Total number of LLM API calls",
    labelnames=["model", "agent", "success"],
)

llm_cost = Counter(
    name="jarvis_llm_cost_usd",
    documentation="Total USD cost of LLM API calls",
    labelnames=["model"],
)

# ── Order Metrics ─────────────────────────────────────────────────────────
orders_total = Counter(
    name="jarvis_orders_total",
    documentation="Total number of orders submitted",
    labelnames=["symbol", "direction", "status"],
)

# ── Position & P&L Metrics ───────────────────────────────────────────────
daily_pnl = Gauge(
    name="jarvis_daily_pnl_usd",
    documentation="Current daily P&L in USD",
)

equity = Gauge(
    name="jarvis_equity_usd",
    documentation="Current account equity in USD",
)

# ── Risk Metrics ──────────────────────────────────────────────────────────
kill_switch_active = Gauge(
    name="jarvis_kill_switch_active",
    documentation="Kill switch status (0=off, 1=active)",
)

safety_events = Counter(
    name="jarvis_safety_events_total",
    documentation="Total number of safety layer events",
    labelnames=["event_type"],
)

consecutive_losses = Gauge(
    name="jarvis_consecutive_losses",
    documentation="Number of consecutive losing trades",
)


# ── Helper functions for metric recording ──────────────────────────────────


def record_pipeline_run(symbol: str, decision: str):
    """Record a pipeline execution."""
    pipeline_runs.labels(symbol=symbol, decision=decision).inc()


def record_pipeline_duration(duration: float, symbol: str):
    """Record pipeline execution duration."""
    pipeline_duration.labels(symbol=symbol).observe(duration)


def record_llm_call(model: str, agent: str, success: bool):
    """Record an LLM API call."""
    llm_calls.labels(model=model, agent=agent, success=str(success)).inc()


def record_llm_cost(model: str, cost_usd: float):
    """Record LLM API cost."""
    llm_cost.labels(model=model).inc(cost_usd)


def record_order(symbol: str, direction: str, status: str):
    """Record an order submission."""
    orders_total.labels(symbol=symbol, direction=direction, status=status).inc()


def set_daily_pnl(pnl_usd: float):
    """Set the daily P&L gauge."""
    daily_pnl.set(pnl_usd)


def set_equity(equity_usd: float):
    """Set the equity gauge."""
    equity.set(equity_usd)


def set_kill_switch(active: bool):
    """Set the kill switch status (0 or 1)."""
    kill_switch_active.set(1 if active else 0)


def record_safety_event(event_type: str):
    """Record a safety layer event."""
    safety_events.labels(event_type=event_type).inc()


def set_consecutive_losses(count: int):
    """Set the consecutive losses gauge."""
    consecutive_losses.set(count)


def sync_safety_gauges(snapshot: dict) -> None:
    """Set the safety-critical gauges from a safety-status snapshot dict.

    Reads the same keys the ``/safety/status`` handler returns. Tolerant: a key
    that is absent leaves its gauge untouched (not reset to 0), and the call
    never raises — observability must not be able to break the safety endpoint.
    """
    try:
        if "kill_switch_active" in snapshot:
            set_kill_switch(bool(snapshot["kill_switch_active"]))
        if "daily_pnl" in snapshot:
            set_daily_pnl(float(snapshot["daily_pnl"]))
        if "portfolio_equity" in snapshot:
            set_equity(float(snapshot["portfolio_equity"]))
        if "consecutive_losses" in snapshot:
            set_consecutive_losses(int(snapshot["consecutive_losses"]))
    except (TypeError, ValueError):
        # Malformed snapshot value — skip rather than break the caller.
        pass


# ── Exposition ──────────────────────────────────────────────────────────────


def mount_metrics(app) -> None:
    """Mount the Prometheus exposition endpoint at ``/metrics`` on ``app``.

    Importing this module already registered the ``jarvis_*`` families with the
    default registry; ``make_asgi_app()`` serves them in text exposition format.
    ``/metrics`` is in ``middleware.auth.EXEMPT_PATHS`` so Prometheus can scrape
    it without the engine API key (read-only, loopback-bound).
    """
    from prometheus_client import make_asgi_app

    app.mount("/metrics", make_asgi_app())
