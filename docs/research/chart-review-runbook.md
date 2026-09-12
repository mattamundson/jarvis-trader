# Chart review runbook

Purpose: make discretionary chart review useful to JARVIS without letting visual judgment bypass deterministic gates.

## Tool roles

- **TradingView MCP:** capture external chart state, Pine snippets, replay/session notes, and discretionary annotations.
- **Lightweight Charts:** render native JARVIS dashboard panels with exact engine data, trade markers, signals, and regime overlays.
- **Second-brain/journal:** stores the chart interpretation, not just screenshots.

## Evidence package

Every chart review should capture:

- Symbol, venue, contract/month if futures.
- Timeframe and session template.
- Data source and timestamp of capture.
- Indicator settings.
- Marked levels: prior high/low, value area, VWAP, opening range, volatility bands, stops/targets if relevant.
- Setup classification.
- Invalidation level.
- What would falsify the setup.
- Screenshot or chart artifact path.
- Link to backtest/paper evidence if the setup maps to a strategy.

## JARVIS integration rule

Chart review may create:

- a strategy hypothesis,
- a journal note,
- a manual watchlist item,
- a candidate for backtest,
- a post-trade explanation.

Chart review may **not** directly authorize live/paper execution or override risk gates.

## Dashboard target

Add/maintain a review surface that shows:

- engine bars/price source,
- active strategy overlays,
- open/paper positions,
- order/trade markers,
- regime/context badges,
- evidence links.
