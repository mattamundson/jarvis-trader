# JARVIS Strategy Registry Schema

**Status:** draft · **Owner:** strategy-research · **Review cadence:** per-strategy promotion gate  
**Purpose:** one record per strategy idea, from hypothesis through paper shadow to live promotion (or closure). The registry is the system of record for what we are testing, what we have tested, and what verdict it earned.

> This schema distills the strategy-research operating model already started in `docs/research/strategy-research-operating-model.md` and the `claude-trading-skills` workflow/verification discipline into a concrete record format. It is a YAML-first contract; a relational or SQLite layer may sit on top later, but every strategy must have a readable record.

---

## 1. What the registry is for

The strategy registry answers:

- What is this strategy trying to exploit?
- What data, instruments, and parameters does it use?
- What tests has it passed (or failed)?
- What is its current promotion state?
- What would make us stop using it?

Every strategy that enters the JARVIS research loop gets a record. Records are versioned alongside the repo so the history of a strategy's assessment is auditable.

---

## 2. Record fields

### 2.1 Identity

| Field | Required | Meaning |
|---|---|---|
| `strategy_id` | Yes | Stable slug, e.g. `mes-momentum-MST_15-30`. Used in filenames, artifact references, and the dashboardif exposed. |
| `name` | Yes | Human-readable name. |
| `owner` | Yes | Person or team accountable for the strategy record and its promotion decisions. |
| `created_date` | Yes | When the record was first created. |
| `updated_date` | Yes | When the record was last meaningfully updated. |
| `source_notes` | No | Where the idea came from (internal research, imported repo, external reference). Include provenance for imported ideas per the Wave 1 import policy. |

### 2.2 Hypothesis

| Field | Required | Meaning |
|---|---|---|
| `hypothesis` | Yes | One or two sentences: what inefficiency or pattern this strategy exploits, and why we think it persists. |
| `kill_criterion` | Yes | What would make this strategy wrong. Explicit, testable where possible. From the `claude-trading-skills` quant-strategy-framework kill rule: no strategy enters paper without a written thesis and a kill criterion. |
| `asset_class` | Yes | The asset class or product surface (e.g. MES, NQ, metal futures, prediction markets). |
| `instruments` | Yes | Specific instruments or universe definition the strategy applies to. |
| `horizon` | Yes | Expected hold horizon or decision cadence (e.g. intraday, swing 1–5 days, position weeks). |

### 2.3 Data

| Field | Required | Meaning |
|---|---|---|
| `data_sources` | Yes | List of data feeds used (Databento, IBKR, YFinance, CSV, FRED/ALFRED, etc.), with provenance per the macro-regime-context-spec contract where applicable. |
| `features` | Yes | List of features/signals used, with a note on any that depend on macro or regime context. |
| `bar_frequency` | Yes | The bar or event frequency the strategy is designed around. |
| `data_contract_version` | No | If the strategy depends on a specific data-layer contract version, record it. |

### 2.4 Parameters

| Field | Required | Meaning |
|---|---|---|
| `parameter_set` | Yes | The parameter set tested, with ranges and the selected values. |
| `parameter_count` | Yes | Number of freely tuned parameters — used by the backtest critique checklist's over-optimization scan (7+ is critical). |
| `parameter_stability` | No | Notes on whether performance is stable across a range or spikes at a point. |

### 2.5 Testing

| Field | Required | Meaning |
|---|---|---|
| `backtest_window` | Yes | In-sample test window (start/end, regimes covered). |
| `oos_window` | No | Out-of-sample or walk-forward window, if any. |
| `trade_count` | Yes | Total trades in the test window(s). Used by the backtest critique sample-size dimension. |
| `backtest_critique_ref` | No | Pointer to the completed backtest critique artifact (JSON + MD) per `docs/research/backtest-critique-checklist.md`. Required before walk-forward or paper. |
| `backtest_verdict` | No | Deploy / Refine / Abandon from the critique. |
| `walkforward_ref` | No | Pointer to walk-forward artifacts, if run. |
| `walkforward_verdict` | No | Verdict from the walk-forward phase. |

### 2.6 Paper shadow

| Field | Required | Meaning |
|---|---|---|
| `paper_start_date` | No | When paper shadow began. |
| `paper_status` | No | Running / completed / stopped. |
| `paper_min_duration_met` | No | Whether the minimum paper-shadow duration (20 trading days or 1 full volatility regime cycle, whichever is longer) has been met. |
| `paper_result_ref` | No | Pointer to paper-shadow result artifacts. |

### 2.7 Promotion state

| Field | Required | Meaning |
|---|---|---|
| `promotion_state` | Yes | One of: `hypothesis`, `backtesting`, `walkforward`, `paper`, `live`, `closed`. The promotion gate moves the record between these states; it does not skip them. |
| `live_start_date` | No | When the strategy entered live promotion, if applicable. |
| `live_status` | No | Live status if `promotion_state` is `live`. |

### 2.8 Closure

| Field | Required | Meaning |
|---|---|---|
| `closure_reason` | No | Why the strategy was closed, if `promotion_state` is `closed`. Capture lessons for `second-brain`. |
| `closure_date` | No | When the record was closed. |

### 2.9 Observability

| Field | Required | Meaning |
|---|---|---|
| `probes` | No | Which Sentinel/observability probes in `docs/research/sentinel-observability-runbook.md` apply to this strategy while it is in paper or live. |
| `freshness_gates` | No | Data freshness gates that apply to this strategy's feeds while live. |

---

## 3. Promotion gate rules

A strategy record advances only when the gate for the next state is satisfied:

1. **`hypothesis` → `backtesting`:** hypothesis, kill criterion, asset class, instruments, data sources, and parameter set are documented.
2. **`backtesting` → `walkforward`:** a completed backtest critique with a **Deploy** verdict is attached, and the critique's JARVIS-specific gates pass (data provenance, point-in-time integrity, execution model coherence, circuit-breaker coherence, kill criterion written, no live config mutation). A **Refine** verdict keeps the record in `backtesting` and requires fixes and a backtest rerun before any further advancement.
3. **`walkforward` → `paper`:** walk-forward verdict supports entry, and the strategy record's paper-shadow section is initialized.
4. **`paper` → `live`:** paper minimum duration is met, paper result is documented, and a fresh safety review has signed off on the live path. The registry record's `promotion_state` may move to `promoted` only when `gate_verdict.verdict == "PASS"` and `evidence_paths` includes the gate card and a PR or decision-ledger reference. A registry entry never authorizes routing by itself — live trading eligibility is read from `GET /paper/validation/approved-paper-gates` (dashboard `/trading-eligibility`). No live config, risk limit, kill-switch, broker routing, or API key change happens without that review.
5. **Any state → `closed`:** strategy is stopped or retired; closure reason and date are recorded; lessons are filed.

---

## 4. File layout

One record per file, named `<strategy_id>.yml`, under `docs/research/strategy-registry/`. Example:

```
docs/research/strategy-registry/
  MES-momentum-MST_15-30.yml
  backtest-critique-MES-momentum-MST_15-30-2026-10-01.json
  backtest-critique-MES-momentum-MST_15-30-2026-10-01.md
```

Records are plain YAML, readable without tooling. A helper script may validate required fields and promote-state consistency, but the source of truth is the file.

> **Note:** This YAML layout is the human-readable strategy record format. For the machine-readable, schema-validated JSON registry (with JSON Schema validation, seed entries, and programmatic discovery), see `docs/research/strategy-registry/` (README.md + schema.json). The YAML records in this directory and the JSON entries in `strategy-registry/entries/` serve different purposes: YAML for the research narrative, JSON for the validated ledger that existing registry tooling discovers.

---

## 5. Imported and referenced strategies

If a strategy idea is imported from an external repo (e.g. a notebook from `jarvis-quant`, a workflow from `claude-trading-skills`, a pattern from `Vibe-Trading` or `TradingAgents`), the record's `source_notes` must name the source repo, the specific file or skill, and the date of import. This is the same provenance discipline as the Wave 1 import README.

Imported ideas do not get a free pass into paper. They go through `hypothesis` → `backtesting` → etc. like any internal idea.

---

## 6. Related

- Backtest critique checklist: `docs/research/backtest-critique-checklist.md`
- Macro/FRED regime-context spec: `docs/research/macro-regime-context-spec.md`
- Chart review runbook: `docs/research/chart-review-runbook.md`
- Sentinel/observability runbook: `docs/research/sentinel-observability-runbook.md`
- Strategy research operating model: `docs/research/strategy-research-operating-model.md`
- Wave 1 import provenance: `docs/research/imported-repos/2026-09-12-wave1/README.md`
- Source discipline: `claude-trading-skills` workflow manifests and verification fields (skills-index.yaml pattern)

---

*This schema is a JARVIS-native contract. It draws on the workflow/verification discipline in `claude-trading-skills` and the strategy-research operating model already in this repo, but it is not a copy of either.*
