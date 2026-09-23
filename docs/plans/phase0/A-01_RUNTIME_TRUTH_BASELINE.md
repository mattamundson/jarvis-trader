# A-01 — Runtime Truth Baseline & Contradiction Register

**Plan:** JARVIS-MIP-1.0  
**Program:** A — Platform & Architecture  
**Phase:** MIP-0  
**Safety class:** S0 planning artifact; findings include S3/S4 blockers  
**State:** **IN_PROGRESS**  
**Repository evidence baseline:** `master@e2a1006e3eb7d35a840487c80899b33103b52277`  
**Started:** 2026-09-02

## Objective

Establish an evidence-backed baseline of what the repository currently claims, what the code actually defaults to, what runtime facts remain unavailable from repository inspection, and which contradictions must be resolved before ISG-0 can close.

This document intentionally does **not** choose safety values merely by majority vote among documents. Where runtime `.env` or broker state is required, the item remains unresolved until observed from the actual runtime. The future authoritative policy is H-01 Versioned Risk Policy.

## Evidence classes

- **CODE:** executable source/default behavior.
- **RUNTIME-DOC:** documentation claiming current runtime state; must be runtime-verified before being treated as fact.
- **EXAMPLE:** `.env.example`, setup guides or historical values; never runtime authority.
- **HISTORICAL:** old canon/roadmap/session document.
- **BROKER:** broker-observed state; highest authority for positions/orders/fills/account when verified.

## Contradiction Register

| ID | Severity | Domain | Conflicting evidence | Temporary Phase-0 position | Resolution WP | State |
|---|---|---|---|---|---|---|
| CRT-001 | HIGH | Runtime ports | Older `README.md` quick start uses engine/dashboard `8000/3000`; `engine/main.py`, `AGENTS.md`, `dashboard/CLAUDE.md` use `8010/3010`. | Treat `8010/3010` as code/current-dev expectation, but verify actual running services in A-01 runtime observation. | A-01, O-03 | OPEN-RUNTIME |
| CRT-002 | MED | Python runtime | Older README says Python 3.11; `AGENTS.md` describes Python 3.12 environment and CI-canonical requirements. | Target Python version must be pinned by O-03; do not infer from README. | O-03 | OPEN |
| CRT-003 | HIGH | Operational datastore | Older README/canon describes PostgreSQL/Redis/QuestDB as running infrastructure; current `DatabaseManager` is SQLite/WAL and `PortfolioTracker` states SQLite is canonical in real deployments. | SQLite is the planning baseline through paper. Postgres/QuestDB are not assumed requirements. | A-02, A-03 | PLAN-RESOLVED |
| CRT-004 | CRITICAL | Daily-loss halt | `engine/config.py` default is `MAX_DAILY_LOSS_PCT=0.06`; `docs/CURRENT_STATE.md` claims `0.08`; `engine/.env.example` uses `0.02`; older skill/handoff docs also describe 2%. | **No value is accepted as runtime truth from git.** Observe redacted runtime config, then H-01 creates one versioned policy. | A-01, H-01 | BLOCKING |
| CRT-005 | CRITICAL | Max drawdown halt | `engine/config.py` default/current comments use `0.20`; `engine/.env.example` and older agent skill material use `0.10`; current-state prose claims 0.20. | Runtime observation required; H-01 becomes authority. | A-01, H-01 | BLOCKING |
| CRT-006 | CRITICAL | Contract cap | `engine/config.py` comment says hard cap `20` / “up to 20 authorized” while the actual Field default is `2`; `docs/CURRENT_STATE.md` claims `4`; `.env.example` uses `2`. | Treat as unresolved safety-critical configuration. No formal execution work may depend on a guessed value. | A-01, H-01, H-03 | BLOCKING |
| CRT-007 | HIGH | Position-size limit | `engine/config.py` default is 10%; `.env.example` is 5%; current state claims 10%. | Runtime observation required; H-01 authority afterward. | A-01, H-01 | OPEN-RUNTIME |
| CRT-008 | CRITICAL | Human approval | `engine/config.py` default/documentation and `PAPER_TRADING_GUIDE` describe approval `True`; `engine/CLAUDE.md` and `CURRENT_STATE.md` describe a standing runtime decision `False`. | Separate paper/canary/live authorization semantics in N-02/H-01. Current runtime flag must be observed; prose is not authority. | A-01, N-02, H-01 | BLOCKING |
| CRT-009 | CRITICAL | Live enablement | Code/default/docs generally claim `LIVE_TRADING_ENABLED=False`, but formal plan requires proving lower environments cannot acquire/activate live credentials rather than trusting a bool. | Treat live as **not authorized** regardless of flag. Runtime flag/port/account still observed in A-01; N-02 establishes policy-as-code boundary. | A-01, N-02, J-05 | BLOCKING-S4 |
| CRT-010 | HIGH | Paper broker behavior | Some docs say paper orders are merely logged/simulated; `main.py` can select the real `IBGatewayManager` on paper port 4002 when `IB_PAPER_BROKER_ENABLED` is enabled, otherwise simulator. | Current execution mode is unknown until runtime config and connector health are observed. | A-01, J-02, J-03 | OPEN-RUNTIME |
| CRT-011 | HIGH | Broker account identity | Historical/current docs contain different demo/paper account identifiers and placeholders. | Never hardcode account ID into plan/docs; broker-observed account is authority and must be redacted in evidence artifacts. | A-01, N-02, J-03 | OPEN-RUNTIME |
| CRT-012 | CRITICAL | Trading eligibility | README/static docs have claimed MES/MGC PASS while later `engine/CLAUDE.md` records MGC re-halted and notes equities paper-trading without corresponding gate evidence. Static tables are known to drift. | Static markdown eligibility is non-authoritative. Future registry must be strategy+symbol+TF+version specific. | D-08, E-03, A-02 | PLAN-RESOLVED / MIGRATION |
| CRT-013 | CRITICAL | Symbol-wide authorization | Repository history documents prior symbol-wide gate behavior where a PASS in one family could authorize a different strategy family. | Explicitly prohibited. Eligibility key includes strategy version + symbol/instrument + timeframe + evidence version. | D-08, E-03 | PLAN-RESOLVED |
| CRT-014 | HIGH | Paper ledger truth | Older risk/roadmap docs describe JSONL/SQLite/paper-runner dual truth; current `PortfolioTracker` says SQLite is sole truth when DB is present, with JSONL only a no-DB fallback. Broker state is still separate. | For JARVIS audit/intents, SQLite is temporary paper baseline; broker is authority for executable positions/orders/fills; reconciliation is mandatory. | A-02, F-01, J-03 | PLAN-RESOLVED / VERIFY |
| CRT-015 | CRITICAL | Execution authority | `ib_gateway.py`, `ib_gateway_connector.py`, `ib_order_manager.py`, `ibkr_executor.py`, `oms_v2.py`, `order_router.py` and routing factories overlap. | No new formal execution UI may bind to a parallel path. J-02 selects survivor(s); I-02 owns one OMS state machine. | A-03, A-06, I-02, J-02 | BLOCKING-ARCH |
| CRT-016 | HIGH | Market-data executability | `MarketDataManager` has multiple provider/fallback tiers, including delayed/historical/cache sources; source suitability for display vs executable decisions is not one domain contract. | B-02 defines provider classes/provenance; H-03 blocks unsafe sources. | B-02, B-06, H-03 | OPEN |
| CRT-017 | CRITICAL | Initial Balance causality | Issue #751: completed IB can be exposed to pre-range/premarket rows in existing validation logic. | Existing affected evidence cannot be treated as re-certified. Correct feature version + impact analysis required. | B-05, C-05, C-06, E-06 | BLOCKING-RESEARCH |
| CRT-018 | HIGH | VWAP session semantics | Issue #752: a strategy described as RTH/09:30 VWAP can consume near-continuous Globex path; hour-based reset semantics are also ambiguous across bar sizes. | Session policy must be explicit in Instrument Master/calendar service and evidence rerun. | B-01, B-05, C-05, E-06 | BLOCKING-RESEARCH |
| CRT-019 | HIGH | Indicator identity | Legacy TOS KAMA, source Phase and STC variants differ from current/simplified Python formulas. | Preserve separate feature versions; do not normalize formulas silently. | C-01, C-05, C-06 | OPEN-RESEARCH |
| CRT-020 | CRITICAL | Multiple-testing truth | Gate-v2 source documents prior DSR/PF/DD specification issues; `campaign_trials.py` states runner-local grid counts can understate campaign-wide trials. | Historical verdicts are evidence, not future authority. Judge V3 requires preregistered campaign trial accounting. | E-01, E-03, E-04, E-07 | BLOCKING-PROMOTION |
| CRT-021 | HIGH | Dashboard numeric truth | Project rules explicitly state there is no complete engine→proxy→render numeric-accuracy test; current route manifest contains many critical pages with landmark debt. | UI is not authoritative. K-12 is mandatory before critical operator numbers are trusted. | K-01, K-12, O-02 | OPEN |
| CRT-022 | HIGH | Dashboard product identity | Current dashboard has roughly 50 routes including Command Center, Mission Control, paper, portfolio, approvals, trust pane and several overlapping research/ops surfaces. | K-01 consolidates to the adopted 14-surface IA; no permanent V2/V3 route tree. | K-01 | PLAN-RESOLVED / MIGRATION |
| CRT-023 | HIGH | Capital basis | Existing repo docs often assume ~$10K or `$50K+` ALT gate profiles, while JARVIS-MIP uses a $3K initial Capital Path planning case. | Capital Path scenario input is not runtime account truth. Broker equity is runtime truth; validation thresholds/risk policies must explicitly state capital regime. | F-01, G-01, H-01 | OPEN |
| CRT-024 | MED | LLM provider | README describes Anthropic-centric pipeline; current environment docs support Ollama/Vertex/Anthropic and note missing-provider degradation. | LLM provider is contextual infrastructure only; runtime AI health must not affect hard safety. | L-01, L-02, M-03 | OPEN |
| CRT-025 | HIGH | “Implementation complete” historical docs | Repo contains `IMPLEMENTATION_COMPLETE.md`/older roadmap language while formal JARVIS-MIP implementation only begins now. | Historical labels do not satisfy JARVIS-MIP work packages. They remain provenance, not formal completion evidence. | A-02, A-06, O-05 | PLAN-RESOLVED |

## Temporary authority decisions now in force

These are plan decisions already adopted and do not require guessing runtime values:

1. **Formal implementation authority:** JARVIS-MIP-1.0.
2. **Broker state:** verified broker state is authority for executable positions/orders/fills/account.
3. **Operational JARVIS ledger through paper:** SQLite baseline, reconciled to broker.
4. **Research truth:** immutable dataset/evidence/trial artifacts, not README headlines.
5. **Eligibility:** future Judge registry by strategy+symbol+TF+version; static status tables are non-authoritative.
6. **Risk parameters:** unresolved until runtime observed; H-01 will produce one versioned policy hash.
7. **Execution:** no formal new mutation path until J-02/I-02 consolidate broker adapter + OMS.
8. **Dashboard:** one canonical product IA; pre-plan Command Center V2/RT spikes are harvest-only.

## Read-only collection control

A dedicated A-01 snapshot tool is being reviewed separately as S1 work. It must use loopback-only allowlisted GET requests, redact secrets and broker account identifiers, refuse silent overwrite, and remain incapable of broker mutation. Until an operator runs the reviewed tool on the actual JARVIS machine and signs the dispositions, all runtime facts below remain unverified.

## Runtime observations still required to complete A-01

Repository inspection cannot prove the following current-machine facts:

- actual loaded `PAPER_TRADING` and `LIVE_TRADING_ENABLED`;
- actual loaded `REQUIRE_HUMAN_APPROVAL`;
- actual loaded risk limits, including daily loss/drawdown/contract caps;
- actual IB paper/simulator selection (`IB_PAPER_BROKER_ENABLED`);
- actual verified broker connection/account (redacted in artifact);
- actual engine/dashboard ports/processes running now;
- actual datastore file/path/schema version and last backup status;
- active eligibility returned by runtime API;
- current git-deployed commit if the running engine is not exactly repository `master`;
- current health/data source freshness.

A-01 may close only after these are captured from the real runtime or explicitly classified **UNOBSERVED — blocks ISG-0**.

## A-01 exit checklist

- [x] Repository baseline ref pinned.
- [x] Code/doc contradictions inventoried.
- [x] Safety-critical contradictions identified as blockers rather than guessed values.
- [x] Every contradiction mapped to a resolution Work Package.
- [ ] Actual runtime configuration captured in redacted machine-readable form.
- [ ] Running commit/process/ports captured.
- [ ] Broker execution mode/account/health captured in redacted form.
- [ ] Runtime risk values compared to code/default/docs.
- [ ] Runtime eligibility captured.
- [ ] Final contradiction dispositions signed: RESOLVED / SUPERSEDED / BLOCKING / ACCEPTED-RISK.

**Current verification level:** repository evidence review only (E0/S0 planning evidence). Runtime behavior remains unverified until the observation section is completed.
