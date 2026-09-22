# LLM Client Integration Guide

## Overview

JARVIS TRADER now has a **robust, production-grade LLM client** (`JarvisLLMClient`) that replaces the previous basic `SimpleLLMClient`. The new client provides:

1. **Automatic retry logic** with exponential backoff (1s → 2s → 4s)
2. **Token tracking** for every API call
3. **Real-time cost calculation** based on current Anthropic pricing
4. **SQLite cost database** at `data/llm_costs.db`
5. **Model fallback** (Opus → Sonnet → Haiku if overloaded)
6. **Comprehensive logging** of all calls with metrics
7. **HTTP endpoints** for daily and monthly statistics

## Quick Start

### 1. Requirements

The client requires **tenacity** for retry logic. This has been added to `requirements-core.txt`:

```bash
pip install tenacity==9.0.0
```

Or reinstall all dependencies:

```bash
pip install -r requirements-core.txt
```

### 2. Automatic Initialization

The client is **automatically initialized** in `main.py` during startup:

```python
# In lifespan() startup
from llm import JarvisLLMClient

_llm_client = JarvisLLMClient(
    api_key=[REDACTED]
    db_path="data/llm_costs.db"
)
```

All agents receive the same client instance, so token tracking is centralized.

### 3. API Endpoints

Two new endpoints are now available for monitoring:

#### Get Daily Statistics
```bash
curl -X GET http://localhost:8010/llm/stats \
  -H "X-API-Key: [REDACTED]"
```

Response:
```json
{
  "date": "2026-03-29",
  "total_calls": 42,
  "total_cost_usd": 12.34,
  "success_rate": 0.976,
  "avg_latency_ms": 1250,
  "per_model": {
    "claude-opus-4-7": {
      "calls": 20,
      "input_tokens": 45000,
      "output_tokens": 12000,
      "cost_usd": 9.50
    },
    "claude-sonnet-4-6": {
      "calls": 22,
      "input_tokens": 32000,
      "output_tokens": 8000,
      "cost_usd": 2.84
    }
  },
  "per_agent": {
    "technical_analyst": {"calls": 10, "cost_usd": 2.10},
    "trader": {"calls": 8, "cost_usd": 5.20},
    "news_analyst": {"calls": 12, "cost_usd": 2.04},
    "risk_manager": {"calls": 12, "cost_usd": 3.00}
  }
}
```

#### Get Monthly Statistics
```bash
curl -X GET http://localhost:8010/llm/stats/monthly \
  -H "X-API-Key: [REDACTED]"
```

Response:
```json
{
  "year_month": "2026-03",
  "total_calls": 1250,
  "total_cost_usd": 385.47,
  "daily_breakdown": [
    {"date": "2026-03-01", "calls": 42, "cost_usd": 12.34},
    {"date": "2026-03-02", "calls": 45, "cost_usd": 13.20},
    ...
  ],
  "per_model": {
    "claude-opus-4-7": {"calls": 600, "cost_usd": 285.00},
    "claude-sonnet-4-6": {"calls": 650, "cost_usd": 100.47}
  }
}
```

## Architecture

### File Structure

```
engine/llm/
├── __init__.py                # Package exports
├── client.py                  # JarvisLLMClient (main class)
├── cost_tracker.py            # CostTracker (SQLite backend)
└── README.md                  # Detailed documentation
```

### Class: JarvisLLMClient

**Location**: `engine/llm/client.py`

**Key Methods**:
- `call()` — Make an LLM API call with retry logic and tracking
- `get_daily_stats()` — Get daily cost summary
- `get_monthly_stats()` — Get monthly cost summary with daily breakdown
- `close()` — Cleanup (called on shutdown)

**Features**:
- Wraps `anthropic.AsyncAnthropic`
- Async/await throughout
- Exponential backoff: 1s → 2s → 4s (max 3 attempts)
- Retries on: 429 (rate limit), 500, 503, connection errors
- Model fallback: Opus → Sonnet → Haiku
- Detailed logging per call

### Class: CostTracker

**Location**: `engine/llm/cost_tracker.py`

**Key Methods**:
- `log_call()` — Log a single API call to SQLite
- `get_daily_summary()` — Get daily stats (cost, calls, per-model breakdown)
- `get_monthly_summary()` — Get monthly stats with daily breakdown
- `close()` — Cleanup

**Database**:
- Path: `data/llm_costs.db`
- Table: `llm_calls` with 9 columns (see schema below)
- Indexes on: timestamp, model, agent_name

## Usage in Agents

All agents receive the same `JarvisLLMClient` instance. They call it like this:

```python
class TechnicalAnalystAgent:
    def __init__(self, llm_client):
        self._llm = llm_client

    async def analyze(self, symbol: str) -> TechnicalReport:
        prompt = f"Analyze {symbol}'s technical setup..."

        result = await self._llm.call(
            model="claude-sonnet-4-6",
            system=self.SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
            agent_name="technical_analyst",  # Logged for tracking
        )

        if not result.success:
            logger.error(f"LLM call failed: {result.error}")
            return None

        # result.content has the response
        # result.cost_usd has the USD cost
        # result.latency_ms has the latency
        # result.retries has retry count
        return self._parse_response(result.content)
```

## Cost Model

### Pricing (as of 2026-03-29)

| Model | Input (per MTok) | Output (per MTok) |
|-------|------------------|-------------------|
| Opus | $15 | $75 |
| Sonnet | $3 | $15 |
| Haiku | $0.80 | $4 |

### Cost Calculation Example

```python
# Opus call with 512 input tokens, 341 output tokens
input_cost = (512 / 1_000_000) * 15 = $0.00768
output_cost = (341 / 1_000_000) * 75 = $0.02558
total = $0.03326
```

## Database Schema

### `llm_calls` Table

```sql
CREATE TABLE llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,                -- ISO 8601 UTC, e.g. "2026-03-29T14:23:45.123456+00:00"
    model TEXT NOT NULL,                    -- e.g. "claude-opus-4-7", "claude-sonnet-4-6"
    input_tokens INTEGER DEFAULT 0,         -- Input token count
    output_tokens INTEGER DEFAULT 0,        -- Output token count
    cost_usd REAL DEFAULT 0.0,              -- Cost in USD (calculated per call)
    latency_ms INTEGER DEFAULT 0,           -- Latency in milliseconds
    agent_name TEXT DEFAULT 'unknown',      -- Calling agent name (for tracking)
    success BOOLEAN DEFAULT 1               -- True if successful, False if failed
);
```

### Indexes

- `idx_timestamp` on `timestamp` (for range queries in daily/monthly summaries)
- `idx_model` on `model` (for per-model cost breakdowns)
- `idx_agent` on `agent_name` (for per-agent cost breakdowns)

### Example Query

```sql
-- Find all failed calls in the last day
SELECT * FROM llm_calls
WHERE success = 0
AND timestamp >= datetime('now', '-1 day');

-- Cost per agent today
SELECT agent_name, COUNT(*), SUM(cost_usd)
FROM llm_calls
WHERE DATE(timestamp) = DATE('now')
GROUP BY agent_name
ORDER BY SUM(cost_usd) DESC;

-- Opus usage breakdown this month
SELECT
    DATE(timestamp) as date,
    COUNT(*) as calls,
    SUM(input_tokens) as input_total,
    SUM(output_tokens) as output_total,
    SUM(cost_usd) as cost_daily
FROM llm_calls
WHERE model = 'claude-opus-4-7'
AND strftime('%Y-%m', timestamp) = strftime('%Y-%m', 'now')
GROUP BY DATE(timestamp);
```

## Logging

### Console Output

Every LLM call produces a log entry:

```
[2026-03-29 14:23:45,123] INFO [claude-opus-4-7] technical_analyst | in:512 out:341 | cost:$0.0333 | latency:1250ms | retries:0
```

Format:
```
[{timestamp}] {level} [{model}] {agent_name} | in:{input_tokens} out:{output_tokens} | cost:${cost} | latency:{latency}ms | retries:{retry_count}
```

### Retry Logging

When retries occur:

```
[2026-03-29 14:24:12,456] WARNING [claude-opus-4-7] Rate limit (429) for news_analyst — attempt 1/3
[2026-03-29 14:24:13,789] WARNING [claude-opus-4-7] Rate limit (429) for news_analyst — attempt 2/3
[2026-03-29 14:24:15,012] WARNING [claude-opus-4-7] Rate limit (429) for news_analyst — attempt 3/3
[2026-03-29 14:24:15,345] WARNING [claude-opus-4-7] Max retries exhausted. Falling back to claude-sonnet-4-6 for news_analyst
[2026-03-29 14:24:15,678] INFO [claude-sonnet-4-6] news_analyst | in:512 out:280 | cost:$0.0081 | latency:800ms | retries:0
```

## Retry Strategy

### Exponential Backoff

The client retries up to 3 times with exponential backoff:

1. **Attempt 1**: Fails → Wait 1 second → Retry
2. **Attempt 2**: Fails → Wait 2 seconds → Retry
3. **Attempt 3**: Fails → Wait 4 seconds → Give up or fallback

### Retryable Errors

- `RateLimitError` (429) — Rate limit exceeded; wait and retry
- `APIConnectionError` — Network issues; wait and retry
- `APIStatusError` with status 500, 503 — Server errors; wait and retry

### Non-Retryable Errors

- `APIStatusError` with status 400, 401, 403, 404 — Input/auth issues; fail immediately
- JSON parse errors — Fail immediately
- Unknown model — Fail immediately

## Model Fallback

If the primary model is overloaded (max retries exhausted), the client automatically falls back:

1. Request model **Opus**
2. If Opus fails → Try **Sonnet**
3. If Sonnet fails → Try **Haiku**
4. If Haiku fails → Return error (no more fallbacks)

Example log:
```
[...] WARNING [claude-opus-4-7] Max retries exhausted. Falling back to claude-sonnet-4-6 for trader
[...] INFO [claude-sonnet-4-6] trader | in:1024 out:512 | cost:$0.0072 | latency:950ms | retries:0
```

Check which model was used:
```python
result = await client.call(model="claude-opus-4-7", ...)
print(f"Actually used: {result.model}")  # May be Sonnet or Haiku if Opus failed
```

## Monitoring Dashboard

### Real-time Checks

```bash
# Is the LLM system working?
curl http://localhost:8010/llm/stats -H "X-API-Key: ..." | jq .success_rate

# How much have we spent today?
curl http://localhost:8010/llm/stats -H "X-API-Key: ..." | jq .total_cost_usd

# Which agent is most expensive?
curl http://localhost:8010/llm/stats -H "X-API-Key: ..." | jq '.per_agent | to_entries | max_by(.value.cost_usd)'
```

### Alert Thresholds (Recommended)

Consider adding alerts for:

| Metric | Threshold | Action |
|--------|-----------|--------|
| Daily cost | > $100 | Investigate usage patterns |
| Success rate | < 90% | Check API connectivity |
| Avg latency | > 2000ms | Consider faster models |
| Rate limit retries | > 5/day | Reduce request frequency |

## Testing

Run the test suite:

```bash
cd engine
pytest tests/test_llm_client.py -v
```

Tests cover:
- Cost calculation accuracy for all models
- SQLite logging and queries
- Daily/monthly summary generation
- Result structure validation
- Fallback chain mapping

## Troubleshooting

### High Costs

**Problem**: LLM costs are higher than expected.

**Solutions**:
1. Check which model is being used most: `curl http://localhost:8010/llm/stats | jq .per_model`
2. Consider using Sonnet or Haiku instead of Opus for non-critical agents
3. Reduce max_tokens if outputs are shorter than needed
4. Batch similar requests to reduce API calls

### Rate Limit Errors

**Problem**: Frequent 429 (rate limit) errors.

**Solutions**:
1. This is normal — the client retries automatically with backoff
2. Check success_rate endpoint: `curl http://localhost:8010/llm/stats | jq .success_rate`
3. If success_rate < 0.95, reduce request frequency
4. Consider increasing max_tokens_per_minute or using a queue

### Model Fallback

**Problem**: Seeing unexpected models in logs.

**Expected**: If Opus is overloaded, the client automatically tries Sonnet or Haiku. This is normal behavior.

**Check**: `curl http://localhost:8010/llm/stats | jq .per_model` to see which models actually fulfilled requests.

### Database Issues

**Problem**: Getting "SQLite locked" errors.

**Solutions**:
1. Multiple processes writing to the same DB — not typical with single FastAPI instance
2. Check if another process is holding the lock: `lsof | grep llm_costs.db`
3. Delete and reinitialize if corrupted: `rm data/llm_costs.db` (data is lost, but system recovers)

## Performance Tips

### For Cost Optimization

1. **Use Sonnet as default** — 2.5x cheaper than Opus, nearly as capable for most tasks
2. **Use Haiku for fast operations** — Token classification, embeddings, simple analysis
3. **Use Opus only for complex reasoning** — Trader agent decision-making, debate orchestration
4. **Reduce max_tokens if possible** — Fewer output tokens = lower cost

### For Speed Optimization

1. **Haiku is fastest** (400–700ms typical latency)
2. **Sonnet is balanced** (800–1200ms)
3. **Opus is slowest** (1200–2000ms) but most capable

### Example Configuration

```python
# For each agent
AGENT_MODEL = {
    "technical_analyst": "claude-sonnet-4-6",   # Balanced
    "news_analyst": "claude-sonnet-4-6",        # Balanced
    "trader": "claude-opus-4-7",                # Complex reasoning
    "risk_manager": "claude-opus-4-7",          # Critical decisions
    "fund_manager": "claude-sonnet-4-6",        # Balanced
}
```

## Summary

The new LLM client provides **production-grade reliability, cost tracking, and observability** for JARVIS TRADER. All API calls are automatically retried, tracked, and logged with full cost metrics.

Key improvements over `SimpleLLMClient`:
- ✅ Retry logic with exponential backoff
- ✅ Token and cost tracking
- ✅ Model fallback when overloaded
- ✅ Comprehensive logging and statistics
- ✅ HTTP endpoints for monitoring
- ✅ SQLite persistence for audit trail

Start the server and check `/llm/stats` endpoint to monitor LLM usage and costs in real-time.
