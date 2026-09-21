# Macro / FRED regime-context spec

**Status:** draft · **Owner:** JARVIS research · **Related:** `docs/research/strategy-registry.md`, `docs/research/backtest-critique-checklist.md`

A spec for using FRED/macroeconomic data as a **regime filter and context feature** in JARVIS — never as a direct trade-placement signal.

Inspired by `mattamundson/fredapi` (point-in-time / vintage / ALFRED revisions handling) and `mattamundson/claude-trading-skills/skills/macro-regime-detector`.

## Core principle

Macro data informs **context**: is the current regime consistent with the regime a strategy was validated in? Macro data does **not** place trades on its own. Any strategy whose live execution depends on a macro signal must encode that signal as a feature in a strategy record that has passed the promotion gate.

## Data source

- Primary: FRED (Federal Reserve Economic Data) via `fredapi` or the FRED REST API.
- API key: `FRED_API_KEY` env var; never hardcoded. Treat as a secret — stored in the envsecret manager, not in repo files.
- Free tier has rate limits; cache aggressively and refresh on a calendar/freshness schedule, not per-trade.

## Point-in-time discipline (the hard part)

FRED series are revised. A value published on one date is often later revised. For backtests and regime classification, use the value **as known at that point in time**, not the latest revised value.

`fredapi` supports this via ALFRED vintage queries:

- `get_series(... realtime_start=..., realtime_end=...)` — restrict to observations valid in a given window.
- `get_series_first_release(...)` — the first published value for each observation, ignoring later revisions.
- Vintage date = the date the observation was valid; using unfiltered latest values in a backtest is look-ahead leakage.

JARVIS rule: any macro feature used in a backtest must be reproducible with a point-in-time query. If a backtest used the latest revised value where a vintage value was appropriate, that's a data-leakage flag in the backtest critique.

## Freshness and calendar gates

- Each macro series used in JARVIS gets a freshness record: last refresh timestamp, next expected release/calendar event, and stale threshold.
- A regime-context feature that depends on stale data must flag itself stale rather than silently using outdated values.
- Release calendar awareness: know when a series is expected to update; a "no change because no new release" is different from "no change because data genuinely stable."

## Recommended regime-context features (examples, not mandates)

- **Rate regime:** direction and level of a policy-rate proxy (e.g. FEDFUNDS or a treasury series), used as a filter/context, not a trade signal by itself.
- **Inflation regime:** CPI/PCE trend as context for whether a strategy historically performed in rising/falling inflation environments.
- **Volatility regime:** VIX-family or realized-vol context to test whether a strategy's backtest regime matches current conditions.
- **Liquidity/credit context:** credit-spread or liquidity proxies as situational context.

Each feature in the strategy registry's `features` list that is macro-sourced should reference the FRED series ID and the point-in-time handling used.

## Integration boundaries

- **Regime filter:** a strategy may include a macro regime condition in its hypothesis (e.g. "validated only in rate-rising regime"). The live gate checks regime consistency and can suppress or flag execution when regime has drifted.
- **Not a signal generator:** no macro series directly generates an order. If someone wants a macro-driven strategy, it must be a proper strategy record with hypothesis, backtest, walk-forward, and paper shadow.
- **Backtest requirement:** a strategy whose hypothesis references a macro regime must backtest with point-in-time macro data and include a regime-split report.

## Secrets

- `FRED_API_KEY` is a secret. It lives in envsecret, not in repo files, not in `.env` committed to git.
- Any macro data pipeline that caches series locally must not commit the cache if it contains API keys or freshly-downloaded data that shouldn't be public.

## Source notes

Distilled from `mattamundson/fredapi/README.md` (FRED/ALFRED Python API, point-in-time and first-release concepts, pandas integration) and `mattamundson/claude-trading-skills/skills/macro-regime-detector/SKILL.md` (macro regime concept and data inventory). Not vendored.
