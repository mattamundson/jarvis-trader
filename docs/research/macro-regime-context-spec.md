# Macro/regime context spec

Purpose: use macro data as context and regime features without contaminating execution logic.

## Candidate sources

- FRED/ALFRED through `fredapi` or direct API.
- Economic calendars.
- Volatility/rates/credit/inflation/liquidity series.
- Internal market breadth and futures curve features.

## Required data contract

Each macro series needs:

- series ID and provider,
- vintage/revision policy,
- release timestamp and effective timestamp,
- update frequency,
- freshness threshold,
- transformation policy,
- missing-data behavior,
- units,
- timezone/calendar semantics,
- provenance path.

## Safe usage

Allowed:

- market brief context,
- regime labels,
- backtest feature inputs with correct release lag,
- dashboard explanatory badges,
- risk review context.

Not allowed:

- bypassing strategy promotion gates,
- changing live position size without explicit risk review,
- using revised future data in historical tests,
- treating stale macro values as current.

## Initial feature candidates

- VIX percentile / volatility regime.
- 10Y/2Y rates and curve change.
- Dollar index proxy.
- Real yields / inflation expectations.
- Credit spread proxy.
- Economic-release day flags.
- FOMC/CPI/NFP event windows.

## Acceptance test idea

A macro feature builder should be testable with a tiny fixture proving that values are only visible after their release timestamp, not at the period they describe.
