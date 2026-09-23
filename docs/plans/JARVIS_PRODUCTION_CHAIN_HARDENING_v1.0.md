# JARVIS Production Hardening v1.0 — One Chain of Truth Addendum

**Prepared:** 2026-09-01  
**Factored into repository:** 2026-09-12  
**Scope:** JARVIS production-hardening planning input  
**Capital authority:** **PAPER ONLY**  
**Live/canary authority:** **NOT GRANTED**  
**Relationship to MIP:** supplements `JARVIS-MIP-1.0`; does not bypass `ISG-0`, downstream milestone gates, safety review, or explicit human authorization.

## 1. Governing thesis

JARVIS earns production readiness through **one chain of truth**:

> one fact has one authority, every feature proves when it was knowable, every order uses one path, and every expansion of capital authority requires explicit human approval.

The shortest safe route is consolidation:

1. establish one source of truth;
2. repair causal evidence;
3. route every broker mutation through one deterministic OMS;
4. run the exact production path for **30–60 trading days** in frozen paper operation;
5. only then hold a canary-readiness review.

Multi-strategy expansion, alternative data, agents, reinforcement learning, options, crypto, clustering, and hot failover remain deferred capability programs unless a later gate explicitly promotes them.

## 2. Authority boundary

The supplied production-hardening input explicitly states:

- **Current capital authority:** paper only.
- Live-capital authorization has not been granted.
- AI accelerates bounded work; it does not inherit capital authority.
- AI agents may not enable live, raise limits, promote strategies, repurpose credentials, submit broker orders, or merge safety-critical work.
- Missing runtime, broker, policy, or credential facts stop the work rather than being guessed.

This addendum therefore authorizes only planning/governance reconciliation and bounded paper-path readiness work. It does **not** authorize runtime trading changes, live/canary credentials, live-capital use, raised limits, or broker-order submission. In plain gate language: this addendum does not authorize runtime trading changes.

## 3. Production-readiness gate sequence

The production-hardening input replaces date promises with evidence gates. Planning ranges are estimates, not deployment authority.

| # | Phase | Gate | Planning range | Permitted state | Path | Current input state |
|---:|---|---|---|---|---|---|
| 0 | Truth and governance | ISG-0 | 2–4 weeks | Paper only | Critical | Open |
| 1 | Contracts and isolation | M1 | 3–5 weeks | Paper only | Critical | Pending |
| 2 | PIT data and research integrity | M2 | 5–8 weeks | Research / paper | Critical | Pending |
| 3 | Judge and anchor strategy | M3 | 4–7 weeks | Research / shadow | Critical | Pending |
| 4 | Risk, OMS and broker spine | M4 | 6–10 weeks | IBKR paper | Critical | Pending |
| 5 | Read-only operator truth | M5 | 4–7 weeks | Read-only | Critical | Pending |
| 6 | Integrated paper controls | M6 | 4–7 weeks | IBKR paper | Critical | Pending |
| 7 | Capital Path and risk frontier | M7 | 3–5 weeks | Simulation | Parallel | Pending |
| 8 | Remaining phases | M8–M12 | Source excerpt unavailable | Gated | Deferred/critical by later plan | Pending |

**Source completeness note:** the pasted source said there are thirteen phases and showed rows 1–8 of 13. Rows 9–13 were not visible in the provided excerpt and are not reconstructed here.

## 4. Starting queue from supplied excerpt

The supplied source says the authorized starting queue has ten work packages; only eight rows were visible in the excerpt. The two hidden rows are intentionally left unresolved rather than guessed.

| # | Authorized starting task | MIP mapping | Safety | Evidence | Execution / review |
|---:|---|---|---|---|---|
| 1 | Rebase and update PR #760 against `master@3e4a903` | A-01/O-01 | S0 | E0 | Human + AI |
| 2 | Capture and sign the redacted runtime-truth baseline | A-01 | S2 | E2 | Human |
| 3 | Produce one complete current-master CI receipt | O-01 | S1 | E2 | AI + Human review |
| 4 | Implement fail-closed `safety_state_verified` and failure matrix | P0-SAFE | S3 | E3 | AI + independent review |
| 5 | Adopt the source-of-truth ADR | A-02 | S1 | E1 | Human |
| 6 | Adopt the modular-monolith and one-mutation-spine ADRs | A-03 | S2 | E2 | Human |
| 7 | Adopt operator-product and change-governance ADRs | K-01/O-05 | S1 | E1 | Human |
| 8 | Build Instrument Master and versioned Risk Policy contracts | B-01/H-01 | S3 | E2 | AI + independent review |
| 9 | Source excerpt unavailable | TBD | TBD | TBD | TBD |
| 10 | Source excerpt unavailable | TBD | TBD | TBD | TBD |

## 5. Reconciliation with existing repository MIP artifacts

Existing recovered artifacts state `JARVIS-MIP-1.0`, MIP-0, and `ISG-0 OPEN / NOT YET SATISFIED`. This production-hardening input is consistent with the same boundary if interpreted as:

- Phase 0 / ISG-0 is open for truth/governance work;
- production readiness is not granted;
- live/canary authority remains closed;
- downstream implementation remains gated;
- paper-path work must produce explicit evidence at the advertised rung.

Where older wording says “MIP-0” and newer wording says “Phase 0 / ISG-0,” treat them as the same governance stage unless a later adopted MIP revision splits them.

## 6. Deferred capability programs

The following are outside the launch-critical path unless explicitly authorized later:

- two-week jump to live trading;
- static margin and universal cost/rebate tables;
- re-running failed strategies at larger capital to manufacture a pass;
- uncalibrated strategy voting or confidence averaging;
- LLM, confluence, memory, or RL position-size increases;
- SMS, WhatsApp, or Siri-only broker authority;
- automatic model, prompt, strategy, policy, or live promotion;
- short-volatility options, crypto perpetuals, and prediction-market trading as launch requirements;
- mandatory Redis, QuestDB, database clustering, partitioning, or hot failover without measured need and safe fencing.

## 7. Immediate consequences for the implementation plan

1. The next defensible move is not a strategy expansion; it is source-of-truth consolidation.
2. A-01/O-01 stay first because runtime truth and CI truth define what can be trusted.
3. `P0-SAFE` should be tracked as a Phase 0 safety work package, but it must receive independent review before merge because the source classifies it as S3/E3.
4. B-01/H-01 may be prepared after ADR alignment, but implementation must not create a second symbol, calendar, risk-policy, execution, or data authority.
5. The frozen paper campaign becomes a non-negotiable prerequisite to any canary-readiness decision.
