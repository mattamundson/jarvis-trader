# JARVIS Master Implementation Plan — Adoption Record

**Date:** 2026-09-02  
**Plan:** `JARVIS-MIP-1.0`  
**Repository:** `mattamundson/jarvis-trader`  
**Adoption PR:** [#768](https://github.com/mattamundson/jarvis-trader/pull/768)  
**Decision:** **ADOPTED — MIP-0 AUTHORIZED**

## Authorization boundary

The owner authorized the formal implementation program and directed execution of the recommended next steps. This opens **MIP-0** and queues **A-01 — Runtime Truth Baseline & Contradiction Register**.

It does **not** authorize live trading, a canary, higher risk limits, strategy promotion, broker-capital use, or autonomous merging of S3/S4 changes. Live capital requires `JARVIS-MIP-1.0` milestone `M11` and a separate explicit Tier 3 owner authorization.

## Governing rules

1. Every implementation task maps to a stable Work Package ID.
2. PRs #749, #754, #756 and RT-3 remain harvest-only spikes until an approved work package selects their changes.
3. Downstream runtime capability remains gated by **ISG-0**.
4. Hard risk, canary/live promotion, and capital changes remain human-authorized.
5. Every “done” or “verified” claim states its observed E0–E5 rung.
6. Runtime and verified broker truth supersede stale prose.
7. No new permanent dashboard or broker-mutation path may be created outside the target architecture.
8. Exposure-increasing mutations fail closed on stale or ambiguous state; authenticated cancel/reduce/flatten paths remain available when their required command and broker state is verified.

## MIP-0 execution order

1. `A-01` Runtime truth baseline and contradiction register — **IN PROGRESS**
2. `O-01` CI baseline and debt classification — **IN PROGRESS**
3. `A-02` Source-of-truth hierarchy ADR
4. `A-03` Target bounded-context architecture ADR
5. `K-01` Operator product IA and deprecation map
6. `O-05` Branch/PR/Codex governance
7. `O-02/O-03` Verification and reproducible-build foundations required by ISG-0

The MIP-1 foundations `B-01`, `H-01`, `M-01`, `N-02`, and `A-04` may be designed during MIP-0, but runtime implementation remains blocked until ISG-0 and their Definition of Ready are satisfied.

## Status

**Formal implementation:** STARTED  
**Current phase:** MIP-0  
**Active work packages:** A-01 and O-01  
**ISG-0:** OPEN / NOT YET SATISFIED  
**Live/canary authorization:** NOT GRANTED
