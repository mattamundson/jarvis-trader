# TradingView + Lightweight Charts review runbook

**Purpose:** the canonical playbook for discretionary chart review and Pine backtest report capture that feeds JARVIS journal entries and strategy reviews. Distilled from `tradingview-mcp` skills and `lightweight-charts` indicator examples — not a vendored dependency.

---

## Part A — TradingView MCP chart-analysis workflow

Source: `tradingview-mcp/skills/chart-analysis/SKILL.md`.

### 1. Set up the chart

1. `chart_set_symbol` — switch to the requested symbol.
2. `chart_set_timeframe` — set the appropriate timeframe for the question.
3. Wait for the chart to load.

### 2. Add indicators

Use `chart_manage_indicator` to add studies. **Use full indicator names** — short aliases are rejected:

| Short | Full name to pass |
|---|---|
| RSI | Relative Strength Index |
| EMA | Moving Average Exponential |
| SMA | Moving Average |
| MACD | MACD |
| Bollinger Bands | Bollinger Bands |
| Volume | Volume |
| VWAP | VWAP |
| ATR | Average True Range |

After adding, use `indicator_set_inputs` to customize (e.g. EMA length → 200).

### 3. Navigate to key areas

- `chart_scroll_to_date` — jump to a specific date of interest.
- `chart_set_visible_range` — zoom to a specific date window.
- `chart_get_visible_range` — check what's currently visible.

### 4. Annotate

- `draw_shape` with `horizontal_line` for support/resistance.
- `draw_shape` with `trend_line` for trend channels (needs two points).
- `draw_shape` with `text` for annotations.

### 5. Capture and analyze

1. `capture_screenshot` — screenshot the annotated chart.
2. `data_get_ohlcv` — pull recent price data for quantitative check.
3. `quote_get` — get the current real-time price.
4. `symbol_info` — get symbol metadata (exchange, type, session).

### 6. Report

Provide: current price and recent range; key support/resistance; indicator readings (RSI overbought/oversold, MACD crossover, etc.); overall bias (bullish/bearish/neutral) with reasoning.

### 7. Cleanup

If indicators or drawings were temporary, remove them: `chart_manage_indicator` action `remove` by entity_id, or `draw_clear` to remove all drawings.

---

## Part B — Strategy backtest report capture

Source: `tradingview-mcp/skills/strategy-report/SKILL.md`.

### 1. Gather data

1. `data_get_strategy_results` — overall metrics (net profit, win rate, profit factor, etc.).
2. `data_get_trades` — individual trade list (max 20).
3. `data_get_equity` — equity curve data points.
4. `chart_get_state` — current symbol, timeframe, studies on chart.
5. `symbol_info` — symbol metadata for context.

### 2. Capture visuals

- `capture_screenshot` with region `chart` — chart with strategy overlay.
- `capture_screenshot` with region `strategy_tester` — Strategy Tester panel.

### 3. Key metrics to report

- Net Profit and % return
- Total Trades and Win Rate
- Profit Factor (target > 1.5 per the strategy-report skill)
- Max Drawdown ($ and %)
- Average Trade ($ and %)
- Sharpe Ratio if available
- Max Consecutive Losses

### 4. Trade analysis

From the trade list:

- Largest winner and largest loser
- Average winner vs average loser (reward:risk)
- Long vs short performance breakdown
- Time in market

### 5. Equity curve assessment

- Is it smooth and upward-sloping?
- Any extended drawdown periods?
- Does it show consistency or was profit front/back-loaded?

### 6. Improvement suggestions (keyed to thresholds)

- Win rate < 50% but profit factor > 1: suggest tighter entries.
- Max drawdown > 20%: suggest position sizing or stop-loss adjustments.
- Profit factor < 1.2: suggest the strategy may need fundamental changes.
- Few trades: suggest widening the lookback or loosening entry criteria.

### 7. Report format

```
## Strategy Report: [Strategy Name]
**Symbol:** [symbol] | **Timeframe:** [tf] | **Period:** [date range]

### Summary
[1-2 sentence overview]

### Key Metrics
| Metric | Value |
|---|---|
| Net Profit | ... |
| Win Rate | ... |
| Profit Factor | ... |
| Max Drawdown | ... |

### Strengths
- [bullets]

### Weaknesses
- [bullets]

### Recommendations
- [specific actionable improvements]
```

---

## Part C — Lightweight Charts indicator inventory

Source: `lightweight-charts` indicator-examples tree. The library ships pluggable indicator examples; these are the candidates JARVIS' dashboard chart integration can make available:

- **average-price** — average price indicator + calculation.
- **correlation** — correlation between two series + calculation.
- **momentum** — momentum indicator + calculation.
- **moving-average** — simple/exponential moving average + calculation.
- **percent-change** — percent change indicator + calculation.
- **product** — product of two series + calculation.
- **ratio** — ratio of two series + calculation.
- **spread** — spread between two series + calculation.
- **sum** — sum of two series + calculation.
- **weighted-close** — weighted close indicator + calculation.

These are reference examples, not a JARVIS feature list — adopt only the indicators that map to existing strategy signals.

---

## JARVIS integration notes

- TradingView MCP is a discretionary review tool, not an automated signal source. Its chart captures and Pine backtest reports feed the trading journal and strategy reviews — they do not place trades.
- Lightweight Charts is the native dashboard charting library; the indicator inventory above is the reference for which overlays the dashboard should support for manual review.
- Any Pine script strategy that looks promising in review still goes through the backtest critique checklist (Part B's metrics feed that checklist's metric section) before it enters the strategy registry.
