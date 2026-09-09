# JARVIS Authority Migration Receipt

**Plan:** JARVIS-MIP-1.0  
**Purpose:** prevent a new source of truth from replacing an old one without parity, recovery, reconciliation, and rollback evidence.

This receipt is required before an existing authority is redirected, deprecated, or removed. Completing the form is evidence preparation only; it does not authorize PAPER/LIVE execution or a production cutover by itself.

## Required identity

- Migration ID
- Work package
- Safety class
- Old authority
- New authority
- Fact/domain being migrated
- Exact consumer inventory
- Exact repository SHA(s)
- Operator/reviewer

## Preconditions

- [ ] Dependency work packages are adopted.
- [ ] Old and new authority semantics are documented.
- [ ] Unknown/stale/ambiguous behavior is explicitly defined.
- [ ] All consumers are enumerated; no hidden fallback authority remains.
- [ ] Required verification rung is named.
- [ ] Rollback owner and rollback trigger are named.

## Parity evidence

Record a bounded comparison window and attach machine-readable evidence for:

1. identical identifiers and normalization;
2. value equality/tolerances;
3. missing/extra records;
4. stale-data behavior;
5. error/failure behavior;
6. restart/recovery behavior;
7. concurrent mutation behavior where applicable;
8. broker/reconciliation behavior for execution facts;
9. dashboard projection behavior for operator-visible facts.

A successful happy-path sample alone is insufficient.

## Cutover states

```text
DRAFT
→ SHADOW_READ
→ PARITY_PROVEN
→ CUTOVER_APPROVED
→ NEW_AUTHORITY
→ OLD_READ_ONLY
→ DEPRECATED
→ REMOVED
```

No state may be skipped. `REMOVED` requires evidence that rollback no longer depends on the old implementation.

## Mandatory failure drills

For S2+ migrations, record expected and observed behavior when applicable:

- new authority unavailable;
- old authority unavailable during shadow comparison;
- stale observation;
- contradictory observation;
- process restart between write and acknowledgement;
- persistence failure after external side effect;
- duplicate/idempotent request;
- reconciliation disagreement.

Any uncertain exposure-increasing state must fail closed.

## Rollback receipt

- rollback command/procedure;
- data compatibility statement;
- maximum rollback time objective;
- whether external/broker side effects require reconciliation first;
- proof rollback was tested at the required verification rung.

## Final approvals

- Engineering reviewer: ____________________
- Safety reviewer when required: ____________________
- Operator/runtime reviewer when required: ____________________
- Capital owner for S4/LIVE: ____________________

**Invariant:** a migration receipt may prove readiness for a human decision; it never grants capital authority itself.
