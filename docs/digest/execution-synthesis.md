# Execution Module — Research Synthesis

**Classifier bucket:** execution (brokers, order routing, paper trading)
**Items reviewed:** 1
**Date:** 2026-04-16

## TL;DR

One item — `krakenfx/kraken-cli`, an AI-native CLI + MCP server for Kraken spot/futures/forex/xStocks. **Low relevance to jarvis-trader's current execution stack** (IB Gateway paper 4002 + Schwab for US futures MCL/MNQ/MES). Kraken offers no CME futures, no ES/NQ/CL contracts, and xStocks are unavailable in the USA. Useful as a reference design for agent-first CLI ergonomics (JSON-only stdout, stable error categories, MCP-over-stdio) but not as a broker swap-in. **Recommendation: note the patterns, skip the integration.**

## Dedup against existing stack

- `engine/execution/ib_gateway.py` + `ib_order_manager.py` — already the primary paper/live router on CME futures. Kraken does not list MCL/MNQ/MES. No overlap.
- `engine/execution/schwab_connector.py` — US retail broker for equity/options fallback. Kraken xStocks are explicitly non-USA. No overlap.
- `engine/execution/order_router.py` — broker abstraction. Adding a Kraken adapter is technically possible but pointless unless Matt pivots to crypto perps (BTC/ETH) or Kraken's five forex perps, which is outside the current multi-market framework.
- MCP server pattern — jarvis-trader already runs Alpaca MCP (configured, needs real keys per MEMORY.md). Kraken's MCP design is similar: stdio transport, service groups, `acknowledged=true` guardrail for destructive tools.

## Novel patterns worth stealing (ranked)

1. **Error envelope contract** (high value, zero code change today). Kraken's 9-category stable `error` field (`auth`, `rate_limit`, `validation`, `api`, `network`, `config`, `websocket`, `io`, `parse`) with `retryable` + `suggestion` + `docs_url` fields is cleaner than jarvis-trader's ad-hoc exception handling in `order_router.py`. Worth a future refactor to standardize execution-layer errors in the same shape — would make `OpenClaw` routing decisions trivially deterministic. See `agents/error-catalog.json` in the repo.

2. **Dangerous-tool gating via `acknowledged=true`** (medium value). Kraken's MCP default requires explicit acknowledgement for destructive calls (orders, withdrawals, staking). Applicable pattern for the WhatsApp-approval flow Matt already runs — could formalize the approval contract as an `acknowledged` field on pipeline→execution handoff rather than out-of-band Discord/WhatsApp state.

3. **JSON-only stdout, stderr for diagnostics** (low value for jarvis-trader since engine is FastAPI, not CLI). Worth noting if the `openclaw` shell-out surface ever grows.

## Noise / non-actionable

- Kraken crypto spot/perps, xStocks, forex — outside mandate (US-based CME futures focus per `multi-market-trading-framework.md`).
- Single-binary Rust install via `curl | sh` — Windows requires WSL, adds ops surface for zero gain.
- Signed releases via minisign — good hygiene, not adoptable as a pattern since jarvis-trader isn't distributed.

## Receipts

- Source: `C:\Users\mattm\discord-export\digest-raw\by-module\execution.json`
- Repo README: `C:\Users\mattm\discord-export\digest-raw\github\krakenfx__kraken-cli.md`
- URL: https://github.com/krakenfx/kraken-cli
- Shared: 2026-04-15
- Cross-ref existing stack:
  - `engine/execution/ib_gateway.py`
  - `engine/execution/ib_order_manager.py`
  - `engine/execution/schwab_connector.py`
  - `engine/execution/order_router.py`
  - `engine/execution/paper_trade_logger.py` (deprecated; warning added 2026-04-10 per MEMORY.md)

## Action items

None urgent. If interest grows in the error-envelope refactor (item 1 above), pair it with the `PaperTradeTracker` migration that's already underway — both touch `engine/execution/` surface and would benefit from landing together.
