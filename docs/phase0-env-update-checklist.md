# engine/.env Phase 0 Update Checklist
# Generated: 2026-05-05
# Use this after all 15 Phase 0 services are rotated in 1Password "Amo Personal"

## Instructions
1. Open engine/.env in your editor
2. For each row below: copy the new value from 1Password and paste over the old value
3. Signal "env updated" when done — Claude will restart the engine

## Credential Variables to Update

| Variable | 1Password Item | Field | Notes |
|---|---|---|---|
| ANTHROPIC_API_KEY | Anthropic-API | credential | Already rotated (T1 complete) |
| TWILIO_ACCOUNT_SID | Twilio-API | account_sid | |
| TWILIO_AUTH_TOKEN | Twilio-API | auth_token | |
| TELEGRAM_BOT_TOKEN | Telegram-Hermes-Bot | token | |
| API_KEY | Jarvis-Internal | API_KEY | New key generated: se0tj2ADf0yNltWJkVeWaj1mOHxOfMi6Bw_EtWSCFfs |
| DISCORD_WEBHOOK_URL | Teams-Webhook | webhook_url | Currently same value as JARVIS_DISCORD_APPROVAL_WEBHOOK — confirm if 2 separate channels needed |
| JARVIS_DISCORD_APPROVAL_WEBHOOK | Teams-Webhook | approval_webhook_url | Currently same value as DISCORD_WEBHOOK_URL |
| BRAVE_API_KEY | Brave-API | credential | |
| POLYGON_API_KEY | Polygon-API | credential | Phase 0 may not cover Polygon — rotate when convenient |
| FINNHUB_API_KEY | Finnhub-API | credential | Phase 0 may not cover Finnhub — rotate when convenient |

## Variables to ADD (new, not currently in .env)

These are new variables from Jarvis-Internal that the engine should reference:

| Variable | Value to Add | 1Password Item |
|---|---|---|
| JWT_SECRET_KEY | (from 1P Jarvis-Internal) | Jarvis-Internal / JWT_SECRET_KEY |
| AUDIT_HMAC_KEY | (from 1P Jarvis-Internal) | Jarvis-Internal / AUDIT_HMAC_KEY |
| BASIC_AUTH_PASS | (from 1P Jarvis-Internal) | Jarvis-Internal / BASIC_AUTH_PASS |
| ADMIN_PASSWORD | (from 1P Jarvis-Internal) | Jarvis-Internal / ADMIN_PASSWORD |

## Variables with Placeholder Values (need real keys)

| Variable | Status |
|---|---|
| FRED_API_KEY | Has placeholder — get real key from https://fred.stlouisfed.org/docs/api/api_key.html |
| ALPACA_API_KEY | Has placeholder — get from https://alpaca.markets (paper trading) |
| ALPACA_SECRET_KEY | Has placeholder — same as above |
| STOCKTWITS_TOKEN | Has placeholder — get from https://stocktwits.com/developers |

## Things to Fix While Editing

1. Remove duplicate FUTURES_MIN_CONFIDENCE_TO_TRADE (one definition should be at the top half, remove it — keep the one lower in the file)
2. Consider consolidating OLLAMA_BASE_URL and OLLAMA_HOST (both point to http://127.0.0.1:11434)
