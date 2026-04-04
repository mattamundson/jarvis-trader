# WhatsApp Trade Approval — Setup & Test

## Overview

JARVIS can receive trade approval replies via WhatsApp. When the pipeline flags a trade for human
review, a WhatsApp alert is sent via OpenClaw. Reply with one word from your phone.

## Commands

| Reply | Action |
|-------|--------|
| **yes** or **approve** or **y** | Approve most recent pending trade |
| **no** or **reject** or **n** | Reject most recent pending trade |
| **hold** or **skip** or **h** | Leave pending — no action taken |
| anything else | Returns unknown command message |

## Configuration

### 1. Set OPENCLAW_WHATSAPP_TO in engine/.env

```
OPENCLAW_WHATSAPP_TO=+17634520414
```

### 2. Register the JARVIS inbound webhook with OpenClaw

OpenClaw must forward inbound messages to the engine. Register once:

```bash
curl -X POST http://localhost:8009/api/oc/webhook/register \
  -H "Content-Type: application/json" \
  -d '{"url": "http://localhost:8010/openclaw/webhook", "events": ["message.received"]}'
```

### 3. Verify endpoint is mounted

```bash
curl http://localhost:8010/openapi.json | python -m json.tool | grep openclaw
```

Expected: `"POST /openclaw/webhook"` in the output.

## Testing

### Test with no pending trades (expected: no_pending response)

```bash
curl -X POST http://localhost:8010/openclaw/webhook \
  -H "Content-Type: application/json" \
  -H "X-API-Key: jarvis-dev-key-change-me" \
  -d '{"message": "yes", "from_number": "+17634520414"}'
```

Expected response:
```json
{"status": "no_pending", "message": "JARVIS: No pending trades to approve"}
```

### Test rejection

```bash
curl -X POST http://localhost:8010/openclaw/webhook \
  -H "Content-Type: application/json" \
  -H "X-API-Key: jarvis-dev-key-change-me" \
  -d '{"message": "no", "from_number": "+17634520414"}'
```

### Test unknown command

```bash
curl -X POST http://localhost:8010/openclaw/webhook \
  -H "Content-Type: application/json" \
  -H "X-API-Key: jarvis-dev-key-change-me" \
  -d '{"message": "maybe", "from_number": "+17634520414"}'
```

Expected: `{"status": "unknown_command", ...}`

## How It Works

1. Pipeline generates LONG/SHORT signal → `notify_approval_required()` sends WhatsApp alert via OpenClaw
2. Matt replies "yes" on phone
3. OpenClaw receives the reply and forwards it to `POST /openclaw/webhook`
4. JARVIS verifies sender matches `OPENCLAW_WHATSAPP_TO`
5. Finds most recent row in `pending_trade_approvals` with `status = 'pending'`
6. Calls `paper_tracker.open_trade()` then marks the row `approved` via `resolve_pending_approval()`
7. Sends WhatsApp confirmation: "JARVIS: Approved — MCL LONG @ $71.23 opened"

## OpenClaw Payload Formats Supported

The endpoint handles multiple envelope formats OpenClaw may send:

```json
{"message": "yes", "from_number": "+17634520414"}
{"text": "yes", "from": "+17634520414"}
{"body": "yes", "sender": "+17634520414"}
```

## Security

Sender verification compares the inbound number against `OPENCLAW_WHATSAPP_TO` (E.164 digits only,
stripped of `whatsapp:` prefix and `+`). Mismatched senders receive `{"status": "unauthorized"}`
and the request is not processed. If `OPENCLAW_WHATSAPP_TO` is not set, verification is skipped
(development mode).

## Approval Precedence

The webhook approves the **most recently created** pending trade (ORDER BY created_at DESC). If
multiple trades are queued, repeat "yes" to approve them in sequence.

## Error Conditions

| Condition | Response |
|-----------|----------|
| Kill switch active | HTTP 409 — cannot approve while kill switch is on |
| No entry price in snapshot | HTTP 400 — trade cannot be priced |
| Database unavailable | HTTP 503 |
| Race condition (already resolved) | HTTP 409 |
