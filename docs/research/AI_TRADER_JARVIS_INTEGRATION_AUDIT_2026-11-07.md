# AI-Trader → JARVIS: selective integration audit (2026-11-07)

**Scope:** source review of HKUDS/AI-Trader main and JARVIS master; initial research-only implementation. This is **not** a complete security audit, performance backtest, or deployed integration. No external AI-Trader API is invoked. Do not register agents or install third-party remote skills as part of this PR.

## Source comparison (inspected paths)

| AI-Trader path | Observed responsibility | JARVIS path | Decision |
| --- | --- | --- | --- |
| `service/server/signal_quality.py` | Keyword/format-based extraction and heuristic quality scores | `engine/agents/pipeline.py` | Do not import heuristic confidence as predictive probability. Independently assess realized outcomes. |
| `service/server/challenge_scoring.py` | Replays submitted simulated trades, evaluates portfolio curves | `engine/backtest/`; `engine/risk/safety_layer.py` | Keep JARVIS risk and canonical backtest gates. Trade snapshots alone cannot prove executable fills. |
| `service/server/experiment_metrics.py` | Agent metric snapshots and agent interaction network edges | `engine/agents/pipeline.py`; `engine/learning/` | Adapt the concept of paired agent-vs-control evaluations; do not duplicate existing agents. |
| `research/scripts/analyze_experiments.py`; `research/scripts/build_network_edges.py` | Research analysis and collaboration graph pipeline (README and file inventory) | `engine/backtest/`; `docs/` | Candidate for later inspection/ablation; not copied in this PR. |
| `service/server/price_fetcher.py` | Alpha Vantage, Hyperliquid, and Polymarket price sourcing | JARVIS market data/order-flow modules | Not suitable as proof of tick-level CME depth or SPX option-chain fidelity. |
| `service/server/permissions.py` | Agent role/capability checks | JARVIS API auth and safety layer | Keep existing auth; never route execution through third-party identity. |
| `service/server/fees.py` | Fixed platform transaction fee rate | JARVIS cost/slippage research | Do not assume a single venue-agnostic fee models ES futures or SPX 0DTE. |
| `skills/{ai4trade,copytrade,tradesync,market-intel,polymarket}` | Agent APIs, signal feed, copy trading, market-intel and prediction-market instructions | Existing JARVIS pipeline and broker adapters | Treat as untrusted third-party integration instructions; no autonomous installation or copying. |
| `service/frontend/` | React UI | `dashboard/app/`, Next.js 15 | Evaluate interaction patterns separately; no dashboard modification in this PR. |
| `docs/api/openapi.yaml` | Documented API surface | JARVIS canonical API references | Potential future read-only adapter, subject to contract and security checks. |

## Existing JARVIS capability confirmed

`engine/agents/pipeline.py` already contains parallel analysts, bull/bear debate, trader synthesis, risk manager, and fund manager, with intermediate `debate_result`, `trade_decision`, and `risk_decision` recorded. It can force HOLD on an inconclusive debate. Replacing or duplicating the agent framework would add complexity without establishing any incremental trading edge.

`docs/CURRENT_STATE.md` and `engine/CLAUDE.md` stress that historical documentation is not current live trade-eligibility truth. Actual live eligibility is determined by runtime gates. This work does not change those gates.

## New bounded prototype

`engine/agents/agent_evidence_research.py` provides a **pure, read-only paired comparison** for already-collected observation records:

- Same event identity and forward-return horizon for deterministic baseline and agent action.
- Records final-agent versus baseline disagreement frequency, participation, directional accuracy and mean signed *underlying* return. Bull/bear are JARVIS's deliberate advocacy stances, not independently calibrated directional predictions.
- Rejects invalid directions, duplicate event identity, naive timestamps, data available only after decision time, future outcomes and nonfinite returns.
- Does not import execution, broker or safety modules.
- Does **not** feed its score back into trade approval or order sizing.

It deliberately does not claim a profitable edge. Return increment is descriptive, not risk adjusted, and is not SPX option P&L. Holding yields zero exposure in this simplified measurement; cash financing, carry, spread, commissions, impact and slippage are excluded.

## Follow-on requirements before any production feature

1. Define a typed, immutable observation export from the existing pipeline, preserving as-of time, exact model/prompt/version, input availability timestamps, outcomes and source hashes. Never use current pipeline output to reconstruct what historical agents allegedly saw.
2. Validate trading calendars, fixed horizon, availability time of the realized outcome, non-overlapping samples, ES contract rolls and SPX option expiry/time value. Reject incomplete records.
3. Compare against deterministic baseline and ablations on exact same sample; report both unconditional and participation-conditional metrics. Compare against always-HOLD and market-only controls.
4. Run pre-registered chronological OOS, purged walk-forward, clustered bootstrap / permutation, multiple-hypothesis adjustment, concentration sensitivity, fee/slippage stress and regime breakdown.
5. Only after data certification, expose read-only results in a new dashboard surface with explicit sample counts and `UNVERIFIED` / `NOT_EVALUATED` states.
6. Obtain independent security review before third-party signal sync, copying, brokerage actions, or remote agent skill downloads.

## Verification contract

- **Source inspection:** GitHub source files and JARVIS pipeline/docs inspected on November 7, 2026.
- **New code/tests:** Submitted for review on a dedicated branch. No claim of complete local repo test, CI pass, successful deployed route, or improved trading expectancy.
- **Safety:** No changes to `engine/config.py`, `engine/risk/`, `engine/agents/pipeline.py`, brokerage, REST routes, or `dashboard/`.
- **Acceptance:** Run `cd engine && .venv/bin/python -m pytest tests/test_agent_evidence_research.py -q` (Linux) or `cd engine && .venv/Scripts/python -m pytest tests/test_agent_evidence_research.py -q` (Windows), followed by Ruff and full safe non-IB suite. Runtime end-to-end validation is separately required for a future integrated feature.

## Licensing

The upstream README displays an MIT badge, but repository metadata did not expose a detected license during inspection. **No AI-Trader source code is copied**. Confirm actual license file and applicable obligations before code reuse.

## Phase 2 — Persisted-decision adapter (added to this research PR)

- `engine/agents/jarvis_decision_evidence.py` consumes an actual stored `decisions` table row (obtained through `DatabaseManager.get_decision_by_id`) with full `full_pipeline_json`, including real `debate_result`, bull and bear reports, and exact final action.
- `HistoricalEvidence` must be supplied by a separately audited point-in-time data/baseline process; it contains input and baseline availability timestamps, immutable data identifiers, fixed horizon, future underlying return, and the outcome availability timestamp. This adapter **does not** fabricate missing fields, read a broker, or query live prices.
- The source `decisions` table does not independently certify when every feature/news item originally became available. `input_available_at` is an **external attestation**, not proof provided by the decisions log. Until the input lineage and market data can be certified from immutable receipts, research remains NOT EVALUATED.
- Only exact `buy` / `sell` / `hold` final actions can participate; missing/inconsistent pipeline final action and degraded or partial debate records are rejected. This is intentionally narrower than all possible existing JARVIS action strings.
- The initial comparator uses *signed underlying returns*, not executable options trades, and cannot establish net expectancy for ES futures or SPX 0DTE.
- Validation: `engine/tests/test_jarvis_decision_evidence.py` includes positive and negative temporal/provenance cases. CI status must be verified after the final commit.

**Note on CI:** the first PR run failed Ruff on an import-order issue in the initial research test plus an unrelated pre-existing `backtest/tpo_profile.py` B905 finding. The research test was adjusted. The baseline B905 remains outside this PR's scope and may continue to block whole-repository CI; do not silently modify unrelated trading calculations to make the status green.
