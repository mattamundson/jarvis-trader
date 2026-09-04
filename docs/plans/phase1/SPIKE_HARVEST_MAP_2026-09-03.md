# JARVIS Spike Harvest Map — 2026-09-03

**Plan:** JARVIS-MIP-1.0  
**Rule:** harvest evidence and bounded implementations; do not treat a parallel architecture as canonical merely because it exists or has landed on `master`.

> **2026-09-04 re-baseline:** PRs #754 and #756 were merged to `master` as commits `0a6a3bd5b30d1b9ad5e2e412335c7ab5fcc06264` and `410c52b80c7fc9eaa64e4945871fd0954c2d2423`. Their code is therefore **ACTIVE-ON-MASTER / UNADOPTED-AS-CANONICAL**. This map does not authorize reverting or disabling them automatically; it requires explicit containment/migration receipts before they become canonical architecture or receive formal implementation credit under the MIP.

| PR | Current role | Canonical harvest target | Harvest | Do not inherit automatically |
|---|---|---|---|---|
| #749 | research-integrity / Capital Path spike | PIT feature system, Judge lifecycle, Capital Path research WPs | feature availability/registry/store, causal studies, purged validation, research fingerprints/trial ledger, Judge V3 diagnostics/accounting, Capital Path simulation/resampling/scenario/frontier modules | any self-promotion to executable strategy; source-parity claims without external/TOS evidence; active IB/VWAP patches before quantified impact + review |
| #754 | **ACTIVE-ON-MASTER / UNADOPTED-AS-CANONICAL** Command Center V2 control plane | K-01 canonical `/command-center`, Trade/Operations surfaces, V4 PAPER operator evidence | `controlPlane.ts` fail-closed aggregation, candidate-display/approval UX concepts, trade-intent client contract/tests | permanent `/command-center-v2`; duplicate navigation/product generation; treating route presence as K-01 adoption or V4 evidence |
| #756 | **ACTIVE-ON-MASTER / UNADOPTED-AS-CANONICAL** manual trade-intent / paper API | A-04, H-01, canonical OMS, broker/reconciliation migration | zero-allowed risk sizing, durable idempotent intent store, atomic claim, bracket submission path, ambiguous-ack no-retry rule, router tests | independent long-term order authority, legacy risk constants as canonical policy, auto-retry after broker ambiguity, LIVE authorization, formal OMS-complete status |
| #771 | persisted safety-state repair | H-01 + safety-state/recovery WP | fail-closed restoration semantics and focused recovery tests | merge without S3 independent safety review; any relaxation of kill-switch persistence |
| #770 | ThinkScript source-integrity baseline | source registry, PIT feature parity/evidence program | immutable supplied source corpus, SHA256 manifest, source-integrity test, provenance baseline | trading parity, causal validity, statistical edge, PAPER/LIVE authority |
| #748 | **MERGED TOOLING** local PR gate | O-02/O-03 verification fallback | local redacted CI fallback and explicit Python 3.12 venv selection | substitution for required V4/V5 runtime evidence; treating local pass as cloud/host proof |

## #749 detailed extraction

Harvest groups are already separable by file boundary:

- **Feature truth:** `feature_availability.py`, `feature_registry.py`, `feature_store.py`.
- **Causal transformations:** `causal_structure.py`, `calendar_features.py`, `opening_range_causal.py`, `session_vwap_causal.py`.
- **Research integrity:** `research_fingerprints.py`, `research_trial_ledger.py`, `purged_validation.py`.
- **Judge:** `judge_v3.py`, diagnostics, trial accounting.
- **Capital Path:** core, Monte Carlo, resampling, ensemble, scenarios, frontier, report.
- **Source parity:** `source_parity.py` plus ThinkScript registry/scanner; remains evidence-limited until external reference outputs exist.

## #754 extraction and containment

`dashboard/lib/controlPlane.ts` remains the primary harvest candidate because it already encodes fail-closed cockpit aggregation. The V2 route files are migration sources, not target IA. K-01 maps `/command-center-v2` to `/command-center` and the route census must continue treating V2 as noncanonical even though it is now present on `master`.

Required next receipt before K-01 adoption:

1. enumerate every V2 read and mutation path;
2. map each path to the canonical surface/domain owner;
3. prove no browser-to-broker authority exists;
4. preserve degraded/unknown-state blocking semantics;
5. migrate component-by-component into the canonical IA;
6. redirect/deprecate V2 only after feature parity and V3 operator E2E evidence.

## #756 extraction and containment

The valuable invariant is not the endpoint path; it is the lifecycle:

```text
PREVIEWED
→ SUBMITTING (atomic claim)
→ SUBMITTED | BLOCKED | REJECTED | EXPIRED

broker call begins + acknowledgement unknown
→ remain ambiguous/submitting
→ reconcile before any resubmit
```

Because the router is now active on `master`, a migration receipt is mandatory before it can be declared the canonical OMS/manual-trade authority. That receipt must compare the active path to A-04/H-01/OMS/J broker contracts, prove restart/reconciliation behavior, and explicitly disposition the legacy `/orders/place` path. Requested quantity remains a ceiling; risk sizing may produce quantity zero / NO TRADE.

A separate S3 containment proposal may default-disable or feature-gate the pre-plan route, but such a runtime behavior change requires explicit safety review; this document does not perform it.

## Harvest gates

Before any extraction or already-merged spike behavior becomes an adopted authority:

1. target work package adopted;
2. source/target semantics compared;
3. focused tests ported with the behavior;
4. authority-migration receipt completed;
5. required V-rung executed;
6. safety review performed when S3/S4;
7. old/parallel authority not silently left active;
8. already-merged exploratory routes are classified as transitional until the migration receipt is accepted.

**Capital boundary:** this map grants no PAPER or LIVE authorization and does not grant formal MIP completion credit to any listed capability merely because its code is on `master`.
