---
repo: mnemox-ai/tradememory-protocol
url: https://github.com/mnemox-ai/tradememory-protocol
stars: 1300
language: Python
license: MIT
archived: false
pushed_at: 2026-03-27
analyzed_at: 2026-06-18
recommendation: partial-integrate
surfaces_with_value: [engine, docs, dev-tooling]
---

# mnemox-ai/tradememory-protocol

## Core value proposition
An MCP server (~17 tools, 35+ REST endpoints) that gives AI trading agents persistent,
queryable memory of every decision made or rejected, plus a tamper-evident audit chain
(per-record SHA-256 + daily Merkle root). Its differentiator over a plain pattern DB is
two-fold: (1) Outcome-Weighted Memory (OWM) recall that ranks past trades by outcome
quality, context similarity, recency, confidence, and "emotional state"; and (2) a
regulatory-compliance framing (MiFID II Art. 17, EU AI Act Arts. 12/14) built on the
hash chain. It is broker-agnostic and never executes trades or touches API keys — pure
memory/audit layer.

## How it maps onto jarvis-trader
jarvis-trader already ships a working learning/memory subsystem. The honest read is ~70%
conceptual overlap with code we already have, one genuinely novel axis (the cryptographic
audit chain), and one weakly-novel axis (multi-dimensional recall weighting).

| tradememory-protocol concept | jarvis-trader equivalent | Verdict |
|---|---|---|
| `remember_trade` / episodic trade records | `engine/learning/feedback.py` + `paper_trades` table | dedup |
| `recall_memories` pre-trade context | `engine/learning/recommendations.py` (injects into Stage-1 TechnicalAnalyst) | dedup |
| Pattern extraction / semantic layer | `engine/learning/patterns.py` + `consolidator.py` + `pattern_db.py` | dedup |
| OWM recency weighting | `recommendations.py` already does exponential temporal decay (verified: 24 decay/win_rate refs) | dedup |
| OWM context-similarity + confidence axes | No equivalent — our recall sorts by win_rate × decay only | partial-integrate (idea) |
| `check_trade_legitimacy` risk gate | `engine/risk/safety_layer.py` (hardcoded) | dedup — do not touch |
| SHA-256 per-record + daily Merkle root | `engine/approval/snapshot.py` + `pipeline_history.py` persist snapshots but with **no hashing** (verified: 0 sha256/hashlib/merkle refs) | partial-integrate (genuinely novel) |
| `get_strategy_performance` / `validate_strategy` | `engine/analytics/performance.py`, `validation_metrics.py`, WFE gate v2 | dedup |
| `evolution_*` (discover/backtest/evolve) | `engine/backtest/*`, `engine/learning/freqai_kitchen.py`, `promotion.py` | dedup |

## Surface analysis

### 1. Engine code
partial-integrate — Two ideas worth lifting; the rest is dedup. (a) **Audit-chain**: our
`engine/approval/snapshot.py` and `pipeline_history.py` already serialize every pipeline
decision to SQLite but as plain JSON with no integrity guarantee (verified: zero
hashing). Adding a per-record SHA-256 over the canonical snapshot plus a `prev_hash` link
and a daily Merkle root would make the decision log tamper-evident at near-zero cost.
(b) **Recall weighting**: `engine/learning/recommendations.py` weights by win_rate and
recency decay but lacks a context-similarity term; OWM's idea of scoring candidate
memories by how closely current regime/session/conviction match stored conditions is a
reasonable enhancement. Everything else is already covered by `engine/learning/` and
`engine/analytics/` — copying it would be duplication.

### 2. Project rules
no-fit — Nothing in `.claude/rules/`. The MiFID II / EU AI Act framing is regulatory
documentation, not a coding rule, and is irrelevant to a paper-only single-user system.

### 3. Project skills
no-fit — The repo is a server, not a Claude Code workflow. `jarvis-learning-snapshot`
already covers memory inspection.

### 4. Slash commands
no-fit — No command-shaped artifacts.

### 5. Subagents
no-fit — Our `memory-curator` agent already owns memory hygiene.

### 6. Docs
partial-integrate — The OWM five-dimension recall model and the Merkle-anchoring design
are worth a short writeup in `docs/digest/` as a reference design even if we implement
only a subset. Ideas captured, not code.

### 7. Dev tooling
partial-integrate — The hash-chain verification pattern (`verify_audit_hash` /
`export_audit_trail`) is a useful template for a CI/hook integrity check over our decision
log. Small, optional, MIT-licensed reference.

### 8. Dashboard
no-fit — Repo ships no UI; `dashboard/` already renders learning/pattern state.

### 9. Ops / messaging
no-fit — No scheduler/notification components. jarvis-trader already runs nightly
consolidation (`engine/schedulers/`) and has a full `engine/notifications/` stack.

## Integration plan
Two small, additive, MIT-attributed changes — neither touches safety code:

1. **Tamper-evident decision log (primary value).**
   - In `engine/approval/snapshot.py`, after building the canonical snapshot dict, compute
     `sha256` over its JSON form plus a `prev_hash` link; store both alongside the existing
     snapshot in `engine/approval/pipeline_history.py`.
   - Add a daily Merkle-root rollup, hooked into the existing nightly scheduler run.
   - Add a verifier script under `scripts/` (mirrors `verify_audit_hash`).
   - Add a test asserting that mutating a stored snapshot breaks chain verification.
   - This is the bulk of the work; ~M.

2. **Context-similarity term in recall (secondary, optional).**
   - In `engine/learning/recommendations.py`, extend the scorer to add a similarity
     multiplier on top of the existing `win_rate × decay`, behind a default-off flag so
     Stage-1 behavior is unchanged until validated. Add a unit test per
     `.claude/rules/meta-discipline.md`.

Do NOT port `check_trade_legitimacy` — risk gating is hardcoded in
`engine/risk/safety_layer.py` (non-negotiable per `.claude/rules/safety.md`). Reference its
heuristics as ideas only, never as a decision path.

## License & attribution
MIT — reuse permitted with attribution. If the Merkle/hash-chain construction is adapted,
add a source comment citing `mnemox-ai/tradememory-protocol (MIT)` in the touched file
header, mirroring the existing attribution style in `engine/learning/consolidator.py`. No
files copied wholesale; ideas + small constructions only.

## Effort estimate
M (2–8hr) — audit-chain integration is the real work (schema column, hashing, Merkle
rollup, verifier, test). The recall-similarity term is S and optional. Both additive with
no safety-file changes, so no `[safety-review]` tag unless implementation drifts into
`engine/risk/`.

## Red flags
- **High conceptual duplication** (~70%). The main risk is integrating for novelty's sake
  and creating a parallel memory system — a `meta-discipline.md` violation. Only the
  hash-chain audit is clearly net-new.
- **Compliance framing is irrelevant** to a $10K paper-only single-user system. Take the
  crypto-integrity mechanism, ignore the regulatory wrapper.
- **"Emotional state" / affective memory layer is a poor fit** — no human-trader affect to
  record; do not port it.
- **MCP-server architecture mismatch.** Adopt the ideas as native engine code, not by
  standing up another server process.
- No security concerns in the integration path; repo is active (Mar 2026), not archived,
  license is clean.
