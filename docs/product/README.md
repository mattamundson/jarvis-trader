# JARVIS Product Planning

**Status:** Proposed governing product package — not adopted until explicit human review.

This directory separates long-term product governance from historical tactical roadmaps and implementation PRs.

## Start here

1. [`JARVIS_MASTER_PRODUCT_PLAN.md`](./JARVIS_MASTER_PRODUCT_PLAN.md) — mission, outcomes, architecture programs, target authorities, delivery phases, verification ladder, Definition of Done, current-state reconciliation, and priority execution order.
2. [`COMMAND_CENTER_PRODUCT_SPEC.md`](./COMMAND_CENTER_PRODUCT_SPEC.md) — canonical operator information architecture, page anatomy, status semantics, data/command behavior, degraded states, migration rules, and UI acceptance criteria.
3. [`JARVIS_DELIVERY_BACKLOG.md`](./JARVIS_DELIVERY_BACKLOG.md) — PlanLife-style outcome → program → epic → work-package hierarchy with conservative current status.
4. [`prototypes/jarvis-product-blueprint.html`](./prototypes/jarvis-product-blueprint.html) — static zero-network visual blueprint containing a roadmap view and Command Center concept. It uses sample data and performs no broker/API mutation.

## Governance hierarchy

```text
JARVIS Master Product Plan
└── Outcome
    └── Program
        └── Epic
            └── Feature / Capability
                └── Work Package
                    └── Task
                        └── Evidence / Test / Receipt

Release Train / PR / Issue = delivery mechanism mapped beneath this hierarchy.
```

## Current governing status

These artifacts are **proposed**, not automatically authoritative. Until explicitly adopted:

- existing merged #754/#756 behavior remains ACTIVE-UNADOPTED;
- the V2 dashboard is a migration/harvest source, not the accepted final Command Center;
- manual order mutation authority remains unresolved between legacy and TradeIntent paths;
- draft #786 contains migration/governance receipts;
- draft #788 is the clean current-master Phase-1 inert contract stack;
- draft #749 remains a research-integrity/Capital Path harvest source;
- no document in this directory grants PAPER or LIVE capital authority.

## Historical planning relationship

Older plans such as `docs/plans/roadmap-2026-04-20-unified.md`, `docs/JARVIS_SOTA_PLAN.md`, and root master reports remain historical evidence. They should not be deleted merely because this package exists. Claims from older plans must be revalidated against the current repository/runtime before they are carried into current status.

## Adoption procedure

1. Review the Master Product Plan.
2. Resolve requested edits.
3. Record explicit human adoption decision and effective SHA.
4. Reconcile active PRs/issues against the hierarchy.
5. Use the status vocabulary and Definition of Done for subsequent work.
6. Keep LIVE promotion as a separate explicit capital decision.
