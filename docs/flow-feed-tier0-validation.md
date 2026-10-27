# Flow Feed Monitoring Stack - Tier 0 Validation

**Date:** 2026-10-27  
**PR:** #983  
**Branch:** `cursor/es-order-flow-dashboard-e6ab`

## Automated Validation Results ✓

All automated checks pass:

| Check | Status | Command | Result |
|-------|--------|---------|--------|
| Dashboard Build | ✅ PASS | `pnpm run build` | Exit 0, all routes compiled successfully |
| TypeScript Type Check | ✅ PASS | `./node_modules/.bin/tsc --noEmit` | Exit 0, no type errors |
| Route Manifest Tests | ✅ PASS | `node --import tsx tests/routeManifest.node.test.ts` | 6/6 tests passed |

### Routes Confirmed in Build

```
├ ƒ /api/flow                              # Main flow data endpoint
├ ƒ /api/flow/health                       # Health check endpoint (NEW)
├ ƒ /api/flow/ingest                       # Ingest endpoint with validation gates
├ ƒ /api/cron/check-flow                   # Proactive alerting cron (NEW)
```

## Manual Validation Checklist

These require the Vercel preview deployment URL and environment variables:

### 1. Health Endpoint
```bash
curl https://<preview-url>/api/flow/health

# Expected response:
{
  "status": "live" | "stale" | "offline",
  "age_seconds": <number>,
  "last_update": "<ISO timestamp>",
  "size_bytes": <number>
}

# Status thresholds:
# - live: < 10s
# - stale: 10-120s
# - offline: >= 120s or blob unreachable
```

**Acceptance:** Returns valid JSON with all fields

### 2. Validation Gates (Reject Bad Data)
```bash
# Test with unrealistic ES price (should be rejected)
curl -X POST https://<preview-url>/api/flow/ingest \
  -H "Authorization: Bearer $FLOW_INGEST_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"ts":"2024-01-01","es":{"last":99999,"vwap":5000,"cvd":0,"bars1m":[]}}'

# Expected response:
{
  "error": "Data failed validation",
  "hint": "Check source data quality (price range, CVD bounds, bar integrity, timestamp age)"
}
# HTTP Status: 400
```

**Acceptance:** Returns 400 with validation error (not 200, not 500)

### 3. Cron Auth - Wrong Secret
```bash
curl https://<preview-url>/api/cron/check-flow \
  -H "Authorization: Bearer wrong-secret"

# Expected response:
{
  "error": "Unauthorized"
}
# HTTP Status: 401
```

**Acceptance:** Returns 401 Unauthorized

### 4. Cron Auth - Correct Secret
```bash
# Requires CRON_SECRET env var set in Vercel
curl https://<preview-url>/api/cron/check-flow \
  -H "Authorization: Bearer $CRON_SECRET"

# Expected response:
{
  "status": "healthy" | "alerted",
  "age_minutes": <number>
}
# HTTP Status: 200
```

**Acceptance:** Returns 200 with status (not 401, not 500)

## Data Quality Gates Verified in Code

The following validation rules are implemented in `dashboard/lib/flowSanitize.ts`:

| Check | Threshold | Rejects |
|-------|-----------|---------|
| ES price range | 1000-10000 | Price outside realistic range |
| CVD magnitude | abs(CVD) < 10000 | Implausibly large cumulative delta |
| Price/VWAP divergence | abs(price - vwap) < 100 | Calculation errors |
| Bar integrity | volume >= 0, high >= low | Malformed OHLCV bars |
| Timestamp age | -60s to +300s | Clock skew or stale data |
| Bars present | len(bars) > 0 | Missing aggregation data |

## CI Status

From PR #983 latest commit `6754be40`:

**Passing (Critical):**
- ✅ Dashboard Build (Next.js)
- ✅ Dashboard Quality (typecheck + unit tests)
- ✅ Engine Tests (pytest, fast)
- ✅ Engine Tests (pytest, slow)
- ✅ Engine Type Check (mypy)
- ✅ Engine Lint (Python)
- ✅ Safety-critical config gate
- ✅ Security Scan

**Failing (Non-blocking):**
- ❌ MIP metadata contract (PR governance - missing metadata sections in PR body, not a code issue)

## Tier 0 Verdict

**Automated validation: COMPLETE ✓**

All code quality checks pass. The monitoring stack compiles, type-checks, and passes all route manifest tests.

**Manual validation: PENDING**

Requires:
1. Vercel preview URL
2. Environment variables (`CRON_SECRET`, `FLOW_INGEST_TOKEN`, `BLOB_READ_WRITE_TOKEN`)
3. Running the 4 manual curl tests above

**Ready for merge:** YES (pending manual endpoint verification)

## Next Steps

1. Get Vercel preview URL from PR comments or Vercel dashboard
2. Run 4 manual curl tests above
3. If all pass → commit this validation doc and merge PR
4. After merge → Set up UptimeRobot, Discord webhooks, Windows watchdog (per Phase 1.3)
5. Then proceed to Tier 1 (Observability) - Week 1 work
