# Macro / FRED Regime-Context Spec

**Status:** draft · **Owner:** strategy-research + data · **Audience:** strategy authors, data engineers, agent workflow authors  
**Purpose:** define how macro regime context enters JARVIS — as a **filter and feature**, never as a direct order trigger.

> This spec distills the `fredapi` Python API (Federal Reserve Economic Data / ALFRED) and the `claude-trading-skills` macro-regime-detector concept into a JARVIS-native contract. Macro context informs posture and features; it does not place trades.

---

## 1. Design principle

Macro data is a **regime filter and context feature**, not a signal generator and not an execution trigger.

- **Allowed:** include FRED series as features in a strategy, use them to compute a regime posture that gates risk allowance, surface them in a pre-trade brief.
- **Not allowed:** let a macro release directly place or cancel an order, mutate risk limits, or flip a kill-switch without passing through the same backtest → walk-forward → paper → safety-review pipeline as any other strategy component.

This matches the `claude-trading-skills` guidance: macro regime is one layer in a multi-layer stack, and execution stays manual or gated by the engine's existing risk layer.

---

## 2. Canonical FRED usage in JARVIS

### 2.1 What FRED is

`fredapi` is a Python client for the Federal Reserve Economic Data (FRED) and Archival FRED (ALFRED) services, operated by the St. Louis Fed. It retrieves series by ID, with point-in-time support via ALFRED for vintage data.

Key facts relevant to JARVIS:

- Free API key required; sign up at the St. Louis Fed FRED site.
- `fredapi` supports per-series requests with start/end dates, frequency, and observation count limits.
- ALFRED supports vintage queries for point-in-time integrity on series that have been revised.

### 2.2 What we use it for

- **Regime features:** rate differentials, yield-curve shape, inflation readings, unemployment, industrial production — as strategy features or regime filters.
- **Regime posture:** a coarse risk-on / risk-off / transitioning label that informs exposure allowance in the daily regime workflow.
- **Calendar awareness:** known release schedule and revision windows so the engine and reviewers know when a macro-driven feature may change.

### 2.3 What we do not use it for

- Direct order triggers.
- Live risk-limit changes without a strategy promotion gate.
- Any path that bypasses the JARVIS data provenance and backtest critique pipeline.

---

## 3. Data contract

Every macro feature used by a JARVIS strategy must carry the following provenance in the strategy record or data-layer metadata:

| Field | Meaning |
|---|---|
| `fred_series_id` | The FRED series ID (e.g. a Treasury yield, CPI, unemployment rate). |
| `source` | `"fred"` or `"alfred"` depending on whether live or vintage data is used. |
| `api_key_env` | The env var name used for the FRED API key (do not record the key). |
| `observation_start` / `observation_end` | The exact range used in the backtest or live feature. |
| `frequency` | The requested frequency after FRED aggregation, if any. |
| `vintage_date` | For ALFRED point-in-time fetches, the vintage date used. |
| `release_date` | The date the observation was first released by the source agency. Distinct from the observation date and the fetch date; this is the publication date of the data point. Required for any series where release timing affects the backtest or live decision. |
| `effective_date` | The date the observation is considered effective (policy-effective date for rate decisions, reference period for economic aggregates). Required when the effective date differs from the observation date, e.g. a monthly CPI released in mid-month covers the prior month. |
| `revision_note` | Any known revision behavior for the series (e.g. CPI revisions, payroll revisions). |
| `refresh cadence` | How often the feature is refreshed in live/paper (e.g. daily, on-release). |
| `freshness gate` | The max age of the latest observation before the feature is considered stale for a decision. |

---

## 4. Freshness and staleness

Macro features are only useful if they are current enough for the decision they inform.

- A regime posture used for a daily exposure decision must be computed from observations no older than the freshness gate defined for that series.
- If a feature is stale, the workflow must either skip the macro layer or mark the decision as macro-blind, depending on how critical the layer is to the strategy.
- The data layer must record the fetch timestamp alongside the observation date so reviewers can tell "data as of" from "observation date."

This is the same freshness-thinking already present in the JARVIS data watchdog and the `claude-trading-skills` market-calendar-dependency policy.

---

## 5. Regime posture model (lightweight)

A regime posture is a coarse label that summarizes macro context for a risk decision. It is not a forecast and not a trade signal.

Suggested minimal model:

1. Pick 2–4 macro features relevant to the strategy's asset class and horizon.
2. Define a simple rule for each feature: e.g. yield curve slope positive/negative, inflation above/below a threshold, unemployment trend up/flat/down.
3. Combine into a posture: `risk_on`, `risk_off`, `transitioning`, or `inconclusive`.
4. Use the posture as a **filter or context feature**, not as a standalone decision.

The posture must be documented in the strategy record, including the exact features, thresholds, and combination rule, so the same posture can be reconstructed from the data.

---

## 6. Integration points

### 6.1 Strategy registry

A macro-bearing strategy record includes:

- The list of FRED series used, with provenance fields from §3.
- The freshness gate for each series.
- The regime posture rule, if any, that the strategy applies.
- A note on whether the macro layer is a filter, a feature, or both.

### 6.2 Backtest critique

When a strategy uses macro features, the backtest critique checklist must verify:

- **No look-ahead on release dates or revisions.** The backtest must use each observation on or after its `release_date`, never before. A strategy that appears to use a macro value before it was publicly available fails the gate. This is the most common macro backtest defect and is checked explicitly.
- **Point-in-time integrity if ALFRED vintages are used.** When a vintage is queried, the `vintage_date`, `release_date`, and `effective_date` must all be recorded, and the backtest must use the value as it was known on the decision date, not the revised value.
- **That the freshness gate used in the backtest matches the intended live behavior.** If the live feature refreshes on release, the backtest must simulate that same release-schedule lag, not ingest the value on the observation date.
- **That the macro layer does not become the sole driver of the edge.** If removing the macro feature collapses the strategy's expectancy, the edge is macro-only and must be treated as a single-point-of-failure regime bet, not a diversified strategy.
- **That any series with known revisions is tested against both first-release and revised values** to confirm the edge is not an artifact of a specific vintage.

### 6.3 Agent workflows

If an agent workflow (Hermes skill, Claude skill, or engine agent command) surfaces macro context in a pre-trade brief:

- State the series, observation date, fetch timestamp, and freshness.
- State the posture or feature value and how it was derived.
- State any staleness or revision uncertainty.
- Do not present the macro read as a directive; present it as context.

### 6.4 Data layer

The data layer should treat FRED/ALFRED as one feed among several (Databento, IBKR, YFinance, CSV), with the same provenance, freshness, and adjustment columns. Do not let macro data have a special unchecked path.

---

## 7. API and secret handling

- The FRED API key lives in `engine/.env` (or the equivalent config for the environment) under a named env var; it is never committed.
- `fredapi`-style clients read the key from the environment, not from a hardcoded file path, so the same client can run in dev, paper, and any CI that supplies the key.
- If a macro feature is used in a public doc, example, or runbook, redact the key and use placeholder series IDs or a documented sample range.

---

## 8. Related

- Backtest critique checklist: `docs/research/backtest-critique-checklist.md`
- Strategy registry schema: `docs/research/strategy-registry-schema.md`
- Chart review runbook: `docs/research/chart-review-runbook.md`
- Source client: `fredapi` — https://github.com/mattamundson/fredapi (Python API for FRED/ALFRED)
- Source concept: `claude-trading-skills` macro-regime-detector and market-calendar-dependency policy
- JARVIS data watchdog and freshness gates (existing engine/docs)

---

*This spec is a distillation and extension, not a fork. `fredapi` remains the canonical client; this doc is the JARVIS contract for how macro context may be used.*
