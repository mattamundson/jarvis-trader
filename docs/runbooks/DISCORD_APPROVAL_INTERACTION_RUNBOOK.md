# DISCORD APPROVAL INTERACTION RUNBOOK

> Companion to: `AUTONOMOUS_PIPELINE_RUNBOOK.md`
> Safety scope: `[safety-review]` — any change here is in the approval-path.

---

## Overview

The Discord reaction watcher (`engine/discord/reaction_watcher.py`) lets Matt
approve, reject, or extend trade candidates by reacting to bot-posted messages
in the personal channel — from any device (phone, desktop, watch).

When the autonomous pipeline enqueues a candidate and the webhook posts it to
the channel, Matt reacts with one of three emojis and the engine acts:

| Emoji | Action | Engine endpoint |
|---|---|---|
| ✅ | Approve — submits paper order via `safety_layer.submit_paper_order()` | `POST /approvals/{id}/approve` |
| ❌ | Reject — marks candidate rejected, no order | `POST /approvals/{id}/reject` |
| ⏸ | Hold/Extend — pushes TTL forward 30 minutes | `POST /approvals/{id}/extend?minutes=30` |

The bot replies in-channel with the result of each action (success or error detail).

---

## Required Environment Variables

Both must be set in `engine/.env` for the watcher to start. Missing either
causes `is_reaction_watcher_enabled()` to return `False` and the watcher
to exit immediately — the engine boots normally without it.

```
# Discord bot token (already present for personal_mcp_server.py)
DISCORD_PERSONAL_BOT_TOKEN=Bot_YOUR_TOKEN_HERE

# Matt's Discord user ID — ONLY reactions from this account trigger approvals
DISCORD_PERSONAL_USER_ID=123456789012345678
```

### How to find your Discord user ID

1. Open Discord (desktop or web).
2. Settings → Advanced → enable **Developer Mode**.
3. Right-click your avatar anywhere → **Copy User ID**.
4. Paste into `DISCORD_PERSONAL_USER_ID`.

### How to create / configure the bot

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications).
2. Create application → Bot tab → **Reset Token** (copy it to `DISCORD_PERSONAL_BOT_TOKEN`).
3. Bot tab → Privileged Gateway Intents → enable:
   - **Server Members Intent**
   - **Message Content Intent** (required to read message text for candidate ID extraction)
4. OAuth2 → URL Generator → Scopes: `bot` → Bot Permissions:
   - View Channels, Read Message History, Send Messages, Add Reactions.
5. Invite the bot to your guild via the generated URL.

---

## Security Model

**The watcher is user-gated at three levels:**

1. **Reactor user ID**: only `DISCORD_PERSONAL_USER_ID` can trigger an action.
   Any reaction from another user in the channel is logged at DEBUG and ignored.

2. **Bot-authored messages only**: the watcher fetches the reacted-to message via
   Discord REST and confirms the `author.id` matches the bot's own user ID
   (received in the gateway READY event). Reactions to messages posted by
   humans or other bots are silently dropped.

3. **Engine safety gates**: the `/approvals/{id}/approve` endpoint re-checks
   `kill_switch_active` and `LIVE_TRADING_ENABLED=False` fresh on every call.
   A kill-switch trip between the reaction and the approval HTTP round-trip will
   cause the approve call to return HTTP 409 and the bot will post the error.

**Risk surface:** if Matt's Discord account is compromised, an attacker who can
access the personal channel and knows the bot is active could approve paper
trades. Mitigated today by paper-only mode (`LIVE_TRADING_ENABLED=False`). For
Phase 3 live trading, the approval gate should require an additional factor
(e.g., hardware confirmation button or signed webhook with rotating secret)
before any real order goes to IB Gateway.

---

## Watcher Lifecycle

- **Starts on engine boot** when both required env vars are set.
- **Managed by `asyncio.create_task()`** inside the FastAPI lifespan context.
- **Cancelled gracefully** in the lifespan teardown (engine shutdown).
- **Self-healing**: on disconnect (network blip, gateway restart, etc.),
  the watcher backs off exponentially (2 → 4 → 8 → 16 → 32 → 60 s cap) and
  reconnects using Discord's RESUME flow (preserves session / avoids re-IDENTIFY
  rate limit). Non-resumable close codes (4004 auth invalid, 4010 invalid shard,
  etc.) trigger a fresh IDENTIFY instead.

---

## Failure Modes

| Failure | Behavior |
|---|---|
| `DISCORD_PERSONAL_BOT_TOKEN` not set | Watcher does not start; logged at INFO; engine boots normally |
| `DISCORD_PERSONAL_USER_ID` not set | Same as above |
| Bot offline / gateway unreachable | Exponential back-off reconnect loop; never crashes engine |
| Wrong user reacts | Silently ignored; logged at DEBUG |
| Reaction on non-bot message | Silently ignored; logged at DEBUG |
| Bot message has no parseable candidate ID | Logged at INFO; no action taken |
| Engine returns HTTP 4xx/5xx on approve/reject | Error message posted to channel; reaction counted as a no-op |
| Engine down (connection refused) | Error message posted if channel post itself works; otherwise logged; back-off loop continues |

---

## Candidate ID Format

The candidate ID is extracted from the bot-posted message content using this regex:

```
(?:candidate|approval)[^(]*\((?:ID\s*)?(\d+)\)
```

This matches patterns like:
- `New trade candidate (ID 17) — MCL LONG @ 72.50`
- `Approval candidate (id 42): MNQ SHORT`
- `Trade candidate (17)`

The sibling webhook agent must post messages containing one of these formats for
the reaction watcher to extract the ID. If the message format changes, update
`_CANDIDATE_ID_RE` in `reaction_watcher.py`.

---

## Extend Endpoint Details

`POST /approvals/{id}/extend?minutes=30`

- Adds `minutes` to the candidate's `expires_at` from the current time.
- `minutes` is **clamped** to [5, 120]. Values outside this range are silently adjusted.
- Only works on `status=pending` candidates. Approved, rejected, or expired candidates
  return HTTP 409.
- Logged to `data/approval_audit.jsonl` with `event=extended`.
- Does NOT submit any order. It only buys more review time.

---

## Environment Variables Reference

| Variable | Required | Description |
|---|---|---|
| `DISCORD_PERSONAL_BOT_TOKEN` | Yes (for watcher) | Bot token from Discord Developer Portal |
| `DISCORD_PERSONAL_USER_ID` | Yes (for watcher) | Matt's Discord snowflake user ID |
| `DISCORD_PERSONAL_CHANNEL_ID` | No | Defaults to `1490851279180660819` |
| `API_KEY` | Engine-wide | X-API-Key used for engine calls (already set) |
| `ENGINE_BASE_URL` | No | Defaults to `http://127.0.0.1:8010` |

---

## Files

| Path | Purpose |
|---|---|
| `engine/discord/reaction_watcher.py` | Watcher — gateway WS loop + reaction dispatch |
| `engine/routers/approval_queue_router.py` | HTTP surface — includes new `/extend` endpoint |
| `engine/main.py` | Lifespan wiring for `create_task(watch_approval_reactions())` |
| `engine/.env.example` | Documents `DISCORD_PERSONAL_USER_ID` |
| `engine/tests/test_reaction_watcher.py` | Unit tests (8 cases, mock gateway) |
| `engine/tests/test_approval_extend.py` | Unit tests for /extend endpoint (6 cases) |

---

## Cross-References

- Autonomous pipeline (enqueues candidates): `AUTONOMOUS_PIPELINE_RUNBOOK.md`
- Discord personal MCP (REST, no gateway): `engine/discord/personal_mcp_server.py`
- Safety rules: `.claude/rules/safety.md`
- Kill switch: `engine/risk/safety_layer.py`
- Approval audit log: `engine/data/approval_audit.jsonl`
