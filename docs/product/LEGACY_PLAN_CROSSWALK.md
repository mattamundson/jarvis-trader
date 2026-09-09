# JARVIS Legacy Plan / Governance Crosswalk

**Parent candidate:** `JARVIS-MPP-1.0`  
**Status:** **DRAFT DISPOSITION MAP — NO PR CLOSED OR AUTHORITY CHANGED BY THIS FILE**  
**Baseline:** current review of open governance/product stack on 2026-09-09

## Purpose

Prevent a governance reset from accidentally discarding unique safety, runtime-evidence, architecture, or delivery controls contained in older stacked PRs.

The rule is:

> **Harvest unique invariants first; supersede ancestry second.**

A newer plan does not erase an older PR merely because the newer plan is broader.

## Disposition vocabulary

| Disposition | Meaning |
|---|---|
| **RETAIN ACTIVE** | Keep the PR/artifact open because it still contains unique unresolved work. |
| **HARVEST REQUIRED** | Copy/rebuild specific unique content onto current-master ancestry before superseding the old PR. |
| **HISTORICAL EVIDENCE** | Preserve for provenance but do not merge as current authority. |
| **SUPERSEDE AFTER HARVEST** | Close unmerged only after the named unique content exists in a current canonical candidate. |
| **CURRENT CANONICAL CANDIDATE** | Current-master draft that should receive review instead of rebuilding parallel equivalents. |

## PR #768 — JARVIS MIP v1.0 adoption / legacy LIVE-readiness retirement

**Current disposition:** **HARVEST REQUIRED / DO NOT CLOSE YET**

Unique material includes:

- `.claude/rules/safety.md` change replacing ambiguous “Phase 3” LIVE language with explicit milestone + owner authorization semantics;
- `CLAUDE.md` and `engine/CLAUDE.md` contributor/authority boundaries;
- retirement of the legacy Phase-3 readiness CLI so a historical computed `GO` cannot return process success or imply live authorization;
- regression coverage proving legacy readiness cannot grant capital authority;
- historical runbook relabeling;
- `JARVIS_MASTER_IMPLEMENTATION_PLAN_v1.0.md` tactical implementation detail.

### Target treatment

- `JARVIS-MPP-1.0` should become the parent product hierarchy **if explicitly adopted**.
- `JARVIS-MIP-1.0` may remain a subordinate implementation/evidence plan after reconciliation.
- LIVE-readiness retirement and contributor safety semantics must be rebuilt/reviewed on current `master` as a narrow safety-governance PR before #768 is superseded.
- Do not carry stale runtime-risk numbers forward as observed truth; A-01 remains the runtime evidence authority.

## PR #772 — Phase-0 governance baseline

**Current disposition:** **HISTORICAL EVIDENCE + SELECTIVE HARVEST**

Unique material includes:

- Phase-0 status framing;
- A-01 contradiction/runtime baseline documentation;
- O-01 CI baseline receipt and machine-readable evidence;
- Phase-0 index/readme.

### Target treatment

- Preserve A-01/O-01 evidence provenance.
- Current status should be reconciled against merged A-01 tooling, Issue #780, #786, and O-CI-001 rather than merged from stale ancestry.
- Do not let historical references to #754/#756 as frozen become current status.
- After evidence is preserved/currentized, #772 can be superseded rather than merged as a long stacked parent.

## PR #774 — A-02/A-03/O-02/O-03/K-01 architecture and verification contracts

**Current disposition:** **HARVEST REQUIRED / HIGH VALUE**

Unique material includes:

- A-02 source-of-truth hierarchy ADR;
- A-03 target bounded-context architecture ADR;
- O-02 verification matrix;
- O-03 reproducible-build baseline;
- K-01 operator-product IA.

### Target treatment

- Reconcile K-01 with `COMMAND_CENTER_PRODUCT_SPEC.md` and K-MIG-001; the target remains one canonical operator product.
- Reconcile A-03 with active-unadopted #754/#756 rather than pretending those paths do not exist.
- Adopt/revise A-02/A-03/O-02/O-03 independently after product-plan adoption and A-01 requirements are satisfied where applicable.
- Prefer a clean current-master architecture PR over merging the stale stacked ancestry.

## PR #775 — O-05 branch / PR / coding-agent governance

**Current disposition:** **GOV-02 HARVEST CANDIDATE**

Unique material includes:

- canonical PR metadata template;
- read-only PR-governance workflow;
- branch/PR/Codex governance contract;
- safety-class and verification-rung enforcement design.

### Target treatment

- Rebase/rebuild on current `master` only after GOV-01 adoption/revision resolves the parent hierarchy.
- Update field names to `JARVIS-MPP-1.0` Outcome/Program/Epic/WP terminology while retaining explicit Safety Class, Verification Rung, migration/rollback, and capital-impact fields.
- Preserve the privileged-event threat model: governance workflow must not check out or execute untrusted PR code.
- Repository-owner/admin confirmation of branch-protection semantics remains a separate verification item.

## PR #781 — A-01 runtime snapshot assessor

**Current disposition:** **RETAIN ACTIVE**

Reason:

- machine assessment is still useful;
- it is explicitly non-authorizing;
- actual Windows/TWS evidence remains external and unresolved.

Do not close merely because product governance is being consolidated.

## PR #786 — active pre-plan migration governance

**Current disposition:** **CURRENT CANONICAL CANDIDATE**

Contains current-master:

- active-pre-plan capability inventory;
- I-MIG-001 manual-order authority migration receipt and semantic matrix;
- K-MIG-001 Command Center V2 migration receipt and component/read/mutation census;
- containment proposal;
- manual mutation-path ratchet.

Do not recreate these in a parallel architecture branch.

## PR #788 — inert Phase-1 contracts

**Current disposition:** **CURRENT CANONICAL CANDIDATE**

Contains current-master inert contracts for:

- A-04 domain/TradeIntent vocabulary;
- B-01 Instrument Master;
- H-01 risk-policy schema;
- I/OMS lifecycle;
- M-01 event envelope;
- N authorization evidence;
- route/migration/integration ratchets.

These remain non-authoritative until explicit contract adoption and authority migration.

## PR #789 — Master Product Plan + operator specification

**Current disposition:** **GOV-01 CURRENT PRODUCT CANDIDATE**

This is the proposed parent hierarchy, not yet adopted. GOV-01 Issue #791 is the explicit decision point.

## Research PRs #749 / #770

**Current disposition:** **RESEARCH HARVEST SOURCES**

- Preserve source integrity, PIT/causality, parity, Judge/research-ledger, and feature-evidence work.
- Do not merge research outputs directly into active strategy/execution authority merely to simplify the PR queue.
- C-01/C-02 should harvest proven research infrastructure after B-02/PIT dependencies are in place.

## Safety PRs #771 / #783 / #784

**Current disposition:** **RETAIN FOR INDEPENDENT SAFETY REVIEW / REBASE AS NEEDED**

These contain safety-semantic changes, including persisted safety-state behavior, indicator math affecting research/strategy semantics, and real-IB PAPER/operator evidence guards. They must not be auto-closed or rolled into a documentation adoption PR.

Any clean replacement must preserve exact safety intent, tests, and review class and receive required executed evidence.

## Immediate consolidation sequence

```text
#789 GOV-01 review packet
→ explicit ADOPT or REVISE decision
→ rebuild #775 as GOV-02 on current master
→ clean current-master harvest of #774 ADRs
→ clean narrow safety-governance harvest from #768
→ close stale #768/#772/#774/#775 only when their unique content is preserved
→ review/adopt #788 contracts authority-by-authority
→ execute I-MIG-001 / K-MIG-001 without creating parallel authorities
```

## Non-authorizing boundary

This crosswalk does not:

- merge or close any PR;
- change runtime configuration;
- change risk thresholds;
- alter broker routing;
- enable PAPER or LIVE execution;
- migrate any authority;
- grant capital authorization.
