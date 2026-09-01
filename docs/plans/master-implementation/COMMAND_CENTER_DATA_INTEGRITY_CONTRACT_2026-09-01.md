# Command Center Data Integrity Contract

## Current Endpoint

`GET /system/data-integrity` currently returns a Redis last-update view:

```json
{
  "timestamp": "2026-09-01T00:00:00+00:00",
  "sources": [
    {
      "source": "ticks:MES1!",
      "last_update": "2026-09-01T00:00:00+00:00",
      "latency_sec": 60.0,
      "status": "healthy"
    }
  ],
  "count": 1
}
```

The existing fresh/stale boundary is `900` seconds via `DATA_INTEGRITY_STALE_AFTER_S`.

## Required Expanded Response

`/system/data-integrity` must remain backward-compatible with the current `timestamp`, `sources`, and `count` fields, then add these fields before the Command Center may render stronger claims than `unknown` or `not_wired`.

```json
{
  "timestamp": "2026-09-01T00:00:00+00:00",
  "status": "ok",
  "stale_after_seconds": 900,
  "sources": [
    {
      "source": "ticks:MES1!",
      "kind": "market_data",
      "provider": "ibkr",
      "provider_tier": "primary",
      "last_update": "2026-09-01T00:00:00+00:00",
      "latency_sec": 60.0,
      "age_seconds": 60.0,
      "status": "healthy",
      "cache_key": "datasource:ticks:MES1!:last_update"
    }
  ],
  "count": 1,
  "cache_age": {
    "status": "fresh",
    "max_age_seconds": 60.0,
    "stale_after_seconds": 900,
    "by_source": [
      {
        "source": "ticks:MES1!",
        "age_seconds": 60.0,
        "status": "fresh"
      }
    ]
  },
  "provider_tier": {
    "status": "known",
    "active": "ibkr",
    "primary": "ibkr",
    "fallbacks": ["yfinance", "cached"],
    "reason": null
  },
  "bar_freshness": {
    "status": "fresh",
    "stale_after_seconds": 900,
    "max_lag_seconds": 60.0,
    "symbols": ["MES1!"],
    "timeframes": ["1m", "5m"],
    "stale_symbols": [],
    "unknown_symbols": []
  },
  "source_parity": {
    "status": "matched",
    "window_seconds": 300,
    "checked_symbols": ["MES1!"],
    "reference_source": "ibkr",
    "compared_sources": ["cached"],
    "max_delta_bps": 0.0,
    "mismatches": [],
    "missing_sources": []
  },
  "trade_enablement": {
    "status": "allowed",
    "blocking_reasons": []
  }
}
```

## Status Values

- Top-level `status`: `ok`, `degraded`, `offline`, or `unknown`.
- Source `status`: keep existing `healthy` and `stale`; add `unknown` only when the engine cannot determine freshness.
- `cache_age.status`: `fresh`, `stale`, `empty`, or `unknown`.
- `provider_tier.status`: `known`, `fallback`, `offline`, or `unknown`.
- `bar_freshness.status`: `fresh`, `stale`, `partial`, `empty`, or `unknown`.
- `source_parity.status`: `matched`, `mismatch`, `missing`, or `not_wired`.
- `trade_enablement.status`: `allowed`, `blocked`, or `unknown`.

## UI Claim Rules

- Cache freshness can render `fresh` or `stale` only when `cache_age.status` is present.
- Provider status can render a provider and tier only when `provider_tier.status` is present.
- Bar freshness can render `fresh`, `stale`, or `partial` only when `bar_freshness.status` is present.
- Source parity must render `not wired` until `source_parity.status` is present.
- Trade enablement must render blocked if any of `cache_age`, `provider_tier`, `bar_freshness`, or `source_parity` reports stale, offline, mismatch, missing, or unknown and the engine includes that state in `trade_enablement.blocking_reasons`.

## Implementation Notes

- Preserve the current `sources[].latency_sec` field so `/data-integrity` remains compatible.
- Treat `sources[].age_seconds` as the canonical field for new consumers; set it equal to `latency_sec` during migration.
- Do not infer provider tier from the source name in the dashboard. Provider/tier must come from the engine response.
- Do not infer source parity from a non-empty `sources[]` array. Parity requires a configured comparison window and at least one comparison result.
- Use the same `DATA_INTEGRITY_STALE_AFTER_S` constant for source, cache, and bar-freshness staleness unless a future contract names a narrower per-source threshold.

## P8-008 Test Targets

- `/system/data-integrity` includes all expanded fields in the healthy Redis case.
- stale Redis input sets `cache_age.status` and `bar_freshness.status` to `stale`.
- missing Redis keys keep `count: 0` and set unknown/empty states without returning a green status.
- dashboard Command Center derivation keeps existing unknown/not-wired fallbacks when the expanded fields are absent.
