# JARVIS TRADER — Monitoring & Observability

## Overview

JARVIS TRADER now includes comprehensive Prometheus metrics export and Grafana dashboard visualization for real-time monitoring of:

- **System Health**: API request rates, latency percentiles (p95, p99), error rates, uptime
- **Trading Performance**: Pipeline decisions, daily P&L, equity curve, orders by symbol
- **LLM Costs & Usage**: Model-specific call counts, daily costs, success rates, latency

## Quick Start

### 1. Start Infrastructure

```bash
cd infrastructure
docker compose up -d
```

This starts:
- **Prometheus** on port `9090` (http://localhost:9090)
- **Grafana** on port `3030` (http://localhost:3030)
- **JARVIS TRADER Engine** exposing metrics at `http://localhost:8010/metrics`

### 2. Access Grafana

1. Open http://localhost:3030
2. Login with:
   - Username: `admin`
   - Password: `jarvis_change_me` (set via `GF_ADMIN_PASSWORD` env var)
3. Navigate to **Dashboards** → **JARVIS TRADER Dashboards**

### 3. View Dashboards

Three pre-provisioned dashboards auto-load:

- **System Health**: Request rate, latency percentiles, error rate, uptime
- **Trading Performance**: Pipeline decisions, P&L gauge, equity curve, orders
- **LLM Costs & Usage**: LLM calls by model, daily cost, token usage, latency

## Architecture

```
┌─────────────────────────────────────────────┐
│ JARVIS TRADER Engine (Port 8010)            │
│ - FastAPI app with prometheus_fastapi_       │
│   instrumentator middleware                  │
│ - Exposes /metrics endpoint                  │
│ - Records custom metrics (pipeline, LLM,    │
│   orders, P&L, risk)                        │
└──────────────────┬──────────────────────────┘
                   │ (scrapes /metrics every 15s)
                   ▼
┌─────────────────────────────────────────────┐
│ Prometheus (Port 9090)                      │
│ - Time-series database                      │
│ - Scrapes JARVIS TRADER & self              │
│ - Retains metrics for 15 days (default)     │
└──────────────────┬──────────────────────────┘
                   │ (queries metrics)
                   ▼
┌─────────────────────────────────────────────┐
│ Grafana (Port 3030)                         │
│ - 3 pre-provisioned JSON dashboards         │
│ - Auto-loaded via provisioning config       │
│ - Real-time visualization & alerts          │
└─────────────────────────────────────────────┘
```

## Available Metrics

### Pipeline Metrics

- **jarvis_pipeline_runs_total** (Counter)
  - Labels: `symbol`, `decision`
  - Tracks total pipeline executions per symbol and decision type

- **jarvis_pipeline_duration_seconds** (Histogram)
  - Labels: `symbol`
  - Buckets: 0.5s, 1s, 2s, 5s, 10s, 30s, 60s
  - Execution time from start to end

### LLM Metrics

- **jarvis_llm_calls_total** (Counter)
  - Labels: `model`, `agent`, `success`
  - Tracks API calls per model and agent

- **jarvis_llm_cost_usd** (Counter)
  - Labels: `model`
  - Total USD spent on LLM API

### Order Metrics

- **jarvis_orders_total** (Counter)
  - Labels: `symbol`, `direction`, `status`
  - Tracks orders submitted per symbol, direction (long/short), and status

### Position & P&L Metrics

- **jarvis_daily_pnl_usd** (Gauge)
  - Current daily P&L in USD

- **jarvis_equity_usd** (Gauge)
  - Current account equity in USD

### Risk Metrics

- **jarvis_kill_switch_active** (Gauge)
  - Value: 0 (off) or 1 (active)
  - Kill switch status

- **jarvis_safety_events_total** (Counter)
  - Labels: `event_type`
  - Safety layer events (circuit breaker trips, margin violations, etc.)

- **jarvis_consecutive_losses** (Gauge)
  - Number of consecutive losing trades

### FastAPI System Metrics (Auto-instrumented)

- **fastapi_requests_total** (Counter)
  - HTTP requests by method, path, status code

- **fastapi_requests_duration_seconds** (Histogram)
  - HTTP request duration with percentiles

## Recording Metrics in Code

Use the monitoring module to record metrics:

```python
from monitoring.metrics import (
    record_pipeline_run,
    record_pipeline_duration,
    record_llm_call,
    record_llm_cost,
    record_order,
    set_daily_pnl,
    set_equity,
    set_kill_switch,
    record_safety_event,
    set_consecutive_losses,
)

# Pipeline execution
record_pipeline_run(symbol="MES", decision="BUY")
record_pipeline_duration(duration=2.5, symbol="MES")

# LLM calls
record_llm_call(model="claude-3-opus", agent="TechnicalAnalyst", success=True)
record_llm_cost(model="claude-3-opus", cost_usd=0.015)

# Orders
record_order(symbol="MES", direction="long", status="filled")

# P&L and risk
set_daily_pnl(pnl_usd=1250.50)
set_equity(equity_usd=102500.00)
set_kill_switch(active=False)

# Safety events
record_safety_event(event_type="margin_violation")

# Consecutive losses
set_consecutive_losses(count=2)
```

## Configuration

### Prometheus

Edit `infrastructure/prometheus/prometheus.yml`:

```yaml
scrape_configs:
  - job_name: "jarvis_trader_engine"
    static_configs:
      - targets: ["host.docker.internal:8010"]  # Change to your host IP if remote
    metrics_path: "/metrics"
    scrape_interval: 15s
```

- **scrape_interval**: How often Prometheus scrapes metrics (default: 15s)
- **targets**: FastAPI engine address (use `host.docker.internal` on Docker Desktop for localhost)

### Grafana

Edit environment variables in `infrastructure/docker-compose.yml`:

```yaml
environment:
  GF_SECURITY_ADMIN_PASSWORD: your_password
  GF_USERS_ALLOW_SIGN_UP: "false"
  GF_PATHS_PROVISIONING: /etc/grafana/provisioning
```

**Admin password** is set on first login. Change it in Grafana UI: Settings → Admin → Change Password.

### FastAPI Instrumentation

In `engine/main.py`:

```python
from prometheus_fastapi_instrumentator import Instrumentator

# Auto-instruments all HTTP endpoints
Instrumentator().instrument(app).expose(app, endpoint="/metrics", tags=["metrics"])
```

This automatically tracks:
- Request count
- Request duration (histogram)
- Request status codes
- Error rates

## Dashboard Descriptions

### System Health Dashboard

**Time Range**: 1 hour

- **Request Rate**: Stacked bar chart of requests/sec by method and path
- **Latency Percentiles**: p95 and p99 latency in seconds
- **Error Rate**: 4xx and 5xx error rates (requests/sec)
- **API Uptime**: Gauge showing uptime percentage (green > 99%, red < 99%)

**Use for**: Detecting API performance degradation, high error rates, bottlenecks.

### Trading Performance Dashboard

**Time Range**: 24 hours

- **Pipeline Decisions**: Stacked bar chart of pipeline runs by symbol and decision type
- **Daily P&L**: Gauge showing current daily profit/loss in USD
- **Equity Curve**: Line chart of equity over time with min/max/last values
- **Orders by Symbol & Direction**: Stacked bars of orders by symbol, direction, and status
- **Kill Switch Status**: Gauge showing kill switch active (0) or inactive (1)

**Use for**: Tracking trading activity, monitoring profitability, identifying drawdowns.

### LLM Costs & Usage Dashboard

**Time Range**: 24 hours

- **LLM Calls by Model**: Stacked bar chart of API calls per model
- **Daily LLM Cost**: Gauge showing total daily LLM spending in USD
- **Cost Over Time**: Line chart of costs per hour bucketed by model
- **Pipeline Latency (p95)**: Scatter plot of pipeline execution latency in ms
- **LLM Call Success Rate**: Line chart of success rate % by model

**Use for**: Controlling API costs, identifying slow models, monitoring reliability.

## Alerting (Optional)

To add alerts, create an `infrastructure/prometheus/alert_rules.yml`:

```yaml
groups:
  - name: jarvis_trading
    interval: 1m
    rules:
      # Alert if daily loss exceeds $5,000
      - alert: DailyLossExceeded
        expr: jarvis_daily_pnl_usd < -5000
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Daily loss exceeded $5,000"
          description: "Current daily P&L: {{ $value }} USD"

      # Alert if LLM cost exceeds $50/day
      - alert: HighLLMCost
        expr: increase(jarvis_llm_cost_usd[1d]) > 50
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High LLM API costs"
          description: "Daily cost: {{ $value }} USD"

      # Alert if API error rate > 5%
      - alert: HighErrorRate
        expr: (rate(fastapi_requests_total{status=~"5.."}[5m]) / rate(fastapi_requests_total[5m])) > 0.05
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High API error rate"
          description: "Error rate: {{ $value | humanizePercentage }}"
```

Add to `prometheus.yml`:

```yaml
rule_files:
  - "alert_rules.yml"

alerting:
  alertmanagers:
    - static_configs:
        - targets: []  # Add Alertmanager address if configured
```

## Troubleshooting

### Prometheus can't scrape JARVIS TRADER

**Error**: `connection refused` or `no route to host`

**Solution**:
1. Check JARVIS TRADER is running on port 8010
2. In Docker, replace `localhost:8010` with `host.docker.internal:8010`
3. For remote hosts, use the actual IP address

### Grafana dashboards not loading

**Solution**:
1. Check provisioning path: `docker exec jarvis_grafana cat /etc/grafana/provisioning/dashboards/provisioning.yml`
2. Verify JSON files exist: `ls infrastructure/grafana/dashboards/`
3. Restart Grafana: `docker compose restart grafana`
4. Check logs: `docker logs jarvis_grafana`

### Missing metrics in dashboards

**Solution**:
1. Ensure metrics are being recorded in the trading pipeline
2. Check Prometheus targets: http://localhost:9090/targets
3. Query metrics directly: http://localhost:9090/graph?query=jarvis_daily_pnl_usd
4. Review FastAPI logs for instrumentation errors

### High Prometheus disk usage

**Solution**:
1. Reduce `scrape_interval` in `prometheus.yml` (default: 15s)
2. Set retention policy in `docker-compose.yml`:
   ```yaml
   command:
     - "--storage.tsdb.retention.time=7d"  # Keep only 7 days
   ```
3. Prune old data: `docker exec jarvis_prometheus promtool query instant 'up' --storage.tsdb.path=/prometheus`

## References

- [Prometheus Documentation](https://prometheus.io/docs/)
- [Grafana Documentation](https://grafana.com/docs/grafana/)
- [FastAPI Prometheus Instrumentator](https://github.com/trallnag/prometheus-fastapi-instrumentator)
- [Prometheus Metrics Types](https://prometheus.io/docs/concepts/metric_types/)
