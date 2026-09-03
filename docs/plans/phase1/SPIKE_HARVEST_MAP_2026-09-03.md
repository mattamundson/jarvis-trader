# JARVIS Spike Harvest Map — 2026-09-03

**Plan:** JARVIS-MIP-1.0  
**Rule:** harvest evidence and bounded implementations; do not merge a parallel architecture merely because it exists.

| PR | Current role | Canonical harvest target | Harvest | Do not inherit automatically |
|---|---|---|---|---|
| #749 | research-integrity / Capital Path spike | PIT feature system, Judge lifecycle, Capital Path research WPs | feature availability/registry/store, causal studies, purged validation, research fingerprints/trial ledger, Judge V3 diagnostics/accounting, Capital Path simulation/resampling/scenario/frontier modules | any self-promotion to executable strategy; source-parity claims without external/TOS evidence; active IB/VWAP patches before quantified impact + review |
| #754 | Command Center V2 control-plane spike | K-01 canonical `/command-center`, Trade/Operations surfaces, V4 PAPER operator evidence | `controlPlane.ts` fail-closed aggregation, candidate-display/approval UX concepts, trade-intent client contract/tests | permanent `/command-center-v2`; browser-to-broker authority; duplicate command center/navigation |
| #756 | manual trade-intent / paper API spike | A-04, H-01, OMS, broker/reconciliation migration | zero-allowed risk sizing, durable idempotent intent store, atomic claim, bracket submission path, ambiguous-ack no-retry rule, router tests | independent long-term order authority, legacy risk constants as canonical policy, auto-retry after broker ambiguity, live enablement |
| #771 | persisted safety-state repair | H-01 + safety-state/recovery WP | fail-closed restoration semantics and focused recovery tests | merge without S3 independent safety review; any relaxation of kill-switch persistence |
| #770 | ThinkScript source-integrity baseline | source registry, PIT feature parity/evidence program | immutable supplied source corpus, SHA256 manifest, source-integrity test, provenance baseline | trading parity, causal validity, statistical edge, PAPER/LIVE authority |

## #749 detailed extraction

Harvest groups are already separable by file boundary:

- **Feature truth:** `feature_availability.py`, `feature_registry.py`, `feature_store.py`.
- **Causal transformations:** `causal_structure.py`, `calendar_features.py`, `opening_range_causal.py`, `session_vwap_causal.py`.
- **Research integrity:** `research_fingerprints.py`, `research_trial_ledger.py`, `purged_validation.py`.
- **Judge:** `judge_v3.py`, diagnostics, trial accounting.
- **Capital Path:** core, Monte Carlo, resampling, ensemble, scenarios, frontier, report.
- **Source parity:** `source_parity.py` plus ThinkScript registry/scanner; remains evidence-limited until external reference outputs exist.

## #754 extraction

`dashboard/lib/controlPlane.ts` is the primary harvest candidate because it already encodes fail-closed cockpit aggregation. The V2 route files are migration sources, not target IA. K-01 therefore maps `/command-center-v2` to `/command-center` and the route census must continue treating V2 as noncanonical.

## #756 extraction

The valuable invariant is not the endpoint path; it is the lifecycle:

```text
PREVIEWED
→ SUBMITTING (atomic claim)
→ SUBMITTED | BLOCKED | REJECTED | EXPIRED

broker call begins + acknowledgement unknown
→ remain ambiguous/submitting
→ reconcile before any resubmit
```

A-04/OMS contracts should absorb that invariant before any active router migration. Requested quantity remains a ceiling; risk sizing may produce quantity zero / NO TRADE.

## Harvest gates

Before any extraction lands in an active authority:

1. target work package adopted;
2. source/target semantics compared;
3. focused tests ported with the behavior;
4. authority-migration receipt completed;
5. required V-rung executed;
6. safety review performed when S3/S4;
7. old/parallel authority not silently left active.

**Capital boundary:** this map grants no PAPER or LIVE authorization and does not approve any listed PR for merge.
