# JARVIS TRADER — LLM Client

Robust, production-grade LLM client with retry logic, token tracking, and cost monitoring.

## Features

- **Async wrapper** around `anthropic.AsyncAnthropic`
- **Retry logic** with exponential backoff (1s → 2s → 4s, max 3 attempts)
- **Retries on**: Rate limits (429), server errors (500, 503), connection errors
- **Token tracking**: Input/output tokens counted per call
- **Cost calculation**: Real-time USD cost per call based on current pricing
- **Daily cost tracking**: SQLite database at `data/llm_costs.db`
- **Model fallback**: Opus → Sonnet → Haiku when overloaded
- **Comprehensive logging**: Model, tokens, latency, cost, retries per call
- **Daily/monthly statistics**: Cost summaries with per-model and per-agent breakdowns

## Architecture

```
JarvisLLMClient (main interface)
├── Wraps anthropic.AsyncAnthropic
├── Manages retry logic with exponential backoff
├── Calculates costs per token
└── Delegates to CostTracker

CostTracker (SQLite backend)
├── Creates & manages llm_calls table
├── Logs each call with metadata
├── Provides daily_summary() and monthly_summary()
└── Indexes by timestamp, model, agent
```

## Cost Model (as of 2026-03-29)

### Input Tokens (per million)
- **Opus**: $15 / MTok
- **Sonnet**: $3 / MTok
- **Haiku**: $0.80 / MTok

### Output Tokens (per million)
- **Opus**: $75 / MTok
- **Sonnet**: $15 / MTok
- **Haiku**: $4 / MTok

## Usage

### Basic Usage

```python
from llm import JarvisLLMClient

# Initialize
client = JarvisLLMClient(
    api_key="sk-ant-...",
    db_path="data/llm_costs.db"
)

# Make a call with retry logic and tracking
result = await client.call(
    model="claude-opus-4-7",
    system="You are a technical analyst.",
    messages=[
        {"role": "user", "content": "Analyze SPY's technical setup."}
    ],
    max_tokens=1024,
    agent_name="technical_analyst"
)

# Check result
if result.success:
    print(f"Response: {result.content}")
    print(f"Cost: ${result.cost_usd:.4f}")
    print(f"Latency: {result.latency_ms}ms")
    print(f"Retries: {result.retries}")
else:
    print(f"Error: {result.error}")
```

### Getting Statistics

```python
# Daily statistics
daily = await client.get_daily_stats()
print(daily)
# Output:
# {
#   "date": "2026-03-29",
#   "total_calls": 42,
#   "total_cost_usd": 12.34,
#   "success_rate": 0.976,
#   "avg_latency_ms": 1250,
#   "per_model": {...},
#   "per_agent": {...}
# }

# Monthly statistics with daily breakdown
monthly = await client.get_monthly_stats()
for day in monthly["daily_breakdown"]:
    print(f"{day['date']}: {day['calls']} calls, ${day['cost_usd']:.2f}")
```

### Via FastAPI Endpoint

```bash
# Get daily stats
curl -X GET http://localhost:8010/llm/stats \
  -H "X-API-Key: jarvis-dev-key-change-me"

# Get monthly stats
curl -X GET http://localhost:8010/llm/stats/monthly \
  -H "X-API-Key: jarvis-dev-key-change-me"
```

## Database Schema

### `llm_calls` Table

```sql
CREATE TABLE llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,                -- ISO 8601 UTC timestamp
    model TEXT NOT NULL,                    -- e.g. "claude-opus-4-7"
    input_tokens INTEGER DEFAULT 0,         -- Input token count
    output_tokens INTEGER DEFAULT 0,        -- Output token count
    cost_usd REAL DEFAULT 0.0,              -- Cost in USD
    latency_ms INTEGER DEFAULT 0,           -- Latency in milliseconds
    agent_name TEXT DEFAULT 'unknown',      -- Calling agent name
    success BOOLEAN DEFAULT 1               -- True if successful
);

-- Indexes for fast queries
CREATE INDEX idx_timestamp ON llm_calls(timestamp);
CREATE INDEX idx_model ON llm_calls(model);
CREATE INDEX idx_agent ON llm_calls(agent_name);
```

## Retry Strategy

The client implements **exponential backoff** with a **maximum of 3 attempts**:

1. **First failure**: Wait 1 second, retry
2. **Second failure**: Wait 2 seconds, retry
3. **Third failure**: Wait 4 seconds, fail (attempt 3)

### Retryable Errors

- `RateLimitError` (429) — API rate limit exceeded
- `APIConnectionError` — Network connection issues
- `APIStatusError` (500, 503) — Server errors

### Fallback Mechanism

If a model is consistently overloaded (max retries exhausted), the client attempts fallback:

1. Try **Opus** (best quality)
2. If Opus fails → Try **Sonnet** (balanced)
3. If Sonnet fails → Try **Haiku** (fastest/cheapest)
4. If Haiku fails → Return error

## Integration with JARVIS TRADER

### Initialization (in `main.py`)

```python
from llm import JarvisLLMClient

# In lifespan startup
_llm_client = JarvisLLMClient(
    api_key=settings.ANTHROPIC_API_KEY,
    db_path="data/llm_costs.db"
)
llm_client = _llm_client

# All agents receive the same client
technical_analyst = TechnicalAnalystAgent(llm_client, data_manager)
trader_agent = TraderAgent(llm_client)
# ... etc
```

### Agent Integration

Agents call the client like this:

```python
class TechnicalAnalystAgent:
    def __init__(self, llm_client):
        self._llm = llm_client

    async def analyze(self, symbol: str):
        result = await self._llm.call(
            model="claude-sonnet-4-6",
            system=self.SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
            agent_name="technical_analyst"
        )

        if not result.success:
            logger.error(f"LLM call failed: {result.error}")
            return None

        return json.loads(result.content)
```

## Logging

Every LLM call produces a log entry:

```
[2026-03-29 14:23:45] INFO [claude-opus-4-7] technical_analyst | in:512 out:341 | cost:$0.0284 | latency:1250ms | retries:0
[2026-03-29 14:24:12] WARNING [claude-opus-4-7] Rate limit (429) for news_analyst — attempt 1/3
[2026-03-29 14:24:13] WARNING [claude-opus-4-7] Rate limit (429) for news_analyst — attempt 2/3
[2026-03-29 14:24:15] WARNING [claude-opus-4-7] Rate limit (429) for news_analyst — attempt 3/3
[2026-03-29 14:24:15] WARNING [claude-opus-4-7] Max retries exhausted. Falling back to claude-sonnet-4-6 for news_analyst
[2026-03-29 14:24:15] INFO [claude-sonnet-4-6] news_analyst | in:512 out:280 | cost:$0.0081 | latency:800ms | retries:0
```

## Error Handling

### Common Scenarios

#### Rate Limit Exceeded
```python
result = await client.call(...)
if not result.success and "429" in result.error:
    # Already retried 3x with backoff; model is genuinely saturated
    # Consider implementing a circuit breaker or backing off further
```

#### Connection Timeout
```python
if not result.success and "connection" in result.error.lower():
    # Network issue; likely temporary
    # Safe to retry immediately without backoff
```

#### Model Fallback
```python
result = await client.call(
    model="claude-opus-4-7",
    allow_fallback=True  # Default; allows Opus → Sonnet → Haiku
)
# If Opus fails, client automatically tries Sonnet
# Check result.model to see which was actually used
print(f"Call was fulfilled by: {result.model}")
```

## Performance Considerations

### Token Costs (Relative to Opus)
- **Opus**: Baseline (2.5x more expensive than Sonnet, 18x more expensive than Haiku)
- **Sonnet**: ~2.5x cheaper than Opus, ~7x cheaper than Haiku (recommended for most agents)
- **Haiku**: ~18x cheaper than Opus (best for fast, low-stakes operations)

### Latency (Typical)
- **Opus**: 1200–2000ms (most capable, slowest)
- **Sonnet**: 800–1200ms (balanced)
- **Haiku**: 400–700ms (fastest)

## Monitoring

Check daily/monthly dashboards via the FastAPI endpoints:

```bash
# Today's stats
curl http://localhost:8010/llm/stats?X-API-Key=...

# This month's breakdown by day
curl http://localhost:8010/llm/stats/monthly?X-API-Key=...
```

## Testing

Run the test suite:

```bash
pytest tests/test_llm_client.py -v
```

Tests cover:
- Cost calculation accuracy
- SQLite tracking and queries
- Daily/monthly summaries
- Fallback chain mapping
- Result structure validation

## Future Enhancements

- [ ] Batch API support for off-peak tasks
- [ ] Circuit breaker pattern for consistent failures
- [ ] Caching of identical requests
- [ ] Per-agent cost budgets and alerts
- [ ] Integration with Prometheus metrics
- [ ] Streaming responses for long outputs
