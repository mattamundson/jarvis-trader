# AUTONOMOUS PIPELINE RUNBOOK

> Status: **ACTIVE** — enabled 2026-05-21 with conservative defaults.
> Any change to this system is a `[safety-review]` scope commit.

---

## Activation Status (2026-05-21)

Enabled by Amo, 2026-05-21 ~18:30 CDT.

| Variable | Value |
|---|---|
| `ENABLE_AUTONOMOUS_PIPELINE` | `1` |
| `AUTONOMOUS_TICK_SECONDS` | `600` (10 min — conservative) |
| `AUTONOMOUS_CONFIDENCE_THRESHOLD` | `0.75` (above default 0.65) |
| `AUTONOMOUS_ACTIVE_SYMBOLS` | `MCL,MNQ` |

**Pre-flight:** all required gates passed. IB data disconnected (non-fatal — Polygon fallback).
**Engine restarted:** 18:30 CDT. Loop confirmed started in logs at 18:30:53.
**First tick:** MCL → HOLD (fund manager priority=skip, ranging regime ADX 17.8). MNQ → HOLD.
**Approval queue:** empty (no candidates above 0.75 threshold). Expected at market close.

**To deactivate:** set `ENABLE_AUTONOMOUS_PIPELINE=0` in `engine/.env` + `.\restart_engine.ps1`.
Pending candidates auto-expire on TTL (30 min). Nothing auto-executes.

Full activation record:
`master-jarvis/second-brain/raw/_session-2026-05-21-amo/wiki/system/autonomous-scheduler-activated.md`

---

## What It Does

The autonomous pipeline scheduler (`engine/scheduler/pipeline_autonomous.py`) runs the
5-stage JARVIS TRADER pipeline on a timed interval and **enqueues trade candidates** for
human approval. It never auto-submits an order.

The approval queue (`engine/routers/approval_queue_router.py`) exposes `/approvals/*` HTTP
endpoints and the Hermes Telegram skill for human review.

```
[Scheduler tick]
    → pre-flight (health + kill-switch + LIVE_TRADING gate)
    → pipeline.analyze_and_decide(symbol)
    → if GREEN + confidence >= threshold
        → idempotency check (no duplicate for same symbol/direction with live TTL)
        → INSERT into pipeline_approval_queue
[Human sees queue via Hermes or dashboard]
    → "approve N" → POST /approvals/N/approve
        → re-check kill-switch + LIVE_TRADING_ENABLED
        → safety_layer.submit_paper_order()
        → row → status=approved, order_id recorded
    → "reject N" → POST /approvals/N/reject → row status=rejected, reason logged
[TTL expires] → row status=expired (auto at next list_pending or every 60s via APScheduler)
```

---

## Safety Gates (Non-Negotiable)

| Gate | Where enforced | What happens on failure |
|---|---|---|
| `ENABLE_AUTONOMOUS_PIPELINE != 1` | Every tick (read fresh) | No-op immediately, no pipeline call |
| `LIVE_TRADING_ENABLED = True` | Pre-flight AND approve endpoint | Tick aborts; approve returns HTTP 409 |
| `kill_switch_active = True` | Pre-flight AND approve endpoint | Tick aborts; approve returns HTTP 409 |
| Engine unhealthy | Pre-flight (safety_layer.get_status) | Tick aborts |
| Candidate TTL expired | approve endpoint + list_pending | approve returns HTTP 410; candidate auto-expired |
| Duplicate (symbol, direction) with live TTL | Enqueue idempotency guard | Skips insert, logs SKIP |
| Confidence < threshold | Tick verdict filter | Skips enqueue, logs SKIP |
| **Entry price sanity** | Enqueue (tick) + approve endpoint | Enqueue: skips insert, logs ERROR; approve: HTTP 422 |

The `approve` endpoint makes **two** independent safety checks (pre-flight + safety_layer live
re-check) with no caching between them. A kill-switch trip during the approval HTTP round-trip
will cause the approve call to return 409 even if the pre-flight passed.

---

## Entry Price Sanity Check

Introduced 2026-05-21 to close the corrupted-price class of bug from the 2026-05-09
phantom-trade incident (6 MES SHORT entries at price 7398.5481 — a `stop_loss` value
mis-mapped into the `entry_price` field; real market was ~7385, delta/ATR ≈ 1.35).

**Formula:** `|entry_price - market_price| / ATR > ENTRY_PRICE_SANITY_MAX_ATR_DELTA`

If the ratio exceeds the threshold (default 1.0) the candidate is rejected at TWO points:
1. **At enqueue** (`autonomous_tick`) — corrupted verdict never enters the approval queue.
2. **At approve** (`approve_pending_trade`) — human-initiated approval for a stale corrupted row is blocked with HTTP 422.

**Env vars:**
| Variable | Default | Effect |
|---|---|---|
| `ENABLE_ENTRY_PRICE_SANITY` | `1` | Set to `0` to disable entirely (opt-out) |
| `ENTRY_PRICE_SANITY_MAX_ATR_DELTA` | `1.0` | Raise to allow wider band; lower to tighten |

**To disable temporarily** (e.g., during extreme vol when ATR is unreliable):
```bash
# In engine/.env:
ENABLE_ENTRY_PRICE_SANITY=0
# Then restart: .\restart_engine.ps1
```

**Log signatures to watch for:**
- `[ENTRY_PRICE_SANITY] rejected: [MES] entry_price=7398.5481 is 1.35 ATR units from market=7385`
- `[AutonomousTick][ENTRY_PRICE_SANITY] MES enqueue rejected: ...`

**Edge case — low-volatility regimes:** When ATR is very small (e.g., MGC overnight at 0.5
points), even a legitimately rounded entry (e.g., a 0.6-point slip from market) can fail
the check. If false rejections are observed in flat overnight sessions, raise
`ENTRY_PRICE_SANITY_MAX_ATR_DELTA` to 2.0 or add an absolute floor (minimum ATR = 1 tick).
The current implementation has no absolute floor — consider this before tightening below 1.0.

---

## How to Enable

1. Add to `engine/.env`:
   ```
   ENABLE_AUTONOMOUS_PIPELINE=1
   AUTONOMOUS_CONFIDENCE_THRESHOLD=0.65    # optional, default 0.65
   AUTONOMOUS_CANDIDATE_TTL_SECONDS=1800   # optional, default 1800 (30 min)
   AUTONOMOUS_TICK_SECONDS=300             # optional, default 300 (5 min)
   AUTONOMOUS_ACTIVE_SYMBOLS=MCL,MNQ       # optional, default MCL,MNQ
   ```
2. Restart the engine: `.\restart_engine.ps1`
3. Verify the log contains:
   ```
   ⏰ Autonomous pipeline loop started — tick=300s (ENABLE_AUTONOMOUS_PIPELINE=1 detected at boot)
   ```
4. Smoke-check: `GET http://127.0.0.1:8010/approvals/pending` returns `{"count": 0, "candidates": []}`.

---

## How to Disable

**Runtime (takes effect on the next tick):**
```bash
# In the engine process environment — disable enqueue on next tick:
# (requires engine restart to propagate .env change)
ENABLE_AUTONOMOUS_PIPELINE=0
```

**Permanent:**
1. Set `ENABLE_AUTONOMOUS_PIPELINE=0` (or remove) in `engine/.env`
2. Restart: `.\restart_engine.ps1`
3. Pending candidates in the queue will **expire naturally** (TTL-based). No manual cleanup needed.

---

## Emergency Stop

Even if the flag is `1`:
- Trigger the kill switch (via `/safety/kill-switch` or the dashboard) — the scheduler
  refuses to enqueue on the next tick AND the approve endpoint refuses to submit.
- Kill switches are checked **on every tick** and **on every approve call** — no restart needed.

Sequence for immediate halt:
```
POST http://127.0.0.1:8010/safety/kill-switch   (X-API-Key header required)
```
The autonomous scheduler will see `kill_switch_active: True` on the next tick and abort.

---

## Viewing the Queue

**Via Hermes (Telegram):**
```
list pending approvals
```

**Via API:**
```bash
curl -H "X-API-Key: <key>" http://127.0.0.1:8010/approvals/pending
```

**Via history:**
```bash
curl -H "X-API-Key: <key>" "http://127.0.0.1:8010/approvals/history?days=7"
```

---

## Approving / Rejecting

**Via Hermes:**
```
approve 17
reject 17 because too close to support
```

**Via API:**
```bash
# Approve (entry_price optional — uses pipeline snapshot if absent)
curl -X POST -H "X-API-Key: <key>" -H "Content-Type: application/json" \
  -d '{"entry_price": 2150.50}' \
  http://127.0.0.1:8010/approvals/17/approve

# Reject
curl -X POST -H "X-API-Key: <key>" -H "Content-Type: application/json" \
  -d '{"reason": "not the right setup"}' \
  http://127.0.0.1:8010/approvals/17/reject
```

Every approve/reject is logged to `engine/data/approval_audit.jsonl`.

---

## Candidate Lifecycle

```
ENQUEUED (status=pending, expires_at = now + TTL)
  → APPROVED (status=approved, order_id=<fill_id>)
  → REJECTED (status=rejected, reviewer_notes=<reason>)
  → EXPIRED  (status=expired, auto at list_pending or TTL sweep)
```

Candidates are never deleted — they stay in the DB for audit and history.

---

## Discord Webhook Integration

Every new approval candidate and every approval/rejection result can be posted as a
rich Discord embed to Matt's personal channel — eliminating the need to poll the
dashboard or API to know when a candidate is waiting.

### Setup

1. In Discord: open the target channel → **Edit Channel → Integrations → Webhooks → New Webhook**.
   Copy the webhook URL (format: `https://discord.com/api/webhooks/<id>/<token>`).

2. Add to `engine/.env`:
   ```
   JARVIS_DISCORD_APPROVAL_WEBHOOK=https://discord.com/api/webhooks/<id>/<token>
   ```

3. Restart the engine: `.\restart_engine.ps1`

No other configuration is needed. The feature is **default-OFF** — if the env var is absent
or empty the system behaves exactly as before.

### What you'll see

**When a candidate is enqueued:**
```
New trade candidate (ID 17)
Symbol: MCL  |  Direction: LONG  |  Confidence: 72%
Entry: $73.45  |  Stop: $72.80   (when pipeline provides prices)
Expires: 29 min remaining

Approve via API:
  curl -X POST "http://127.0.0.1:8010/approvals/17/approve" -H "X-API-Key: ..."

Approve via Hermes:
  jarvis-approval-queue "approve 17"
```

**When approved:**
```
Approved — candidate 17
Symbol: MCL  |  Direction: LONG  |  Order ID: INV-12345
```

**When rejected:**
```
Rejected — candidate 17
Symbol: MCL  |  Notes: too close to resistance
```

**When expired:**
```
Expired — candidate 17 (TTL)
```

### Design notes

- **Best-effort:** webhook failures log a WARNING and are never re-tried. The enqueue,
  approve, and reject flows are unaffected even if Discord is unreachable.
- **Rate limits:** Discord webhooks allow ~30 requests/min per channel. With a 300 s
  tick and 2–4 active symbols, the peak rate is ~4 posts per tick — well within limits.
- **No expiry post (yet):** TTL-based expiry is handled by `_expire_stale()` inside
  `list_pending()`. That function does not currently fire a Discord notification — the
  expiry embed is a follow-up TODO once a dedicated TTL sweep task is added.
- **Module:** `engine/notifications/discord_webhook.py` — reads `JARVIS_DISCORD_APPROVAL_WEBHOOK`
  fresh on every call; never cached at module level.

### Troubleshooting

| Symptom | Fix |
|---|---|
| No posts in Discord | Confirm `JARVIS_DISCORD_APPROVAL_WEBHOOK` is set and non-empty in `engine/.env` |
| HTTP 401 from Discord | Webhook URL is wrong or was deleted — regenerate in Discord channel settings |
| HTTP 429 from Discord | Rate-limited; reduce symbols or increase `AUTONOMOUS_TICK_SECONDS` |
| `discord_webhook post failed` in logs | Network issue or Discord outage — transient, self-resolving |

### Cross-reference

- `[[CLAUDE_CODE_AND_HERMES_INTEGRATION_MAP]]` — Hermes approval skill that reads the same queue

---

## Environment Variables Reference

| Variable | Default | Description |
|---|---|---|
| `ENABLE_AUTONOMOUS_PIPELINE` | `0` | `1` to enable. Read fresh every tick. |
| `AUTONOMOUS_CONFIDENCE_THRESHOLD` | `0.65` | Minimum confidence to enqueue |
| `AUTONOMOUS_CANDIDATE_TTL_SECONDS` | `1800` | Candidate TTL (30 min) |
| `AUTONOMOUS_TICK_SECONDS` | `300` | Tick interval (floor = 60s) |
| `AUTONOMOUS_MIN_TICK_SECONDS` | `60` | Race-condition floor — prevents tick < paper-order round-trip |
| `AUTONOMOUS_ACTIVE_SYMBOLS` | `MCL,MNQ` | Comma-separated symbols to scan per tick |
| `JARVIS_DISCORD_APPROVAL_WEBHOOK` | *(unset)* | Discord webhook URL; leave unset to disable |
| `JARVIS_ENGINE_PUBLIC_URL` | `http://127.0.0.1:8010` | Engine URL used in Discord curl snippets |

---

## Known Subtlety — Race Condition Floor

The minimum tick interval is 60 seconds (`AUTONOMOUS_MIN_TICK_SECONDS`). This prevents the
scheduler from firing a second tick before the first paper-order round-trip completes,
which would race the idempotency guard. If `AUTONOMOUS_TICK_SECONDS < AUTONOMOUS_MIN_TICK_SECONDS`,
the floor silently takes precedence and a warning is logged.

---

## Files

| Path | Purpose |
|---|---|
| `engine/scheduler/pipeline_autonomous.py` | Scheduler tick logic + DB helpers |
| `engine/scheduler/__init__.py` | Package marker |
| `engine/routers/approval_queue_router.py` | HTTP surface (/approvals/*) |
| `engine/main.py` | Router wiring + background loop startup |
| `engine/notifications/discord_webhook.py` | Approval-queue Discord embed poster (new) |
| `engine/tests/test_pipeline_autonomous.py` | Scheduler unit tests |
| `engine/tests/test_approval_queue_router.py` | Router unit tests |
| `engine/tests/test_discord_webhook_notifications.py` | Discord webhook unit tests (new) |
| `engine/data/approval_audit.jsonl` | Audit log (auto-created on first approve/reject) |

---

## Cross-References

- Kill switch: `engine/risk/safety_layer.py` (DO NOT MODIFY without Tier 3 + `[safety-review]`)
- Existing approval flow: `engine/approval/service.py`, `engine/routers/approval_router.py`
- Safety rules: `.claude/rules/safety.md`
- Operating philosophy: `docs/runbooks/STARK_MODE_OPERATING_PHILOSOPHY.md`
