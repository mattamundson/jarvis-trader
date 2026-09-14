# Polybot execution-risk evidence contract

Status: research/test scaffold only. No live trading config, paper trading config,
risk limits, kill-switch state, broker routing, API keys, `.env` files, PM2,
symbol gates, scheduled tasks, or order behavior are changed.

## Source mined

- Reference repo: `mattamundson/polybot`
- Reference commit: `f298140` (`main`, archived repo)
- Selected source files reviewed locally:
  - `docs/STRATEGY_RESEARCH_GUIDE.md`
  - `docs/EXAMPLE_STRATEGY_SPEC.md`
  - `analytics-service/clickhouse/init/*strategy_validation*`
  - `analytics-service/clickhouse/init/*order_lifecycle*`
  - `executor-service/.../LiveTradingGuardFilter.java`
  - `executor-service/.../PaperExchangeSimulator.java`

## Coverage proof

Prior Waves 13 and 14 already covered generic Polymarket probability/order-book
risk and prediction-market backtest-adapter gates. `polybot` adds a different,
non-duplicative lesson: event-market strategy claims are dominated by
**decision-time book freshness, paired-leg inventory, order lifecycle, and
settlement-aware replay**. Those controls belong in an offline evidence schema
before any future event-market research can influence JARVIS scoring.

## Transferable findings

1. The source separates research analytics, execution simulation, order lifecycle,
   and strategy validation tables. JARVIS should keep the same boundary: replay
   evidence is not execution permission.
2. Decision-time top-of-book is load bearing. The source notes stale trade-triggered
   TOB around tens of seconds while websocket TOB can be sub-second; any edge claim
   without freshness evidence is suspect.
3. Complete-set behavior requires both legs. A one-leg directional label is
   incomplete when paired UP/DOWN fills happen within seconds.
4. Execution edge can dominate directional alpha. Reports must show requested price,
   realized fill price, midpoint/fair proxy, fees, slippage, and settlement value.
5. Order lifecycle matters: cancel/replace cadence, stale orders, GTC behavior,
   top-up behavior, and hidden overexposure must be visible in replay artifacts.
6. Venue payloads must stay venue-specific. Polymarket token IDs and Kalshi tickers
   should live in isolated payloads under a common evidence envelope.
7. Live trading guardrails from a reference repo are safety inspiration only; they
   are not permission to port execution code.

## JARVIS implementation from this wave

This wave adds an inert stdlib-only schema helper:

- `engine/research/event_markets/schema.py`

The helper validates fixture/replay records for:

- UTC timestamp normalization, including nanosecond epoch values.
- Probability bounds for bid/ask/mid/raw/normalized prices.
- Bid/ask sanity (`bid <= ask`).
- Venue-specific payload separation (`token_id` for Polymarket, `ticker` for Kalshi).
- Explicit resolved/unresolved outcome handling.
- Deterministic replay hashes independent of input order.

## Promotion boundary

Allowed after this wave:

- Build fixture-only event-market replay examples.
- Add offline validators for probability, freshness, settlement, and order lifecycle.
- Display evidence completeness in research dashboards.

Blocked without a separate `[safety-review]` PR:

- Polymarket/Kalshi/futures/options order routing.
- Live or paper trading config changes.
- Any change to `engine/config.py`, risk limits, kill switches, active instruments,
  PM2, `.env`, broker credentials, or order behavior.
- Treating event-market odds as a strategy promotion override.
