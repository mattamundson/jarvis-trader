# Work Package Charter: `<WP-ID>`

## Control metadata

| Field | Value |
|---|---|
| Plan | `JARVIS-MIP-1.1` |
| Program / Epic | `<PROGRAM>` / `<EPIC>` |
| Work Package | `<WP-ID>` |
| Charter version | `0.1-draft` |
| Status | `DRAFT` |
| Phase / Gate | `<PHASE>` / `<GATE>` |
| Safety / Decision / Codex | `<S#>` / `<D#>` / `<A#>` |
| Accountable human | `<NAME>` |
| Implementation owner | `<NAME OR AGENT>` |
| Independent reviewer | `<NAME>` |

## Objective

State one observable outcome. Do not describe implementation activity as the
outcome.

## Non-goals

- Explicitly excluded behavior.
- Adjacent capability deferred to another WP.

## Dependencies

| WP / contract | Required state | Evidence or mock |
|---|---|---|
| `<ID>` | `<DONE/approved contract>` | `<path>` |

## Authority and contracts

### Authoritative inputs

| Value/domain | Authority | Freshness/completeness rule | Failure behavior |
|---|---|---|---|
| `<VALUE>` | `<SOURCE>` | `<RULE>` | `<FAIL CLOSED/DEGRADE>` |

### Input contracts

- `<named contract and version>`

### Output contracts

- `<named contract and version>`

### Forbidden dependencies and mutations

- `<domain or mutation this WP may not perform>`

## Acceptance criteria

- [ ] Criterion is deterministic and observable.
- [ ] Unavailable, stale, partial, and ambiguous states are specified.
- [ ] No duplicate authority or bypass is introduced.

## Verification plan

| Requirement | Evidence |
|---|---|
| Minimum rung | `<E0-E5>` |
| Unit/property | `<tests>` |
| Integration/replay | `<tests>` |
| Numeric cross-check | `<inputs and expected values, or N/A>` |
| PIT/session/timezone | `<adversarial cases, or N/A>` |
| Security/adversarial | `<cases, or N/A>` |
| Runtime/broker observation | `<procedure, or N/A>` |

## Migration and compatibility

Describe observe → shadow → compare → replay → isolated paper → cutover. Name
the compatibility boundary and the authority during migration.

## Rollback and disable plan

Required for S2+. State the disable mechanism, preserved data, recovery steps,
and conditions that prohibit automatic retry or re-enable.

## Observability and audit

List events, reason codes, metrics, traces, freshness states, actor identity,
and correlation/causation requirements.

## Evidence manifest

`<repo-relative path created during VALIDATION>`

## Residual risks and assumptions

| Risk/assumption | Impact | Owner | Resolution or acceptance |
|---|---|---|---|
| `<ITEM>` | `<IMPACT>` | `<OWNER>` | `<ACTION>` |

## Approvals

| Role | Decision | Identity | UTC timestamp | Evidence |
|---|---|---|---|---|
| Accountable human | PENDING | — | — | — |
| Independent reviewer | PENDING | — | — | — |
| Safety/capital owner, if required | PENDING | — | — | — |
