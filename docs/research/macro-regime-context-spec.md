# FRED / macro regime-context spec

**Purpose:** define how JARVIS consumes FRED/macro data — as a regime filter and context feature only, never as a direct trade trigger. Distilled from `fredapi` (the Python FRED/ALFRED wrapper) and `sunday-quant-scientist` technique catalog, aligned with the audit's "Market data and macro context" guidance.

---

## 1. Role and boundary

- **Role:** macro/FRED data provides regime context and feature columns for strategy signals. It answers "what regime are we in?" and "is the macro backdrop consistent with this signal?"
- **Boundary:** macro data does **not** place trades directly. No FRED series triggers an order by itself. Any strategy that appears to trade on a macro series must decompose that into a tradable instrument signal (e.g. VIX level → MES trend filter, not "FRED VIXCLS crossed X → buy").
- **Freshness gate:** macro features used in a live signal must have a defined staleness threshold. If a series hasn't updated within its expected release cadence, the feature is treated as stale and the signal either falls back or is suppressed, depending on the strategy's risk posture.

---

## 2. Candidate FRED series for regime features

Derived from common macro-timing use cases; not an exhaustive or endorsed list — each must be validated against JARVIS' instruments before use:

| Series ID | Description | Regime use case |
|---|---|---|
| FEDFUNDS | Effective Federal Funds Rate | Monetary-policy regime / rate-direction context |
| CPIAUCSL | CPI All Items | Inflation regime |
| SP500 | S&P 500 (FRED) | Equity regime proxy (level, not a trade signal) |
| VIXCLS | CBOE Volatility Index | Volatility regime; directly relevant to MES/VIX strategies |
| T10Y2Y | 10Y-2Y Treasury spread | Yield-curve regime (inversion as recession proxy) |
| INDPRO | Industrial Production | Growth regime |
| PAYEMS | Nonfarm Payrolls | Labor-market regime (release-day noise caveat) |
| UMCSENT | U of Michigan Consumer Sentiment | Sentiment regime |

**Release cadence caveat:** series like PAYEMS and CPI are monthly with a known release calendar. A strategy that keys off them must handle the gap between "data release date" and "data is queryable" and must not treat a missing update as a regime change.

---

## 3. Data contract

- **Source:** `fredapi` (PyPI package) is the JARVIS FRED adapter — do not vendor the library. Install as a dependency; wrap it in a small internal client that normalizes the response into JARVIS' bar/event schema with provenance columns.
- **Provenance columns:** every macro feature row carries `series_id`, `observation_date`, `release_date` (when available from ALFRED), `freshness_seen_at`, and `source` = "FRED".
- **Archival / revisions:** ALFRED provides vintaged revisions. If a strategy uses vintaged data for backtesting, that must be stated explicitly — otherwise use the latest observation and do not claim "as-of-release" realism.
- **Error handling:** FRED API errors / rate limits must not crash the engine. A failed macro fetch degrades to "macro feature unavailable" for that cycle, not " engine error."

---

## 4. Backtest realism

- **Point-in-time rule:** backtests using FRED data must use the observation as it was known at decision time, not the revised latest value, if the strategy claims realism. `fredapi` + ALFRED vintaged queries enable this; using `latest` observation for a historical backtest is a look-ahead risk.
- **Release-day gap:** a macro series observed on its release date may not be available at the same intraday moment a futures signal fires. State the assumed availability time (e.g. "CPI used from day+1 open") or the backtest overstates realism.
- **Cost model note:** macro context features do not carry a separate execution cost, but any strategy whose edge depends on a macro series must still pass the backtest critique checklist's execution-realism leg.

---

## 5. What NOT to do

- Do not let a macro threshold place a trade without an instrument-level signal.
- Do not use macro series as the sole edge for a live futures strategy without a documented regime-stability test.
- Do not backtest a macro-driven strategy using revised data and claim point-in-time realism.
- Do not let a missing FRED API key or rate limit silence the engine — degrade gracefully.

---

## 6. Relationship to other docs

- Complements `strategy-research-operating-model.md` (the idea → data → backtest → walk-forward → paper → promotion pipeline; macro features are part of the "data" step).
- Feeds the `backtest-critique-checklist.md` regime-split section (a macro-aware strategy must show regime splits).
- The `mes_sma_trend_vix_pctile` strategy already uses VIX percentile as a feature; this spec is the boundary document for expanding macro context beyond VIX without introducing direct macro-trading.
