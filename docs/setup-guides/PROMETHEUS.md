# Prometheus & Grafana Implementation Summary

## Completed Steps

All 7 steps have been successfully implemented for JARVIS TRADER monitoring:

### ✅ STEP 1: Architecture Review
- Read engine/main.py (2387 lines) — FastAPI app with lifespan context manager
- Read infrastructure/docker-compose.yml — Existing Grafana setup identified
- Identified FastAPI lifespan initialization point for metric recording

### ✅ STEP 2: Dependencies Added
**File Modified**: `engine/requirements-core.txt`
```
prometheus-fastapi-instrumentator==6.1.0  # Prometheus metrics export for FastAPI
```

### ✅ STEP 3: Prometheus Instrumentation Wired Into FastAPI
**Files Modified**: `engine/main.py`

**Imports Added**:
```python
from prometheus_fastapi_instrumentator import Instrumentator
from monitoring.metrics import set_kill_switch, set_daily_pnl, set_equity
```

**Instrumentation Setup**:
```python
# After app creation (line 453)
Instrumentator().instrument(app).expose(app, endpoint="/metrics", tags=["metrics"])
```

**Custom Metrics Module Created**: `engine/monitoring/metrics.py`
- Defines 10 Prometheus metrics with labels
- Provides helper functions for recording metrics in code
- Easily imported and used throughout the trading pipeline

**Metrics Included**:
- `jarvis_pipeline_runs_total` — Pipeline execution counter
- `jarvis_pipeline_duration_seconds` — Execution duration histogram
- `jarvis_llm_calls_total` — LLM API call counter
- `jarvis_llm_cost_usd` — LLM cost tracker
- `jarvis_orders_total` — Order submission counter
- `jarvis_daily_pnl_usd` — Daily P&L gauge
- `jarvis_equity_usd` — Equity gauge
- `jarvis_kill_switch_active` — Kill switch status (0/1)
- `jarvis_safety_events_total` — Safety layer event counter
- `jarvis_consecutive_losses` — Losing trade streak gauge

### ✅ STEP 4: Grafana Datasource Configuration
**File Created**: `infrastructure/grafana/provisioning/datasources/prometheus.yml`
```yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: true
```

### ✅ STEP 5: Prometheus Service Added to Docker Compose
**File Modified**: `infrastructure/docker-compose.yml`

**Service Added**:
```yaml
prometheus:
  image: prom/prometheus:v2.51.0
  container_name: jarvis_prometheus
  restart: unless-stopped
  ports:
    - "9090:9090"
  volumes:
    - ./prometheus/prometheus.yml:/etc/prometheus/prometheus.yml
    - prometheus_data:/prometheus
```

**Grafana Updated**:
- Added `GF_PATHS_PROVISIONING` environment variable
- Added Grafana provisioning volume mount
- Added Prometheus as dependency

**Volume Added**:
```yaml
prometheus_data:
```

### ✅ STEP 6: Prometheus Configuration
**File Created**: `infrastructure/prometheus/prometheus.yml`

**Scrape Jobs Configured**:
- **jarvis_trader_engine**: Scrapes JARVIS TRADER /metrics on port 8010 every 15s
- **prometheus**: Self-monitoring on localhost:9090

### ✅ STEP 7: Grafana Dashboards Created
Three JSON dashboards auto-provisioned:

#### 1. **System Health Dashboard**
**File**: `infrastructure/grafana/dashboards/system-health.json`
- Request Rate: Stacked bar chart (requests/sec by method/path)
- Latency Percentiles: p95 and p99 latency in seconds
- Error Rate: 4xx and 5xx errors per second
- API Uptime: Gauge showing uptime percentage

#### 2. **Trading Performance Dashboard**
**File**: `infrastructure/grafana/dashboards/trading-performance.json`
- Pipeline Decisions: Stacked bars by symbol and decision type
- Daily P&L: Gauge showing current profit/loss in USD
- Equity Curve: Line chart with min/max/last values
- Orders by Symbol: Stacked bars by symbol, direction, and status
- Kill Switch Status: Active/inactive gauge

#### 3. **LLM Costs & Usage Dashboard**
**File**: `infrastructure/grafana/dashboards/llm-costs.json`
- LLM Calls by Model: Stacked bars by model and agent
- Daily LLM Cost: Gauge showing total daily spend in USD
- Cost Over Time: Line chart bucketed by hour and model
- Pipeline Latency: Scatter plot of p95 execution time in ms
- LLM Success Rate: Line chart by model

**Provisioning Config Created**: `infrastructure/grafana/provisioning/dashboards/provisioning.yml`
- Auto-loads all JSON dashboards on startup
- Enables editing and deletion controls

### Supporting Documentation
**File Created**: `infrastructure/MONITORING.md`

Comprehensive guide including:
- Quick start instructions
- Architecture diagram
- Complete metrics reference
- Code examples for recording metrics
- Dashboard descriptions
- Troubleshooting guide
- Alerting setup (optional)
- Performance tuning

## File Structure

```
jarvis-trader/
├── engine/
│   ├── main.py (MODIFIED)
│   ├── requirements-core.txt (MODIFIED)
│   └── monitoring/
│       ├── __init__.py (NEW)
│       └── metrics.py (NEW)
└── infrastructure/
    ├── docker-compose.yml (MODIFIED)
    ├── MONITORING.md (NEW)
    ├── prometheus/
    │   └── prometheus.yml (NEW)
    └── grafana/
        ├── provisioning/
        │   ├── datasources/
        │   │   └── prometheus.yml (NEW)
        │   └── dashboards/
        │       └── provisioning.yml (NEW)
        └── dashboards/
            ├── system-health.json (NEW)
            ├── trading-performance.json (NEW)
            └── llm-costs.json (NEW)
```

## Integration Points

### Recording Metrics in Trading Pipeline

The monitoring module is ready to be integrated:

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

# In pipeline execution:
record_pipeline_run(symbol="MES", decision="BUY")
record_pipeline_duration(duration=2.5, symbol="MES")

# In agent execution:
record_llm_call(model="claude-3-opus", agent="TechnicalAnalyst", success=True)
record_llm_cost(model="claude-3-opus", cost_usd=0.015)

# In order manager:
record_order(symbol="MES", direction="long", status="filled")

# In portfolio tracker (periodic):
set_daily_pnl(pnl_usd=1250.50)
set_equity(equity_usd=102500.00)

# In safety layer:
set_kill_switch(active=False)
record_safety_event(event_type="margin_violation")
```

## Deployment Checklist

- [ ] `pip install -r engine/requirements-core.txt` (installs prometheus-fastapi-instrumentator)
- [ ] `cd infrastructure && docker compose up -d` (starts Prometheus + Grafana)
- [ ] Verify Prometheus: http://localhost:9090
  - Check Targets: Prometheus → Status → Targets
  - Verify JARVIS TRADER engine target is UP
- [ ] Verify Grafana: http://localhost:3030
  - Login with admin/jarvis_change_me
  - Check Dashboards → JARVIS TRADER Dashboards
  - Verify 3 dashboards are loaded
- [ ] Integrate metric recording into trading pipeline code
- [ ] Start JARVIS TRADER engine: `uvicorn main:app --reload --port 8010`
- [ ] Check API metrics: http://localhost:8010/metrics
- [ ] Monitor live dashboards on http://localhost:3030

## Configuration Notes

### Scrape Interval
- Default: 15 seconds (configured in prometheus.yml)
- Change in `prometheus.yml` under `scrape_interval`
- Affects metric resolution and storage size

### Grafana Admin Password
- Default: `jarvis_change_me`
- Set via `GF_ADMIN_PASSWORD` environment variable in docker-compose.yml
- Change in Grafana UI: Settings → Admin → Change Password

### Prometheus Storage
- Retention: 15 days (Prometheus default)
- Location: `prometheus_data` Docker volume
- Adjust with `--storage.tsdb.retention.time=7d` in command flags

### JARVIS TRADER Hostname
- Docker: `host.docker.internal:8010` (localhost from Docker perspective)
- Change to actual IP if running on remote machine
- Edit `infrastructure/prometheus/prometheus.yml` targets

## Next Steps

1. Install the prometheus-fastapi-instrumentator dependency
2. Start the Docker infrastructure (Prometheus + Grafana)
3. Integrate metric recording into the trading pipeline code
4. Monitor live dashboards in Grafana
5. (Optional) Configure alerting rules for P&L, costs, and errors

All infrastructure is ready for real-time observability of JARVIS TRADER.
