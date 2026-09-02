# JARVIS Phase 0 — Plan Adoption & Truth Baseline

**Plan:** JARVIS-MIP-1.0  
**Gate:** ISG-0  
**Status:** IN PROGRESS

Phase 0 exists to eliminate contradictory authorities before downstream capability implementation.

## Work packages

1. **A-01 — Runtime Truth Baseline & Contradiction Register** — IN PROGRESS
2. **O-01 — CI Baseline & Debt Classification** — READY / running in parallel where independent
3. **A-02 — Source-of-Truth Hierarchy & Canon ADR** — blocked by A-01
4. **A-03 — Target Bounded-Context Architecture ADR** — blocked by A-01/A-02
5. **K-01 — Operator Product IA & Wireframe/Deprecation Map** — blocked by A-03
6. **O-05 — Branch/PR/Codex Governance** — blocked by O-01/A-02

Supporting Phase-1 foundations are queued only after their required dependencies.

## Governing artifacts

- `../JARVIS_MASTER_IMPLEMENTATION_PLAN_v1.0.md`
- `../JARVIS_PLAN_ADOPTION_2026-09-01.md`
- `../JARVIS_PHASE_0_STATUS.md`
- `A-01_RUNTIME_TRUTH_BASELINE.md`

## Rule

Do not label downstream functionality formally implemented until ISG-0 closes. Technical spikes may be inspected/harvested only when a governed WP explicitly calls for them.
