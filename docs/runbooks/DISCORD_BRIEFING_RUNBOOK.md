# Discord briefing endpoint — runbook (2026-05-20)

**Purpose:** Operating reference for `GET /discord/briefing`, the composed
pre-session intelligence facade. Use this when writing Hermes prompts, dashboard
widgets, or any agent that needs a single-call "what does Discord say about
symbol X right now?" view.

---

## Why this route exists

Four separate Discord consumer modules exist (`commentary_processor`,
`ib_levels`, `sentiment_provider`, `signal_context`), each with its own cache
and its own response shape. Any agent that wants the full picture currently has
to wire all four manually — and coordinate their latencies.

`/discord/briefing` unifies them into a single awaitable call with a 5-minute
TTL cache at the facade layer. It is intentionally **higher-level and more
human-readable** than `/discord/intelligence`:

| Surface | Audience | Shape | Staleness |
|---------|----------|-------|-----------|
| `/discord/briefing` | Pre-session prep, Hermes morning calls, agent context injection | Structured `DiscordBriefing` dataclass; includes `headline` string and `actionable` bool | 5-min TTL |
| `/discord/intelligence` | Dashboard widget, RL state vector, live-feed consumers | `DiscordSignalContext` feature vector (numeric) | Per-request with its own caching |
| `/discord/signals`, `/discord/ib-reports` | Raw data, historical analysis | Paginated DB rows | Live (no cache) |

---

## API contract

```
GET /discord/briefing
Host: 127.0.0.1:8010
X-API-Key: <value from engine/.env>
```

### Query parameters

| Parameter | Type | Default | Constraints | Description |
|-----------|------|---------|-------------|-------------|
| `symbol` | string | **required** | — | JARVIS or Discord symbol. Accepts both micro (`MCL`) and full (`CL`). Normalized to uppercase internally. |
| `lookback_hours` | int | `24` | 1–168 | Window for the `recent_signal` probe against `discord_bot_signals`. |
| `for_date` | string | today (UTC) | `YYYY-MM-DD` | Trading date to brief on. Useful for backtests. Omit for live sessions. |

Source: `engine/routers/discord_router.py` lines 541–573.

### Response shape

HTTP 200 — JSON object (`DiscordBriefing.to_dict()`, defined at `engine/discord/briefing.py` lines 91–105):

```json
{
  "symbol": "MCL",
  "discord_symbol": "CL",
  "as_of": "2026-05-20T13:42:00.000000",
  "headline": "MCL range_day, neutral, inside_ib, conv 0.30",
  "actionable": false,
  "corey_bias": {
    "session_type": "range_day",
    "directional_bias": "neutral",
    "ib_bias": "inside_ib",
    "conviction": 0.30,
    "key_levels": [],
    "specific_triggers": [],
    "data_quality": "fresh",
    "corey_quote": "...",
    "date": "2026-05-20"
  },
  "ib_levels": {
    "ib_high": 77.45,
    "ib_low": 76.80,
    "ibu50": 77.85,
    "ibu100": 78.10,
    "ibd50": 76.40,
    "ibd100": 76.15,
    "auction_context": "balanced"
  },
  "keyword_sentiment": 0.12,
  "regime_multiplier": 1.05,
  "recent_signal": {
    "symbol": "CL",
    "direction": "LONG",
    "signal_type": "ENTRY",
    "entry_price": 77.10,
    "target1": 77.45,
    "target2": 77.80,
    "stop1": 76.85,
    "win_rate": 0.62,
    "timestamp": "2026-05-20T10:15:00"
  },
  "lookback_hours": 24,
  "warnings": []
}
```

**Key fields:**

| Field | Meaning |
|-------|---------|
| `headline` | One-liner computed as `"{symbol} {session_type}, {directional_bias}, {ib_bias}, conv {conviction:.2f}"` (line 75–79) |
| `actionable` | `true` iff `data_quality == "fresh"` AND `directional_bias != "neutral"` AND `conviction >= 0.5` (lines 83–89) |
| `ib_levels` | `null` when no IB report has been posted for `for_date` |
| `recent_signal` | `null` when no `discord_bot_signals` row falls within `lookback_hours` |
| `warnings` | Non-empty list describes which of the 4 sub-calls degraded gracefully (e.g. `"corey_bias_failed:TimeoutError"`) |

### Error responses

| Status | Meaning |
|--------|---------|
| 422 | `for_date` is not a valid `YYYY-MM-DD` string |
| 500 | Unhandled exception in the facade — inspect `pm2 logs jarvis-engine --lines 50` |

Note: the facade itself **never raises for missing data** (briefing.py line 174).
A 200 with `ib_levels: null` or `recent_signal: null` is normal when Discord
hasn't posted those items yet. A non-empty `warnings` array means one input
degraded to its neutral default.

---

## The 4 composed inputs

All source detail is in `engine/discord/briefing.py` lines 188–219.

### 1. Corey session bias (lines 188–195)

**Provider:** `discord.commentary_processor.CoreyCommentaryProcessor`
**Underlying table:** `discord_corey_commentary` (66K+ rows) + `discord_analyses` (LLM cache)
**Method:** `get_session_bias(for_date)` — async, LLM-extracted from the raw commentary corpus for `for_date`
**Degraded default:** `_neutral_bias(for_date, message_count=0)` — all fields neutral/zero, `data_quality="stale"`, warning appended

**Policy note** (briefing.py lines 29–32): Corey `#market-updates` is the ONLY
trusted futures sentiment source per owner directive 2026-04-19. Reddit, Twitter,
and news are explicitly excluded. `corey_bias.directional_bias` and `ib_levels`
are authoritative; `keyword_sentiment` is a weaker auxiliary signal.

### 2. IB levels (lines 197–205)

**Provider:** `discord.ib_levels.IBLevelProvider`
**Underlying table:** `discord_ib_reports` (1,000 rows)
**Method:** `get_levels(symbol, for_date)` — sync, date-indexed, Discord-symbol keyed
**Symbol mapping:** `ib_provider._map_symbol(symbol)` translates `MCL→CL`, `MES→ES`, etc. (line 199)
**Degraded default:** `None`

### 3. Keyword sentiment + regime multiplier (lines 207–216)

**Provider:** `discord.sentiment_provider.SentimentProvider`
**Underlying table:** `discord_daily_sentiment` (pre-aggregated)
**Methods:** `get_sentiment(for_date)` returns `-1.0..+1.0`; `get_regime_multiplier(for_date)` returns `0.7..1.3`
**Degraded default:** `keyword_sentiment=0.0`, `regime_multiplier=1.0`

### 4. Most-recent bot signal (lines 218–219, helper lines 237–267)

**Source:** `discord_bot_signals` table (221K+ rows), raw SQL — bypasses `get_features()` which requires ATR/price context unavailable at briefing time
**Query:** `SELECT … FROM discord_bot_signals WHERE symbol = ? AND timestamp >= ? ORDER BY timestamp DESC LIMIT 1` (lines 248–258)
**Symbol key:** `discord_symbol` (the mapped value, e.g. `CL` not `MCL`)
**Degraded default:** `None`

---

## Cache behavior

Defined at `engine/discord/briefing.py` lines 51 and 117–118:

```python
CACHE_TTL_SECONDS = 300  # 5-minute TTL
_cache: dict[tuple[str, str, int], tuple[DiscordBriefing, float]] = {}
```

**Cache key:** `(symbol.upper(), for_date.isoformat(), lookback_hours)` — so
`MCL + 2026-05-20 + 24` and `MCL + 2026-05-20 + 4` are distinct cache entries.

**Expiry check:** monotonic clock comparison (line 183). The cache is module-level
and survives across requests within the same engine process — it does NOT bust on
engine restart unless `clear_cache()` is called explicitly.

**Force-refresh:** there is no `?refresh=true` query param on this route. To
force a fresh fetch: restart the engine (`.\restart_engine.ps1`) or call
`discord.briefing.clear_cache()` from within the process.

**Note:** the underlying providers maintain their own caches too. The briefing
layer adds one more TTL on top to avoid coordination cost when the same briefing
is requested multiple times per bar (e.g. debate + trader + fundamental_analyst
all calling within one 5-minute window).

---

## Smoke test

Replace `<YOUR_API_KEY>` with the value from `engine/.env`.

```powershell
$h = @{ "X-API-Key" = "<YOUR_API_KEY>" }

# MCL briefing — today, 24h lookback
Invoke-RestMethod "http://127.0.0.1:8010/discord/briefing?symbol=MCL" -Headers $h |
    ConvertTo-Json -Depth 5

# MES briefing — last 4h signals only
Invoke-RestMethod "http://127.0.0.1:8010/discord/briefing?symbol=MES&lookback_hours=4" -Headers $h |
    Select-Object headline, actionable, keyword_sentiment, warnings

# Historical date (backtest use)
Invoke-RestMethod "http://127.0.0.1:8010/discord/briefing?symbol=MCL&for_date=2026-05-19" -Headers $h |
    Select-Object headline, actionable
```

**Healthy response indicators:**
- HTTP 200
- `actionable` is a bool (not null)
- `warnings` is an empty array (or explains a degraded sub-source)
- `as_of` is within the last 5 minutes (or within 5 min of cached fetch)

---

## When to use briefing vs other routes

| Use case | Recommended route |
|----------|-------------------|
| Pre-session Hermes prompt / morning briefing | `/discord/briefing?symbol=MCL` |
| Agent context injection (debate, fundamental, trader agents) | `/discord/briefing` |
| Dashboard live widget (numeric feature vector) | `/discord/intelligence` |
| RL state vector construction | `/discord/intelligence` |
| Historical signal scan / strategy research | `/discord/signals` + `/discord/ib-reports` |
| Corey quote for a specific date | `mcp__discord-jarvis__get_session_bias` |
| Real-time messages not yet ingested | `mcp__discord-personal__list_recent_messages` |

---

## Troubleshooting

**200 with `ib_levels: null`**
No IB report posted for `for_date` in `discord_ib_reports`. Normal before IB levels are announced (~9:30am CT). Check with:
```powershell
Invoke-RestMethod "http://127.0.0.1:8010/discord/ib-reports?limit=1" -Headers $h
```

**200 with `recent_signal: null`**
No `discord_bot_signals` row for the mapped Discord symbol within `lookback_hours`. Widen the window (`&lookback_hours=72`) or check signal ingestion health.

**200 with non-empty `warnings`**
One or more sub-providers degraded. The warning string is `"<source>_failed:<ExceptionType>"`. Check `pm2 logs jarvis-engine --lines 100` for the root cause. The briefing returns neutral defaults — it is still usable.

**500**
Unhandled exception in the facade (not in a sub-provider). Inspect logs. Likely a schema change in one of the underlying modules or an import failure.

**422 on `for_date`**
Date string is not `YYYY-MM-DD`. Correct the format.

**Stale data (headline looks days old)**
The 5-minute cache is process-level. If `as_of` is stale, the engine process itself may be long-lived with an old cache entry — restart with `.\restart_engine.ps1`.

---

## Cron recipes for Hermes

These assume Hermes calls the engine via HTTP at `http://127.0.0.1:8010`.

### Pre-market briefing — 7:00am CT

```yaml
# In Hermes config or a scheduled Hermes prompt
schedule: "0 7 * * 1-5"
timezone: "America/Chicago"
prompt: |
  Fetch the Discord briefing for MCL and MES:
    GET /discord/briefing?symbol=MCL
    GET /discord/briefing?symbol=MES&lookback_hours=4
  Summarize: session type, directional bias, IB levels if present,
  recent signal if present. Flag if actionable=true.
```

### Mid-day reset — 12:00pm CT

```yaml
schedule: "0 12 * * 1-5"
timezone: "America/Chicago"
prompt: |
  Refresh the Discord briefing for active instruments (MCL, MES).
  Note any change in session_type or directional_bias vs the 7am run.
  Highlight if a new bot signal arrived in the last 4 hours.
```

Note: the engine-side 5-minute cache will serve these calls from SQLite-fresh
data when Hermes fires, since 7am and noon are well outside any prior cache window.

---

## Related runbooks

- `[[DISCORD_INTEL_RUNBOOK]]` — full Discord intelligence layer: MCP servers, all 7 HTTP routes, ingest task, 6 SQLite tables, smoke tests
- `[[HEALTH_API_CONTRACT]]` — `/health` and `/safety/*` stable key contracts
- `[[CLAUDE_CODE_AND_HERMES_INTEGRATION_MAP]]` — Hermes gateway, MCP wiring, session coordination
