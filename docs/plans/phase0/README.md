# JARVIS MIP-0 — Plan Adoption and Truth Baseline

**Plan:** JARVIS-MIP-1.0  
**Gate:** ISG-0  
**Status:** IN PROGRESS — DESIGN-TO-READY

MIP-0 eliminates contradictory authorities before downstream runtime capability is implemented. Design work may proceed where it does not require unresolved local-runtime facts, but no blocked work package is relabeled complete and no downstream runtime authority is granted before ISG-0 closes.

## Work packages

1. **A-01 — Runtime Truth Baseline & Contradiction Register** — BLOCKED-AWAITING-RUNTIME; local Windows receipt required
2. **O-01 — CI Baseline & Debt Classification** — repair merged in PR #773; exact refreshed MIP-head CI receipt pending final completion
3. **A-02 — Source-of-Truth Hierarchy ADR** — DRAFT COMPLETE; adoption blocked by A-01 and PR #768
4. **A-03 — Target Bounded-Context Architecture ADR** — DRAFT COMPLETE; adoption blocked by A-01/A-02 and PR #768
5. **K-01 — Operator Product IA & Deprecation Map** — DRAFT COMPLETE; route migration/removal not authorized
6. **O-05 — Branch/PR/Codex Governance** — implementation on a separate stacked branch; branch-protection admin verification remains external
7. **O-02 — Verification Matrix** — DRAFT COMPLETE; adoption blocked by O-01/PR #768
8. **O-03 — Reproducible Build Baseline** — DRAFT COMPLETE; bounded reproducibility only, not bit-for-bit Python locking

MIP-1 foundations are not formally implemented until ISG-0 closes. Their next intended sequence is A-04 → B-01 → H-01 → M-01 → N-02, followed by PIT feature/Judge, portfolio/risk, OMS/broker, and canonical operator-product migrations.

## Governing artifacts

- `../JARVIS_MASTER_IMPLEMENTATION_PLAN_v1.0.md`
- `../JARVIS_PLAN_ADOPTION_2026-09-02.md`
- `../JARVIS_PHASE_0_STATUS.md`
- `A-01_RUNTIME_TRUTH_BASELINE.md`
- `O-01_CI_BASELINE.md`
- `O-01_CI_BASELINE.json`
- `A-02_SOURCE_OF_TRUTH_HIERARCHY_ADR.md`
- `A-03_TARGET_BOUNDED_CONTEXT_ARCHITECTURE_ADR.md`
- `O-02_VERIFICATION_MATRIX.md`
- `O-03_REPRODUCIBLE_BUILD_BASELINE.md`
- `K-01_OPERATOR_PRODUCT_IA.md`

## Non-negotiable rule

Do not label downstream functionality formally implemented, production-ready, live-ready or capital-authorized until its required verification rung is complete and ISG-0/dependent gates have closed. Spikes may be inspected or harvested only through an explicit governed work package.
