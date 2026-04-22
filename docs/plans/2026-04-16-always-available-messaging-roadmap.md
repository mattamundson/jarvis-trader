# Always-Available Agent Messaging — Roadmap

**Created:** 2026-04-16
**Goal:** When Claude/Codex/Gemini are maxed out, Matt can message OpenClaw and Hermes from Telegram or WhatsApp and get responses powered by free local Ollama models.

## Current State

- OpenClaw E2E working via `/messaging/chat` with local Ollama qwen2.5:7b (~90-143s latency)
- Hermes CLI adapter wired but stalls (3 config mismatches blocking inference)
- Telegram bot token exists, webhook endpoint exists, webhook not registered
- WhatsApp linked to OpenClaw, inbound forwarding not configured
- Ollama running with 6 models (qwen2.5:7b, hermes3, gpt-oss:20b, qwen2.5-coder:32b, llama3.3, nomic-embed-text)
- Engine healthy on port 8010, OpenClaw gateway healthy on 18789

## Task Dependency Graph

```
T1 (Hermes fix) ─────────────────────────────┐
                                              ├─→ T10 (Hermes native Telegram)
T2 (Register webhook) ──┬──→ T3 (Telegram E2E)
                        └──→ T6 (Auto-registration)

T4 (WhatsApp inbound) ── independent
T5 (Persona fix) ──────── independent
T7 (/model command) ───── independent
T8 (Update OpenClaw) ──── independent
T9 (Health monitor) ───── independent
```

## Tasks (Priority Order)

### T1: Fix Hermes Local Inference — 30min
**Why:** Doubles available agents from 1→2.

1. Fix `/root/.hermes/config.yaml`: provider→custom, model→qwen2.5:7b
2. Fix `/root/.hermes/.env`: LLM_MODEL=qwen2.5:7b, HERMES_INFERENCE_PROVIDER=custom
3. Verify Ollama serving: `curl http://127.0.0.1:11434/api/tags`
4. Kill stale processes: `pkill -f 'hermes chat'`
5. Test direct CLI: `timeout 120 hermes chat -q 'Reply HERMES_OK' -Q`
6. Test via gateway: `POST /messaging/chat` with `/hermes Reply HERMES_OK`
7. Confirm reply_text populated, health_state=ok

### T2: Register Telegram Webhook — 15min
**Why:** One API call unlocks bidirectional Telegram.

1. Read TELEGRAM_BOT_TOKEN from .env
2. Set up tunnel (ngrok or Cloudflare) for public HTTPS URL
3. Register: `POST https://api.telegram.org/bot{TOKEN}/setWebhook?url={URL}/messaging/inbound/telegram`
4. Verify: `GET getWebhookInfo` — URL set, no errors
5. Send test message from Telegram app
6. Add TELEGRAM_WEBHOOK_URL to .env.example

### T3: Telegram E2E Round-Trip — 20min (blocked by T2)
**Why:** Proves the entire pipeline works from phone.

1. Send `/openclaw Say hello` from Telegram
2. Verify engine logs show inbound
3. Verify reply appears in Telegram within 3min
4. Test `/hermes Say hello` (requires T1)
5. Test `/status`, `/agent hermes`, `/reset`

### T4: Wire WhatsApp Inbound → Gateway — 45min
**Why:** Second messaging channel for redundancy.

1. Check OpenClaw webhook forwarding config
2. Configure forwarding to `localhost:8010/messaging/inbound/whatsapp`
3. Alternative: Twilio webhook direct to public URL
4. Test E2E: WhatsApp → engine → agent → reply

### T5: Fix OpenClaw Agent Persona — 30min
**Why:** Agent currently returns career-ops alerts instead of answering prompts.

1. Audit `/root/.openclaw/workspace/skills/`
2. Create trading-only agent profile or strip career-ops context
3. Update command template if using separate agent
4. Verify: "Reply with exactly X" returns X

### T6: Telegram Webhook Auto-Registration — 20min (blocked by T2)
**Why:** Survives engine restarts.

1. Add startup hook in messaging_router.py
2. Read TOKEN + WEBHOOK_URL from env, call setWebhook
3. Log success/failure, skip gracefully if not configured
4. Add manual re-registration endpoint

### T7: Add /model Switch Command — 45min
**Why:** Trade speed vs capability from chat.

1. Add `/model`, `/model list`, `/model set <name>` to command parser
2. Query Ollama `/api/tags` for available models
3. Persist choice per-user in SQLite
4. Validate model exists, warn on large models

### T8: Update OpenClaw to 2026.4.15 — 20min
**Why:** Fixes version warnings, 2 CRITICAL security findings.

1. Backup config, run update
2. Verify gateway healthy post-update
3. Address security findings
4. Clean stale sessions (51→manageable)

### T9: Health Monitoring + Auto-Recovery — 60min
**Why:** Self-healing when backends go down.

1. Periodic health check (60s) for Ollama, OpenClaw, Hermes
2. Auto-restart on failure (one retry per 5min window)
3. Alert via available channel if recovery fails
4. Store 24h health history in SQLite

### T10: Hermes Native Telegram Fallback — 45min (blocked by T1)
**Why:** Backup path if JARVIS engine is down.

1. Create second Telegram bot OR document webhook switchover
2. Configure Hermes gateway with local Ollama
3. Test: engine stopped, Hermes Telegram still responds
4. Document failover procedure in runbooks/

## Architecture

```
[Telegram App] ──webhook──→ [Engine :8010/messaging/inbound/telegram]
[WhatsApp]     ──webhook──→ [Engine :8010/messaging/inbound/whatsapp]
                                         │
                                   SharedAgentGateway
                                    /              \
                            CliAdapter          CliAdapter
                           (OpenClaw)           (Hermes)
                               │                    │
                          WSL subprocess       WSL subprocess
                               │                    │
                        openclaw agent         hermes chat
                               │                    │
                          Ollama qwen2.5:7b    Ollama qwen2.5:7b
                          (port 11434)         (port 11434)

[Fallback: Hermes native Telegram gateway — independent of engine]
```

## Success Criteria

All paid APIs maxed out. You open Telegram. You type `/openclaw what's the MCL regime?` and get a response within 3 minutes from your local 7B model. You type `/hermes summarize today's trades` and get a response. You type `/status` and see both agents healthy. Zero dollars spent.
