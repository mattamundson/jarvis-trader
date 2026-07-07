---
repo: runesleo/polymarket-toolkit
url: https://github.com/runesleo/polymarket-toolkit
stars: 94
language: Python
license: MIT
archived: false
pushed_at: 2026-03-31T04:27:08Z
analyzed_at: 2026-04-18
recommendation: partial-integrate
surfaces_with_value: [engine-code, skills, docs]
---

# runesleo/polymarket-toolkit

## Core value proposition

Two AI-callable skills for analyzing Polymarket (prediction market) traders: `polymarket-profile` aggregates PnL, win rate, position breakdown, and auto-detects strategy patterns (Market Maker, SPLIT arbitrage, diversified); `polymarket-brier` rates prediction accuracy via Brier Score and calibration analysis. Both query public APIs (no auth required) and output structured data suitable for trader intelligence or signal sourcing.

## Surface analysis

### 1. Engine code
`partial-integrate` — PnL aggregation and win-rate calculation logic (settlement-based, not position-level) is directly ported to `engine/analytics/trade_analytics.py`. jarvis-trader already tracks PnL and profit factor; polymarket's settlement-finality approach complements but does not replace existing `TradeAnalytics` class. Brier Score calibration (predicted vs. actual outcome distribution) is novel pattern not present in jarvis-trader: applicable only if jarvis-trader integrates prediction-market hedging or adds probabilistic trade outcome tracking.

### 2. Project rules
`no-fit` — polymarket-toolkit contains no discipline rules, coding invariants, or safety patterns. Deployment is stateless (curl-based API calls); no operational risk vectors.

### 3. Project skills
`integrate-now` — Two skills are directly portable to `~/.claude/skills/polymarket-profile/` and `~/.claude/skills/polymarket-brier/`. Both are instruction-based (no code execution; API calls via curl + JSON parsing). Context: polymarket-toolkit skills rely on public APIs; jarvis-trader's existing skills (jarvis-trader, backtest-report, gstack) use internal APIs. Duplication risk is low — polymarket skills serve trader intelligence, not core trading logic.

### 4. Slash commands
`no-fit` — polymarket-toolkit provides no slash commands. Skills are designed for natural-language invocation (e.g., `/polymarket-profile 0x63ce3421...`), which is handled by the AI agent itself, not by a dedicated command file.

### 5. Subagents
`defer` — polymarket-profile auto-detects strategy (Market Maker, SPLIT arbitrage, Whale, Diversified) using heuristics: trade frequency, position concentration, category diversity. Concept is valuable for `safety-reviewer` (to flag market makers as low-signal) or a new `trader-intelligence` subagent. However, polymarket strategies (SPLIT arbitrage, liquidity provisioning) do not map to futures strategies (mean-reversion, trend-following, vol-of-vol). Defer until post-integration of equities or structured-products trading.

### 6. Docs
`integrate-now` — Polymarket strategy taxonomy (Market Maker, SPLIT Arbitrage, Diversified, Whale) and Brier Score interpretation (high Brier = poor calibration, low Brier = good prediction) belong in `docs/strategy/` or `docs/digest/` as reference material. Example: "When evaluating an external signal source, prioritize traders with Brier < 0.20 (80%+ accuracy) over high-PnL traders who may be market makers." Add to `docs/digest/signal-quality.md` or new `docs/strategy/prediction-market-intel.md`.

### 7. Dev tooling
`no-fit` — polymarket-toolkit has no CI/CD, hooks, PM2 config, or automation. It's a pure-skill repository.

### 8. Dashboard
`partial-integrate` — Polymarket profile widget (top wins/losses, category breakdown, strategy label) maps to existing `dashboard/components/PerformanceSummaryWidget.tsx`, `RegimePnLBreakdownWidget.tsx`, and `BestWorstTradesWidget.tsx`. Brier Score calibration table (confidence vs. forecast vs. actual) is a new chart type, similar to `BacktestMetricsWidget.tsx`. Effort: moderate (data source is Polymarket API, not SQLite trades). **Decision gate**: Add only if jarvis-trader introduces prediction-market hedging or acquires external-trader-signal monitoring capability.

### 9. Ops / messaging
`defer` — Whale alerts (large position changes from top traders) would map to `engine/schedulers/` + `engine/notifications/` (Discord/Telegram). Current scheduler is eod_scheduler.py (end-of-day); polymarket alerts would require intraday polling. Deferred until decision on whether polymarket monitoring is core or exploratory.

## Integration plan

**Immediate (integrate-now):**
1. Copy `skills/polymarket-profile/SKILL.md` and `skills/polymarket-brier/SKILL.md` to `~/.claude/skills/` (no adaptation needed; pure API-instruction skills).
2. Add reference section to `docs/digest/signal-quality.md` or new `docs/strategy/prediction-market-intel.md` explaining Brier Score, strategy taxonomy, and decision rules (e.g., "filter traders with Brier > 0.30").
3. Document in `.claude/commands/` as `/trader-intel <polymarket-address>` → calls polymarket-profile skill under the hood (optional, for quick access).

**Follow-up (partial-integrate, decision-gated):**
- If jarvis-trader adopts external-trader-signal sourcing: wire polymarket-profile into `engine/agents/safety-reviewer.md` to auto-flag market makers.
- If prediction-market hedging is approved: add Brier Score widget to dashboard (`dashboard/components/BrierScoreCalibrationWidget.tsx`).
- If intraday monitoring is approved: add whale-alert scheduler to `engine/schedulers/polymarket_whale_alert.py`.

**Not recommended:**
- Do not port polymarket-profile logic into `engine/analytics/`; it is a special case (settlement-final, not continuous P&L streams). Keep as external skill.

## License & attribution

**License**: MIT (same as polymarket-toolkit; no conflicts).

**Attribution**: Add to file header in any integrated skill:
```
Based on runesleo/polymarket-toolkit (https://github.com/runesleo/polymarket-toolkit)
Licensed under MIT. Author: Leo (https://x.com/runes_leo)
```

## Effort estimate

- **Integrate-now (skills + docs)**: S (< 2 hr). Copy skill files, add 1-2 reference docs.
- **Partial-integrate (dashboard widget)**: M (2–8 hr). Requires Polymarket API wrapper, data fetching, Tailwind/Recharts chart.
- **Deferred (subagent, scheduler)**: L (1–3 days). Requires decision on prediction-market monitoring scope.

**Total initial effort**: S. Can be shipped same week.

## Red flags

1. **Venue mismatch**: Polymarket trades binary outcomes (Yes/No settlement). jarvis-trader trades continuous futures (MES, MNQ, etc.). Strategy patterns do not transfer (SPLIT arbitrage ≠ mean reversion). Use only for signal sourcing or hedging, not as a strategy template.

2. **API rate limits**: Polymarket's public APIs (lb-api, data-api, gamma-api) have undocumented rate limits. Large account pagination (10K+ trades) may exceed limits. Test with prod accounts before deploying to scheduler.

3. **Settlement lag**: Polymarket markets can take days/weeks to resolve. Brier Score and Top Wins/Losses are post-hoc analysis, not live signals. Not suitable for real-time decision-making.

4. **Operator risk**: Polymarket is a CFTC-regulated platform; trading/signal sourcing compliance may be required. Ensure legal review before wiring polymarket trader profiles into trade approval flows.

5. **Archived risk**: Low (repo was pushed 2026-03-31, active). No unmaintained signal.

