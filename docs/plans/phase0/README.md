# JARVIS MIP-0 — Plan Adoption and Truth Baseline

**Plan:** JARVIS-MIP-1.0  
**Gate:** ISG-0  
**Status:** IN PROGRESS

MIP-0 eliminates contradictory authorities before downstream runtime capability is implemented.

## Work packages

1. **A-01 — Runtime Truth Baseline & Contradiction Register** — IN PROGRESS
2. **O-01 — CI Baseline & Debt Classification** — IN PROGRESS in parallel where independent
3. **A-02 — Source-of-Truth Hierarchy ADR** — blocked by A-01
4. **A-03 — Target Bounded-Context Architecture ADR** — blocked by A-01/A-02
5. **K-01 — Operator Product IA & Deprecation Map** — blocked by A-03
6. **O-05 — Branch/PR/Codex Governance** — blocked by O-01/A-02
7. **O-02/O-03 — Verification and Reproducible Build** — blocked by O-01

MIP-1 foundations are not part of the MIP-0 implementation queue.

## Governing artifacts

- `../JARVIS_MASTER_IMPLEMENTATION_PLAN_v1.0.md`
- `../JARVIS_PLAN_ADOPTION_2026-09-02.md`
- `../JARVIS_PHASE_0_STATUS.md`
- `A-01_RUNTIME_TRUTH_BASELINE.md`
- `O-01_CI_BASELINE.md`
- `O-01_CI_BASELINE.json`

## Rule

Do not label downstream functionality formally implemented until ISG-0 closes. Spikes may be inspected or harvested only through an explicit governed work package.
