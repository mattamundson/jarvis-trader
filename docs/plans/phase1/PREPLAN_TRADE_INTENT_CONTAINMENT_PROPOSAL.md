# Pre-Plan TradeIntent Containment Proposal — S3 DRAFT

**Plan:** JARVIS-MIP-1.0  
**Proposal ID:** I-CONT-001  
**State:** PROPOSAL ONLY — NOT IMPLEMENTED / NOT AUTHORIZED  
**Safety class if implemented:** S3  
**Observed baseline:** `master@99d75f31267294d7ff58520683d158408c3c3eeb`

## Problem

PR #756 is now merged and `orders_router.py` unconditionally mounts `trade_intents_router`. The path itself is PAPER-only and already fail-closed in several important ways, but it was created before A-04/B-01/H-01/canonical OMS/J broker contracts were adopted.

The governance issue is therefore not that RT-2 is obviously unsafe; it is that an exploratory path can become de-facto architecture merely through presence on `master`.

## Recommended containment option

Add a server-side registration gate, default OFF:

```text
JARVIS_ENABLE_EXPERIMENTAL_TRADE_INTENTS=0  # default
```

Target behavior:

```python
if experimental_trade_intents_enabled():
    router.include_router(trade_intents_router)
```

The flag would control **route registration**, not bypass or weaken endpoint checks. When enabled, all existing PAPER/LIVE, kill-switch, symbol, market freshness, sizing, reconciliation, bracket and ambiguous-ack checks remain mandatory.

## Why server-side registration

A UI-only hide is insufficient because callers can invoke HTTP routes directly. A server-side default-off gate makes the experimental authority absent unless the operator deliberately opts in.

## Why this is not being implemented automatically

#754/#756 were merged by another human/process after the MIP freeze was established. Disabling that behavior on `master` would itself be a safety/runtime policy change. This proposal therefore requires explicit S3 review before implementation or merge.

## Required acceptance criteria for a containment PR

- [ ] Default is OFF when env/config value is absent.
- [ ] OFF means `/trade-intents/*` is not mounted; read-only unrelated `/orders/status` remains unaffected.
- [ ] ON never enables LIVE; router-level `_require_paper_mode()` remains unchanged and tested.
- [ ] ON does not weaken kill switch, approved-symbol, freshness, zero-sizing, reconciliation, bracket, idempotency or ambiguous-ack protections.
- [ ] Existing durable intents are not deleted or mutated by toggling route visibility.
- [ ] Operator status endpoint/UI discloses whether experimental TradeIntent routes are mounted.
- [ ] Restart behavior is deterministic from configuration.
- [ ] No API key/broker credential changes.
- [ ] Independent safety review approves the behavior change.
- [ ] V3 application E2E and V4 IB PAPER receipt are named before formal operational use.

## Alternative: leave mounted but explicitly transitional

If the owner intends to keep RT-2 callable during the migration, the alternative is:

1. leave routes mounted;
2. label them transitional/experimental in operator UI and runtime status;
3. prohibit formal MIP completion credit;
4. complete `I-MIG-001` on an accelerated schedule;
5. prohibit adding any additional manual-order authority.

This is less contained than default-off registration but avoids changing current behavior before review.

## Recommendation

**Preferred:** server-side default-off registration, because the canonical architecture is not yet adopted and the path can increase PAPER exposure.  
**Current action:** documentation and ratchets only. No runtime behavior is changed by this proposal.

**Invariant:** neither choosing nor rejecting this proposal grants LIVE authorization.