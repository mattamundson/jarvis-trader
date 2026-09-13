# Polymarket probability/order-book risk checklist

Status: docs-only research-control artifact. No live trading config, paper trading config, risk limits, kill-switch state, broker routing, API keys, `.env` files, PM2, symbol gates, or order behavior are changed.

## Source mined

- Reference repo: `mattamundson/Polymarket-Trading-Bot`
- Reference commit: `edbe8cdc70ee7eff255d3f1659bf95fe794d3f72` (`main`, repo pushed 2026-04-22)
- Files reviewed through GitHub API:
  - `README.md`
  - `package.json`
  - `src/types.ts`
  - `src/core/engine.ts`
  - `src/data/market_fetcher.ts`
  - `src/data/orderbook_stream.ts`
  - `src/execution/order_router.ts`
  - `src/execution/position_manager.ts`
  - `src/execution/trade_executor.ts`
  - `src/paper_trading/fill_simulator.ts`
  - `src/paper_trading/pnl_tracker.ts`
  - `src/paper_trading/slippage_model.ts`
  - `src/risk/exposure_limits.ts`
  - `src/risk/kill_switch.ts`
  - `src/risk/risk_engine.ts`
  - `src/strategies/arbitrage/cross_market_arbitrage.ts`
  - `src/strategies/arbitrage/mispricing_detector.ts`
  - `src/strategies/convergence/filtered_high_prob_convergence.ts`
  - `src/strategies/copy_trading/copy_trade_strategy.ts`
  - `src/strategies/market_making/spread_strategy.ts`
  - `src/strategies/research_ai/ai_forecast_strategy.ts`
  - `src/strategies/registry.ts`
  - `src/strategies/strategy_interface.ts`
  - `src/wallets/paper_wallet.ts`
  - `src/wallets/wallet_manager.ts`
  - `src/whales/whale_analytics.ts`
  - `src/whales/whale_scanner.ts`
  - `tests/order_router.test.ts`
  - `tests/risk_engine.test.ts`
  - `tests/whale_scanner.test.ts`

## Transferable findings for JARVIS

The reference system is a venue-specific prediction-market bot, but its durable value for JARVIS is the way it decomposes edge into probability normalization, order-book quality, venue-risk checks, paper fills, and copy/sentiment features. Treat it as architecture and test inspiration only, not as execution code to port.

High-value source facts:

1. Market-data intake normalizes Gamma API markets into explicit `bid`, `ask`, `midPrice`, `spread`, `outcomePrices`, `volume24h`, `liquidity`, `endDate`, `eventId`, and `seriesSlug` fields.
2. The fetcher paginates active/open markets in 100-row pages, sorts by `volume24hr`, throttles between pages, retries 429/5xx responses, and returns partial data after repeated page failures instead of blocking the whole scanner.
3. The order-book stream polls every 15 seconds by default, caps the live cache at 2,000 markets, persists first/last-seen timestamps, and debounces persistence to at most once every five minutes.
4. Market parsing rejects inactive/closed/non-orderable rows, rejects empty token IDs, rejects all-zero prices, swaps inverted `bestBid > bestAsk`, and derives fallback bid/ask levels when both are zero.
5. The base risk path is deterministic: order router loads wallet state, runs risk checks first, then calls the executor only when the risk engine returns `ok=true`.
6. The risk engine blocks on active kill switch, insufficient balance, max position size, max open trades, max daily loss, max drawdown, max exposure per market, and order-rate limits. The source default limits are `maxPositionSize=100`, `maxExposurePerMarket=200`, `maxDailyLoss=100`, `maxOpenTrades=5`, `maxDrawdown=0.20`; its order-rate cap is `120/min` in paper mode and `20/min` in live mode.
7. The paper fill path has an explicit adverse slippage model: buy fills move price up, sell fills move price down, with slippage capped at 1% and scaled by `0.001 * log10(size + 1)`.
8. Cross-market arbitrage checks binary YES+NO sum drift, event-cluster probability consistency, staleness under 60 seconds, volume/liquidity floors, a fee estimate, edge after costs in net bps, and half-Kelly sizing capped by capital, liquidity, and absolute shares.
9. Mispricing arbitration combines spread analysis, VWAP deviation, price-volume divergence, mean reversion, order-flow imbalance, and event-level validation. It also exposes a useful red flag: top-of-file comments cite 60 bps take-profit / 80 bps stop-loss, while the implemented management block uses 100 bps take-profit / 60 bps stop-loss / trailing/time/spread exits. JARVIS should explicitly fail docs-vs-code drift before promotion.
10. Market making gates quote candidates by volume, liquidity, spread, probability band (`0.05 < YES < 0.95`), recent-spike avoidance, volatility-adjusted spread, inventory skew, per-market inventory limit, and max quoted-market count.
11. The convergence strategy is the cleanest checklist template: liquidity, probability band, spread, time-to-resolution, anti-chase, order flow, volume trend, and cluster exposure are counted as explicit rejection reasons.
12. The copy/whale subsystem should be treated as a sentiment/research feed, not a trade copier. Its transferable controls are max trade age, min/max copied notional, min source win rate, daily-volume cap, drawdown pause, consecutive-loss cooldown, market whitelist/blacklist, and per-whale performance tracking.
13. Tests prove at least the minimum invariant shape: risk checks approve in-limit orders, kill switch rejects orders, and order router reaches the executor only after risk passes.

## JARVIS probability/order-book evidence gate

Any future JARVIS feature that uses prediction-market-style probability, order-book imbalance, or copy-trade sentiment should attach this evidence bundle before it can influence a research-card score, market brief, or dashboard recommendation.

| Gate | Required evidence | Pass condition |
|---|---|---|
| Source venue | Venue/feed, endpoint, timestamp, auth class, raw payload hash | Feed is read-only or paper-only; no secret/API-key values are stored in evidence |
| Market eligibility | Active/open/orderable flags, expiry, outcome/token identifiers | Ineligible, closed, expired, or malformed markets are dropped before scoring |
| Probability normalization | YES, NO, total probability, normalized probability, vig/overround | `YES + NO` drift is measured; normalization math is shown rather than inferred |
| Bid/ask sanity | Best bid, best ask, spread, mid, crossed-market handling | Crossed/zero/empty books are repaired with a flagged fallback or rejected |
| Liquidity/depth | 24h volume, liquidity, depth near touch if available | Candidate clears predeclared floors; thin books cannot raise confidence |
| Freshness/staleness | Last update timestamp, fetch latency, retry count, partial-data flag | Stale or partial feeds can inform research notes but cannot promote execution |
| Edge after costs | Gross edge, spread cost, fee/slippage assumptions, net edge bps | Net edge remains positive after conservative cost model and size-dependent slippage |
| Correlation/event grouping | Event ID/slug, series slug, related markets, cluster exposure | Multi-market signals account for event/series concentration before ranking |
| Position concentration | Proposed exposure by event, symbol, strategy family, and regime | Concentration caps bind before narrative confidence or agent score uplift |
| Exit rule parity | Take-profit, stop-loss, trailing, time exit, flattening conditions | Docs, code, tests, and dashboard labels match exactly; any drift blocks promotion |
| Paper simulator | Fill model, slippage model, fill timestamp, requested vs filled price | Backtest/paper output includes both requested and realized fill economics |
| Rejection telemetry | Counts by rejection reason | A zero-signal cycle explains why nothing passed rather than silently returning empty |
| Human override boundary | Whether operator acted on the signal and why | Operator discretion is separated from model/strategy performance |

## Futures/options adaptation rules

Prediction-market mechanics do not transfer one-to-one into SPY/QQQ/VIX options or MES futures. Use these constraints when adapting ideas:

1. Binary probability is not directional edge by itself. Convert prediction-market odds into a bounded sentiment/context feature unless a separate, instrument-specific JARVIS backtest proves it improves CAGR, drawdown, and calibrated touch/close/failure probabilities after costs.
2. Order-book imbalance is only useful if the source venue and JARVIS target instrument share a plausible causal channel. A Polymarket political/sports book is usually not a futures signal; a macro/event contract may be a research feature only.
3. Copy-trading/whale activity is a candidate sentiment feed, never an execution instruction. Require source-wallet survivorship-bias controls, realized/unrealized PnL split, copied-trade delay, liquidity capacity, and regime segmentation.
4. Market-making logic can inform dashboard diagnostics for spread/depth/adverse selection, but it must not become futures/options quoting automation without a dedicated `[safety-review]` PR.
5. Cross-market arbitrage should be translated into a consistency checker: probabilities, futures-implied move, options-implied move, VIX term structure, and macro calendar should agree enough to explain a recommendation. Disagreement is a risk flag, not an auto-trade.
6. Any probability-derived feature must log the exact calculation: raw odds, normalized odds, timestamp, latency, source, smoothing, and stale-data behavior.

## Implementation boundary

Allowed from this artifact:

- Add research-report templates for probability normalization and order-book quality.
- Add offline validators that check evidence payloads for bid/ask sanity, freshness, normalization, cost/slippage assumptions, and docs-vs-code exit parity.
- Add dashboard-only evidence completeness indicators, if scoped separately.
- Use prediction-market data as a paper-only research/sentiment input after source provenance and lag are explicit.

Blocked from this artifact without a dedicated `[safety-review]` PR:

- Any live or paper order-routing change.
- Any copy-trading, wallet-following, or venue-specific execution integration.
- Any change to `engine/config.py`, risk limits, kill-switch logic, active instrument gates, `.env`, PM2, broker routing, or order behavior.
- Any provider/API-key or secret configuration change.
- Any feature that lets prediction-market odds override JARVIS gate/verdict failures.

## Recommended next implementation candidate

Mine `mattamundson/prediction-market-backtesting` into a docs-only backtest-adapter/evidence checklist. Focus on event-market schema lessons, deterministic replay requirements, cost/slippage modeling, and why venue-specific adapters stay isolated from JARVIS futures/options execution until a separate safety-reviewed implementation scope exists.
