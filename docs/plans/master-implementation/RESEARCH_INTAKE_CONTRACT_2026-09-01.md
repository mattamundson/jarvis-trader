# Research Intake Contract

## Purpose

The Command Center Research Intake panel must show open PRs, issues, experiments, spikes, and backlog items as intake only. These rows must never imply production readiness or trade authorization.

## Source Files

| Source | Role | Contract Status |
|---|---|---|
| `docs/plans/master-implementation/PR_ISSUE_SPIKE_DISPOSITION_2026-09-01.md` | Current PR, issue, and spike disposition matrix | Canonical planning source |
| `docs/plans/master-implementation/IMPLEMENTATION_BACKLOG.json` | Ranked implementation backlog and blocker state | Canonical backlog source |
| `docs/plans/master-implementation/COMMAND_CENTER_IMPLEMENTATION_TICKETS_2026-09-01.md` | Command Center panel acceptance and safety notes | Canonical product source |
| `GET /strategy/research-candidates` | X-bookmark edge-scan research verdicts | Existing engine source |
| `dashboard/app/research-log/page.tsx` | Existing research-log UI surface | Reference consumer |

## Normalized Row Shape

Any future `/strategy/research-intake` endpoint or generated dashboard fixture should normalize source rows into this shape:

```json
{
  "id": "pr-754",
  "kind": "pr",
  "title": "Command Center V2 paper trading control plane",
  "source": {
    "system": "github",
    "ref": "#754",
    "branch": "feature/command-center-v2-paper",
    "url": "https://github.com/mattamundson/jarvis-trader/pull/754"
  },
  "status": "open",
  "classification": "Command Center reference spike",
  "disposition": "reference",
  "phase": "Phase 5",
  "readiness_impact": "none",
  "next_action": "Extract API contracts, UI lessons, and safety constraints into the Command Center build.",
  "evidence": [
    "docs/plans/master-implementation/PR_ISSUE_SPIKE_DISPOSITION_2026-09-01.md"
  ],
  "updated_at": "2026-09-01"
}
```

## Allowed Kinds

- `pr`
- `issue`
- `experiment`
- `spike`
- `backlog`
- `research_verdict`

## Allowed Dispositions

- `keep`: retain as an active tracked item.
- `split`: separate mixed scope before adoption.
- `replace`: supersede with a cleaner implementation.
- `reference`: mine for lessons, contracts, tests, or UI ideas.
- `retire_to_archive`: archive after a replacement or superseding plan exists.
- `defer`: keep visible but outside the active high-ROI path.

## UI Rules

- Research Intake rows must render as `intake`, `reference`, `defer`, or `archive-planned`.
- Research Intake rows must not set `APPROVED`, `ACTIVE`, `PASS`, or any readiness badge used by live eligibility or strategy-ledger panels.
- GitHub metadata unavailable must render as `metadata unavailable`, not as an empty success state.
- Empty input must render `No open research items.`
- `readiness_impact` must be `none` unless a later task creates an explicit promotion contract and test coverage.

## Initial Normalized Rows

| ID | Kind | Disposition | Classification | Next Action |
|---|---|---|---|---|
| `pr-749` | `pr` | `keep` | Research foundation candidate | Inspect failing checks, run focused feature-registry/parity tests, then decide whether Phase 2 adopts it. |
| `pr-754` | `pr` | `reference` | Command Center reference spike | Extract API contracts, UI lessons, and safety constraints into Phase 5. |
| `pr-756` | `pr` | `reference` | Trade-intent / OMS reference spike | Extract lifecycle and idempotency concepts after the OMS contract is approved. |
| `pr-755` | `pr` | `keep` | Source-parity safety review | Inspect CI failures and rerun affected local checks before merge consideration. |
| `issue-750` | `issue` | `keep` | Feature-governance hardening | Execute and harden PR #749 feature-integrity suite. |
| `issue-751` | `issue` | `keep` | Validation defect | Write acceptance and patch the Initial Balance PIT leak. |
| `issue-752` | `issue` | `keep` | Validation defect | Write acceptance and patch VWAP premarket/session semantics. |
| `issue-753` | `issue` | `keep` | Command Center product epic | Convert into a milestone-backed epic after GitHub write scope is approved. |
| `issue-310` | `issue` | `defer` | Advisory dashboard tile | Keep lower priority than trust, data, and risk surfaces. |

## P8-010 Dependency

Route consolidation can proceed after this contract because `/mission-control`, `/today`, and `/trust-pane` can be reviewed against a stable intake rule: research and reference material may inform the Command Center, but it cannot change readiness state.
