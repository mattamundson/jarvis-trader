# JARVIS Master Implementation Plan — Adoption Record

**Date:** 2026-09-01  
**Plan:** `JARVIS-MIP-1.0`  
**Repository:** `mattamundson/jarvis-trader`  
**Planning branch:** `planning/jarvis-master-implementation-plan-v1`  
**Decision:** **ADOPTED — FORMAL IMPLEMENTATION AUTHORIZED**

## Authorization

The project owner explicitly authorized beginning formal implementation against JARVIS Master Implementation Plan v1.0.

This authorization opens the implementation program at **Phase 0** and starts **A-01 — Runtime Truth Baseline & Contradiction Register**. It does **not** authorize live trading, risk-limit increases, strategy promotion, merging safety-critical changes, or use of broker capital outside the gates defined by the plan.

## Governing rules now in force

1. Every implementation task maps to a stable Work Package ID.
2. Pre-plan PRs #749, #754, #756 and the RT-3 spike are frozen for harvest, not treated as completed implementation.
3. Downstream capability implementation remains gated by **ISG-0**.
4. Hard risk, canary/live promotion, and capital changes remain human-authorized.
5. “Done/verified” claims must state the observed E0–E5 evidence rung.
6. Runtime and broker truth supersede stale documentation.
7. No new parallel dashboard generation or execution path may be created outside the target architecture.

## Phase-0 execution order

1. `A-01` Runtime truth baseline & contradiction register — **IN_PROGRESS**
2. `O-01` CI baseline & debt classification
3. `A-02` Source-of-truth hierarchy & canon ADR
4. `A-03` Target bounded-context architecture ADR
5. `K-01` Operator product IA & wireframe approval
6. `O-05` Branch/PR/Codex governance
7. `B-01` Instrument Master
8. `H-01` Versioned Risk Policy
9. `M-01` Canonical Event/Audit schema
10. `N-02` Environment & authorization matrix
11. `A-04` Core domain contracts
12. `O-02/O-03` Verification and reproducible-build foundations

## Status

**Formal implementation:** STARTED  
**Current phase:** Phase 0  
**Current work package:** A-01  
**ISG-0:** OPEN / NOT YET SATISFIED
