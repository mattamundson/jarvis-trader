# PASS43 - Next Top ROI Tranche

## Scope

- Seeded the next ten recommended tasks after completing P9-001 through P9-010.
- Ranked the tranche by guard ratchets, mock fidelity, type/schema hardening, and route-consolidation safety.

## New Tasks

| ID | Status | Why It Is Next |
|---|---|---|
| P10-001 | ready | Locks in the dashboard refresh-interval debt reduction already reported by guards. |
| P10-002 | ready | Promotes newly used endpoint shapes into the generic E2E mock so broader route smoke has fewer false failures. |
| P10-003 | ready | Moves summary derivations out of JSX and into focused pure tests. |
| P10-004 | blocked | Splits the growing Command Center sections file after derivation tests exist. |
| P10-005 | ready | Adds an engine response model for the expanded data-integrity contract. |
| P10-006 | blocked | Adds OpenAPI/schema regression tests after the response model exists. |
| P10-007 | blocked | Wires provider metadata only after the response contract is model-backed. |
| P10-008 | ready | Aligns sidebar navigation with the route-consolidation policy. |
| P10-009 | blocked | Plans redirect readiness only after nav and parity tests are updated. |
| P10-010 | blocked | Runs a consolidated Command Center evidence suite after the P10 dashboard changes. |

## Next Action

- Start `P10-001`: lower `REFRESH_INTERVAL_CEILING` from `128` to the current passing count of `105`.
