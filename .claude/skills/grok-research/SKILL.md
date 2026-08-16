---
name: grok-research
description: On-demand catalyst/news/company research via xAI's Grok API (web search, X search, code execution, vision) through the `grok` MCP server. Use for ad-hoc research during a session — background on a company, a macro event, a technical question — NOT as a trading signal input. Use when asked "look this up on Grok", "check X for <topic>", "research this catalyst", or when a quick code-sandbox calculation would help.
---

# grok-research — xAI Grok MCP wrapper for jarvis-trader

Thin routing layer over the `grok` MCP server ([merterbak/Grok-MCP](https://github.com/merterbak/Grok-MCP), MIT), wired in this repo's `.mcp.json`. This skill does not reimplement anything — it documents jarvis-trader-specific usage and, critically, the scope boundary that keeps it out of the trading pipeline.

## Install prerequisite

Already cloned and dependency-installed at `C:\Users\mattm\Code\tools\Grok-MCP` (native Windows, `uv`-managed venv) and registered in `.mcp.json` as the `grok` server. It still needs a real API key before any tool call will work:

1. Create an API key at [console.x.ai](https://console.x.ai) (Amo-only — billing action).
2. Store it in 1Password vault `Amo Personal` as item `XAI-API` / field `credential`.
3. Write it to `C:\Users\mattm\Code\tools\Grok-MCP\.env` as `XAI_API_KEY=<value>` (gitignored in that repo — never in `.mcp.json`, never committed, same pattern as the existing `x-twitter` MCP server's own local `.env`).

Verify with `list_models` (cheap, no search cost) before relying on the search/agent tools.

## When to use

- Ad-hoc research during a session: company background, a macro event, "what happened with X ticker today", a technical/engineering question.
- `x_search` for X-native discussion on a specific catalyst, with handle/date filters — useful when you know which accounts matter (e.g. a specific analyst, a company's IR account).
- `code_executor` for a quick sandboxed calculation or data transform mid-conversation, without leaving the chat.
- `chat_with_vision` for a chart screenshot or image a human dropped in.

## When NOT to use

- **Autonomous signal generation — this is explicitly out of scope, same boundary as `last30days`.** `x_search`/`web_search` results do NOT feed the debate/trader agents. Do not wire this tool's output into `engine/agents/pipeline.py` or `debate.py` without a separate safety review.
- **Never as a futures sentiment source.** `engine/agents/social_analyst.py:1-21,347-364` hard-gates Reddit/PRAW off for futures symbols (`FUTURES_SUBREDDIT_MAP`) — only Corey Sures' Discord `#market-updates` is trusted futures sentiment, per owner directive 2026-04-19. `x_search` results are exactly the kind of raw social-sentiment signal that gate exists to keep out of futures trading decisions. Treat Grok's X search the same way you'd treat raw Reddit: fine for general research, never as a trading input for futures.
- **Not a replacement for `last30days`** — that skill aggregates Reddit + X + YouTube + TikTok + Polymarket + GitHub with engagement scoring; this is single-provider (Grok's own web/X search + code execution + vision), useful when you specifically want Grok's synthesis or need code execution/vision, not a multi-platform sweep.

## How to invoke

Call the MCP tools directly by name once the `grok` server is connected (Claude Code surfaces each tool's full docstring/args from `src/server.py`):

- `web_search("<query>")` — general web research with citations.
- `x_search("<query>", allowed_x_handles=[...], from_date=..., to_date=...)` — X-native search.
- `grok_agent("<task>")` — unified agent mixing search, files, images, and code execution for a multi-step research task.
- `code_executor("<task>")` — sandboxed Python for a quick calculation.
- `list_models()` — verify the key/connection works before relying on the above.

## Integration with existing workflow

- Complements `last30days`: reach for `last30days` when you want broad multi-platform community sentiment; reach for this when you want Grok's own web/X search synthesis, code execution, or vision.
- Session handoffs: do not capture raw tool output into session logs unless explicitly asked — same ephemeral-research convention as `last30days`.

## Attribution

Wrapper around [merterbak/Grok-MCP](https://github.com/merterbak/Grok-MCP), MIT-licensed. No code copied; this file documents the invocation pattern and jarvis-trader-specific scope boundary only.

## Provenance

Installed 2026-08-15 as part of a broader "install Grok bot" request — see `C:\Users\mattm\.claude\plans\install-grok-bot-on-idempotent-pearl.md` for the full context, including why a Docker-based alternative (djtelicloud/grok-mcp-server) was passed over (no Docker on this machine) and why Hermes' own native `x_search` tool (separate, OAuth-based, currently broken on auth/billing) was left alone rather than duplicated here.
