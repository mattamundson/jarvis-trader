# Risk Attribution Runbook

> What drove yesterday's P&L? This module decomposes realized paper-trade P&L
> across pipeline analysts so every dollar of gain or loss has a name attached to it.

## What Is Attribution?

The JARVIS pipeline records each analyst's `signal` value in
`paper_trades.strategy_params["analyst_signals"]` at trade-entry time. These signals
are already in the range [-1, +1] — positive is bullish, negative is bearish.

The attribution engine uses **pro-rata decomposition**:

```
weight_i = signal_i / sum(|signal_j|)      # each analyst's fraction of total |signal| mass
attribution_i = trade_pnl * weight_i       # dollars attributed to analyst i
residual = trade_pnl - sum(attribution_i)  # P&L not explained by stored signals
```

Analysts currently tracked (matching `analyst_signals` keys):

| Slot | Source |
|------|--------|
| `technical` | TechnicalAnalystAgent (STC, EMA, VWAP) |
| `news` | NewsAnalystAgent (LLM news sentiment) |
| `social` | SocialAnalystAgent (StockTwits / Reddit) |
| `fundamental` | FundamentalistAgent |
| `corey` | CoreyAuctionAnalystAgent (Discord #market-updates) |
| `pattern_vision` | PatternVisionAnalyst (chart patterns) |
| `kronos` | KronosClassifier (time-of-day regime) |
| `options` | OptionsAnalyst (put/call flow) |
| `regime_adjust` | RegimeEngine adjustments |
| `other` | Any unrecognized analyst key |

## How to Interpret the Residual

The `residual` field captures P&L that cannot be cleanly attributed:

- **Trade has no stored verdict** — strategy_params is NULL or contains no `analyst_signals`
  (imported trades, test seeds, pre-pipeline trades all land here entirely)
- **All signals were zero** — pipeline ran but no analyst had conviction
- **Slippage / gap moves** — the actual fill price differed from the expected entry, and
  the weighted signal sum doesn't account for that drift
- **Late information** — the pipeline verdict was stale by the time the trade closed
  (e.g. overnight hold, MGC daily-bar strategy)

A large residual on a day with many trades usually means the trades pre-date pipeline
verdict recording (before the `analyst_signals` write was added). A small residual on
a day with recent pipeline trades is normal — it's floating-point rounding.

## Read-Only Invariant

This module **never writes to the database**. It opens SQLite in read mode and returns
Python dataclasses. No position sizing, no order routing, no kill-switch interaction.

The `ENABLE_RISK_ATTRIBUTION` flag in `engine/.env` is checked only by the vault cron
script (`scripts/write_attribution_to_vault.py`). The HTTP routes are **always active**
regardless of the flag.

## HTTP Endpoints

All routes require `X-API-Key` (same key as the rest of the engine API).

### Single-day

```
GET /attribution/daily?date=YYYY-MM-DD
```

Returns `DailyAttributionResponse` — attribution dict + residual for all closed trades
on that date. Defaults to today if `date` is omitted.

### Rolling window (JSON)

```
GET /attribution/window?days=30
```

Returns `WindowAttributionResponse` with `daily[]` array and `per_analyst` stats.

### Rolling window (Markdown — vault-ingestible)

```
GET /attribution/window?days=30&format=markdown
```

Returns `text/markdown` suitable for direct gbrain / Obsidian ingest.

## Vault Writeback (Cron)

Run at 6pm CT post-close to capture the day's final P&L:

```powershell
# PowerShell scheduled task (add to install-regression-tasks.ps1 or schtasks manually)
engine\.venv\Scripts\python scripts\write_attribution_to_vault.py --force
```

Weekly rollup (run Monday after market close, or at week-end):

```powershell
engine\.venv\Scripts\python scripts\write_attribution_to_vault.py --weekly --force
```

Output files land in:

```
master-jarvis/second-brain/raw/_session-attribution/daily-YYYY-MM-DD.md
master-jarvis/second-brain/raw/_session-attribution/weekly-YYYY-WW.md
```

Each file has frontmatter compatible with gbrain's `_session-attribution` ingest rule.
The `Jarvis-VaultGbrainSync` task (30-min cadence) will pick them up automatically.

## Dashboard Widget

`RiskAttributionPanel` on the `/jarvis` Stark page (column 2, below QuantStatsPanel):

- **Stacked bar chart** — per-analyst contribution per day for the last 30 days.
  Positive bars (profitable days) stack up; negative bars stack down. Color-coded
  by analyst slot.
- **Summary table** — mean/day, std, max single-day loss, win-rate-when-top for each
  non-zero analyst. "top" badge marks the window's dominant contributor.
- **Empty state** — displayed when no closed trades exist in the window.

## Methodological Concern

**Correlated signals get double-counted via cancellation, not double-inflation.**

The pro-rata formula normalizes by total |signal| mass. When two analysts both signal
bullish (e.g. `technical=0.5, news=0.5`), their joint influence sums to 100% of P&L —
correct. But when they are *correlated in their error* (both wrong on the same bad trade),
each analyst is debited proportionally, making neither look as bad as they truly are for
that trade in isolation.

More specifically: the formula assumes **linear independence of analyst contributions**.
In practice, the technical analyst and regime_adjust are structurally correlated (both
derive from STC / price action). If both signal bullish on an uptrend-continuation trade
that works, technical gets ~50% credit and regime_adjust gets ~50%. But the same signal
source drove both — the real independent contribution is smaller for each.

This doesn't invalidate the attribution but does mean: **do not interpret a high-residual
analyst as the sole cause of a loss**. Use attribution as a directional audit trail, not
a causal scorecard.

## Cross-References

- [[QUANTSTATS_TEARSHEET_RUNBOOK]] — tearsheet-level P&L stats (Sharpe, Sortino, drawdown)
- [[STARK_MODE_OPERATING_PHILOSOPHY]] — Stark page layout and update cadence
- `engine/analytics/risk_attribution.py` — attribution engine (read-only)
- `engine/routers/attribution_router.py` — HTTP routes
- `scripts/write_attribution_to_vault.py` — vault writeback cron script
- `dashboard/components/RiskAttributionPanel.tsx` — dashboard widget
