# LLM Decision-Identity Attribution — Design Spec

Status: **PROPOSED** (spec only; no implementation in this PR)
Author: Claude (Opus 4.8) for Amo
Related: `engine/backtest/forward_test.py`, `engine/backtest/candidate_registry.py`,
`engine/backtest/family_fdr.py`, `engine/agents/pipeline.py`,
`engine/scheduler/pipeline_autonomous.py`

---

## 1. Problem

The forward-test spine (registry → loop → graduation) validates **mechanical**
strategies (`MGC_trend_rv_filter_rank1`: 50/120 EMA + RV + ATR). But live trades
are **not** produced by those rules. The live autonomous pipeline decides via an
**LLM/agent conviction process** — `agents/pipeline.py::analyze_and_decide` →
analyst reports → bull/bear debate → trader → risk → fund manager → a confidence
gate (`scheduler/pipeline_autonomous.py`).

Consequence: a mechanical candidate can only graduate if it is what trades, and
it isn't. The honest funnel has **no pipe to the live engine** — every live trade
sits in "symbol-level context" and nothing can ever graduate. We are validating
an artifact (the backtest strategy) that is not the product (the LLM trader).

**Goal:** validate the thing that actually trades. Make the *LLM decision
configuration* the unit of attribution and graduation — with the same gate-v2
rigor and multiple-testing discipline that protects the mechanical path.

## 2. Core concept: the Decision Identity

A **Decision Identity** is a deterministic fingerprint of *the configuration that
produced a trade decision* — everything that, if changed, could change what the
pipeline decides. Two trades share a Decision Identity iff they were produced by
the same decision process. That identity is what accumulates a forward record and
what graduates (or doesn't).

This is the LLM analogue of a registry candidate's `params`. For a mechanical
strategy the params ARE the identity (`fast=50, slow=120, ...`). For the LLM
pipeline, the identity is the **config fingerprint** defined below.

### 2.1 What the fingerprint must cover

Anything that changes decisions and is not already part of market input:

| Class | Concrete fields (from the live pipeline) |
|---|---|
| **Pipeline code** | `PIPELINE_VERSION` (new constant) + git short SHA |
| **Models** | `ANALYST_MODEL`, `TRADER_MODEL`, `FAST_MODEL` (`config.py:457`), the `model_router` task→model map |
| **Prompts** | per-agent system-prompt SHA-256 (trader/fund/risk/analysts) — prompts are hardcoded and unversioned today |
| **Active analysts** | the set actually run (`technical, news, social, fundamental, corey, breakout, harmonic, kronos?, options?, vision?`) — gated by `ENABLE_KRONOS`, `ENABLE_OPTIONS_ANALYST`, playwright presence |
| **Gates / thresholds** | `FUTURES_MIN_CONFIDENCE_TO_TRADE`, `FUTURES_CONFIDENCE_BOOST`, `AUTONOMOUS_CONFIDENCE_THRESHOLD`, `STC_*`, `MTF_FILTER_ENABLED` |
| **Sizing / risk shape** | `_SYMBOL_ATR_PARAMS` (trader), `MAX_CONTRACTS_PER_INSTRUMENT`, paper-vs-live prompt swap (`PAPER_TRADING`) |

### 2.2 Two-level identity (the key design choice)

A single exact hash is too brittle — flip one flag and every trade's identity
changes, resetting the forward record forever. So split into two levels:

- **`config_hash` (exact):** SHA-256 over the full canonical config snapshot
  (§2.1). Changes on *any* config change. Used for exact reproducibility and
  drift detection.
- **`decision_lineage` (semantic family):** a human-assigned, registered label
  for "the same strategy intent" — e.g. `llm_core_v2`. A lineage spans a set of
  `config_hash`es that the operator asserts are *the same edge hypothesis*
  (e.g. a prompt typo fix, or a Sonnet point-release, does **not** create a new
  edge). **Graduation is evaluated per lineage**, not per exact hash.

The registry (§4) is what maps `config_hash` → `decision_lineage` and declares
which lineage is live. This is the deliberate, eyes-open control surface: the
operator decides which config changes are "material" (new lineage, record resets)
vs "immaterial" (same lineage, record continues). The system **defaults to
material** — an unrecognized `config_hash` is its own singleton lineage until the
operator explicitly folds it into an existing one. Fail-closed: never silently
merge an unknown config into a graduating lineage.

## 3. What to persist per trade

Today `open_trade` stores `strategy_params = {notes, rv_at_entry, analyst_signals}`
and the approval queue stores the full `verdict_json`. Add the identity:

```
strategy_params["decision_identity"] = {
    "config_hash": "<sha256[:16]>",
    "pipeline_version": "<PIPELINE_VERSION>",
    "git_sha": "<short>",
    "models": {"analyst": "...", "trader": "...", "fast": "..."},
    "active_analysts": ["technical", "news", ...],
    "gates": {"min_conf": 0.55, "boost": 0.05, "autonomous_thresh": 0.65},
    "prompt_hashes": {"trader": "<sha>", "fund": "<sha>", ...},
    "lineage": "<resolved from registry, or config_hash if unregistered>"
}
```

This is computed **once** in `analyze_and_decide` (a `pipeline_config` block on the
result) and threaded to `open_trade` via the existing `candidate_id` hook —
renamed/extended to a generic `attribution` payload, or a sibling
`decision_identity` kwarg. The fill-mirror passes whatever the decision attached.

Because the full `verdict_json` is already persisted in the approval queue, the
fingerprint is **auditable**: you can always recompute `config_hash` from the
stored snapshot and confirm a trade's claimed identity.

## 4. Registry model (decision-identity registry)

A new `engine/backtest/decision_registry.json`, parallel to
`candidate_registry.json`, pre-registers **decision lineages** (not mechanical
params). Same anti-multiple-testing methodology:

```json
{
  "schema_version": 1,
  "graduation_rule": { "min_forward_oos_windows": 6, "min_forward_pf_ci_lower": 1.10,
                       "min_forward_p_edge": 0.95, "must_survive_family_fdr": true, "q": 0.10 },
  "lineages": [
    {
      "id": "llm_core_v2",
      "status": "forward_testing",
      "deployed_live": true,
      "hypothesis": "The 13-analyst + bull/bear debate + fund-manager pipeline on Sonnet-4.6 carries positive OOS expectancy on MES/MGC futures at the 0.55 confidence gate.",
      "member_config_hashes": ["a1b2c3...", "d4e5f6..."],
      "material_change_policy": "model major version, analyst add/remove, gate move >0.05, or any prompt-intent change => NEW lineage; typo/point-release => same lineage (append config_hash here).",
      "registered_at": "2026-06-15"
    }
  ]
}
```

Mirrors the mechanical registry's helpers:
`load_registry`, `get_active_lineages`, `lineage_for_config_hash(hash)`,
`live_lineage()`, `meets_graduation(forward_stats)`.

`lineage_for_config_hash` is the heart of the honesty model:
- hash ∈ a registered lineage's `member_config_hashes` → that lineage.
- hash unknown → **its own singleton lineage** (`unregistered:<hash[:8]>`),
  status implicitly `forward_testing`, never `deployed_live`. It accrues its own
  record but cannot borrow another lineage's history. The operator must
  explicitly append it to fold it in.

## 5. Forward-test attribution & graduation (adapted)

`forward_test.py` already computes per-group OOS windows, bootstrap PF-CI,
binomial p_edge, and family-wide BH-FDR. The adaptation is mechanical:

- **Group key** becomes `decision_identity.lineage` instead of mechanical
  `candidate_id`/params.
- `attribution_level(trade, lineage)` → `lineage` (precise, can graduate) when
  the trade's `decision_identity.lineage` matches; else symbol-level context.
- **Family-FDR family** = the set of registered lineages evaluated together (so
  testing 5 pipeline variants applies the same multiple-testing correction the
  mechanical campaign uses — see `family_fdr.py`).
- Graduation rule is unchanged (6+ independent OOS windows, PF-CI ≥ 1.10,
  p_edge ≥ 0.95, survives FDR). Graduation is necessary-not-sufficient; gate-v2
  routing still governs sizing.

The existing `/analytics/forward-test` endpoint and the cockpit `ForwardTestPanel`
work unchanged — they just render lineages instead of mechanical candidates.

## 6. The honesty core — three LLM-specific traps

This is where an LLM attribution model is *harder* than a mechanical one, and
where the design earns its keep.

### 6.1 Config drift (silent edge laundering)
Every prompt tweak / model bump / flag flip changes `config_hash`. Without the
lineage layer, the operator could quietly improve the pipeline and inherit the
old record — laundering a fresh, unvalidated config into a "graduated" status.
**Mitigation:** graduation is per-lineage; folding a new `config_hash` into an
existing lineage is an explicit, logged registry edit governed by the lineage's
`material_change_policy`. A material change **must** start a new lineage with a
zero forward record. The forward-test report surfaces, per lineage, the list of
member hashes and the count of trades **per hash** — so a lineage that is 90% one
hash and 10% a just-added hash is visible, not hidden.

### 6.2 Non-determinism (same config, different output)
LLMs are stochastic; identical config + identical bars can yield different
decisions. This is **acceptable and correct** for attribution: the identity is
the *configuration*, not the output. Edge is defined over the distribution of
outcomes a config produces. Recommend logging `temperature`/sampling settings in
the fingerprint (so a temperature change is a material change), and otherwise
treating run-to-run variance as part of the strategy's variance — which is
exactly what PF-CI and the binomial p_edge already price in.

### 6.3 Multiple testing across variants (the big one)
The LLM solution space is unbounded — you can spin up infinite pipeline variants
and cherry-pick the one that looked good last month. This is the same disease
`family_fdr.py` was built for, now more dangerous because variants are cheap.
**Mitigation:** (a) lineages must be **pre-registered** before their forward
window is counted (dated entry + hypothesis, like the mechanical registry);
(b) all live/recent lineages form one FDR family with q = 0.10; (c) the report
logs the total number of lineages ever registered (the real `n_trials` for DSR),
so a graduation that only survives because 1-of-1 was tested is distinguishable
from 1-of-20.

## 7. Implementation phases (no code in this PR)

| Phase | Change | Files | Risk |
|---|---|---|---|
| **P1 — fingerprint** | add `PIPELINE_VERSION`; compute a `pipeline_config` snapshot + `config_hash` in `analyze_and_decide`; per-agent `prompt_hash`/`model_used` | `agents/pipeline.py`, agent classes, `config.py` | low (additive to result dict) |
| **P2 — persist** | thread `decision_identity` to `open_trade` (generalize the `candidate_id` hook); store in `strategy_params`; persist `config_hash` on the approval-queue row | `scheduler/pipeline_autonomous.py`, `portfolio/tracker.py`, `execution/paper_trade_logger.py` | low (tag-only, fail-open — same pattern as #59) |
| **P3 — registry** | `decision_registry.json` + `decision_registry.py` (load/resolve/live/graduation) | new files | none (pure data + reads) |
| **P4 — attribution** | generalize `forward_test.py` group key to lineage; FDR family = registered lineages | `backtest/forward_test.py` | low (read-only analytics) |
| **P5 — surface** | cockpit panel + `/analytics/forward-test` render lineages; show per-hash trade counts & drift | dashboard, analytics router | low (read-only) |

P1–P2 are the only changes that touch the live decision/entry path, and both are
strictly additive (compute + tag), never altering `final_action`. Same fail-open
discipline as PR #59.

## 8. Open decisions for Amo

1. **Lineage granularity.** Is "the whole pipeline on Sonnet-4.6" one lineage, or
   do you want per-symbol lineages (MES vs MGC may behave differently)? Recommend
   **per (lineage × symbol)** for the forward record, single registered lineage
   for the config — mirrors how the mechanical registry is per-symbol.
2. **Material-change policy.** Who owns the call that a prompt edit is
   material? Recommend: **default material** (new lineage), operator explicitly
   folds in immaterial changes. Conservative = honest.
3. **Prompt hashing scope.** Hash only the system prompts, or also the few-shot
   examples / tool definitions? Recommend system prompts + tool list (the parts
   that steer decisions), not transient context.
4. **Backfill.** The full `verdict_json` is already stored per historical trade —
   we *can* retro-compute `config_hash` for past trades from those snapshots and
   seed forward records. Worth doing, or start the clock fresh at P2 deploy?
5. **DSR n_trials source.** Count registered lineages, or all `config_hash`es ever
   seen? Recommend registered lineages (the things you chose to test), with the
   total-hashes count logged as a drift signal.

## 9. Why this is the right unit

You are running an **LLM trader**, not a mechanical one. Validating the mechanical
backtest strategy answers "would this rule have an edge?" — a research question.
Validating the decision identity answers "does the system I actually run have an
edge, and which configuration of it?" — the product question, and the only one
whose answer protects real money. The mechanical registry stays useful as a
research feeder; this makes the *live engine itself* the thing that graduates.
