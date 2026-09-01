# PR, Issue, And Spike Disposition - 2026-09-01

This matrix prevents pre-plan work from being mistaken for adopted implementation.

## Live GitHub Records Checked

Checked with `gh pr view` / `gh issue list` on 2026-09-01.

## Open PRs

| PR | Branch | State | Current Classification | Disposition |
|---|---|---|---|---|
| #749 `research: feature integrity registry and golden-vector parity` | `research/feature-integrity-v2` | draft, unstable checks | Research foundation candidate | Keep open as spike. Next: inspect failing checks, run local focused feature-registry/parity tests, and decide whether to adopt into Phase 2. |
| #754 `feat: Command Center V2 paper trading control plane` | `feature/command-center-v2-paper` | draft, unstable checks | Command Center reference spike | Do not merge as final product. Extract API contracts, UI lessons, and safety constraints into Phase 5 Command Center build. |
| #756 `feat: paper trade-intent preview and submission foundation` | `feature/trade-intent-paper-api` | draft, unstable checks | Trade-intent / OMS reference spike | Do not merge as final OMS. Extract intent lifecycle and idempotency concepts after OMS contract is approved. |
| #755 `[safety-review] indicators.py: restore Saty Phase Oscillator EMA3 smoothing` | `safety-review/phase-ema3-smoothing` | open, unstable checks | Source-parity safety-review candidate | Highest near-term research correctness PR. Next: inspect CI failures, re-run affected local checks, decide merge only after validation evidence. |

## Open Issues

| Issue | Title | Plan Mapping | Disposition |
|---|---|---|---|
| #750 | Research: execute and harden PR #749 feature-integrity suite | Phase 2 / M1 | Keep. This is the immediate hardening task for feature governance. |
| #751 | Validation defect: current Initial Balance backfills completed IB into premarket bars | Phase 2 / M2 / M3 | Keep. This is a real PIT leak and must fail closed before any strategy using IB evidence can promote. |
| #752 | Validation defect: VWAP gate path can trade premarket on near-continuous Globex cache | Phase 2 / M2 / M3 | Keep. This is a real session-semantics defect and must be fixed before VWAP promotion. |
| #753 | Command Center V2: real-time paper trading control plane | Phase 5 / M5 | Keep as product epic; implementation should follow this master plan, not PR #754 alone. |
| #310 | Dashboard: ES auction / overnight-bias card (advisory) | Phase 5 or later | Defer. Useful advisory tile, lower ROI than trust/data/risk spine. |

## Spike Policy

- A spike can be mined for code, tests, design, and lessons.
- A spike is not complete implementation.
- A spike may be closed, rewritten, cherry-picked, or adopted only after the relevant milestone gate exists.
- Failed CI on a spike is not automatically a production blocker unless the plan adopts that spike.

## Next Disposition Actions

1. Inspect PR #755 CI failure logs and local reproducibility.
2. Inspect PR #749 failure logs and identify whether failures are code, CI environment, or unrelated dashboard quality gates.
3. Create a compact route/API inventory before touching Command Center implementation.
4. Write acceptance criteria for #751 and #752 before patching.
5. Convert #753 into a milestone-backed epic if GitHub issue editing is approved in a later pass.

