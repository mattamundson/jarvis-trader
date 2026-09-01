# Command Center Route Consolidation Plan

## Decision Rule

`/command-center` is the canonical first-screen operator shell. Other broad operator routes should either become drilldowns from that shell or redirect after their unique safety/context value has been migrated.

## Route Actions

| Route | Action | Final State | Risk Notes |
|---|---|---|---|
| `/mission-control` | Merge into Command Center, then redirect | `/mission-control` redirects to `/command-center?view=operations` after parity checks | [RISK] Immediate redirect would hide Environment Fleet, split-brain reconciliation, and several mature degraded-state panels that are not yet first-class in `/command-center`. |
| `/today` | Demote to Daily Brief drilldown | Keep route as `/today` for the market/session brief; link from Command Center instead of treating it as a competing first screen | [RISK] Immediate redirect would drop live chart context, market context strip, and session metrics that are useful but not command authority. |
| `/trust-pane` | Merge trust summary into Command Center; keep route as deep audit view | Keep route as `/trust-pane` until dual-system provenance and audit rows have a compact Command Center summary | [RISK] Immediate redirect would hide cross-system trust evidence, edge ledger detail, bar-quality context, and post-trade snippets that are too dense for the first screen. |

## Migration Checklist

1. Add Command Center drilldown links for `Operations`, `Daily Brief`, and `Trust Audit`.
2. Move `/mission-control` unique panels into Command Center or linked drilldowns:
   - `TradingStatusReconciliation`
   - `RiskSafetyPanel`
   - `EngineDataPanel`
   - `EnvironmentFleetPanel`
3. Extract `/today` first-screen facts into Command Center:
   - mode banner
   - engine/execution status
   - session trade counts
   - market context strip link
4. Extract `/trust-pane` first-screen facts into Command Center:
   - live/static provenance summary
   - edge-ledger summary
   - bar-quality summary
   - post-trade audit link
5. Add route-level tests proving:
   - `/command-center` remains the canonical first screen.
   - `/mission-control` redirects only after parity.
   - `/today` and `/trust-pane` remain reachable as drilldowns.

## Mission-Control Redirect Readiness

Current status: **not ready to redirect**. `/command-center` exposes the summary layer and drilldown links, but `/mission-control` still owns full operational panels and `/command-center?view=operations` is not implemented.

Redirect target contract:

- `/mission-control` may redirect only to `/command-center?view=operations`.
- The `operations` view must be a real routable state, not an ignored query string.
- The redirected view must preserve degraded-state visibility for each migrated panel.

Parity blockers before redirect:

| Blocker | Current owner | Required before redirect |
|---|---|---|
| Risk and kill-switch details | `/mission-control` `RiskSafetyPanel` | Command Center operations view renders equivalent `/safety/status`, `/health`, and paper-position failure states. |
| Trading split-brain reconciliation | `/mission-control` `TradingStatusReconciliation` | Command Center operations view renders the reconciliation contract and does not collapse disagreement into a green aggregate. |
| Paper positions and performance | `/mission-control` `PositionsPerformancePanel` | Command Center operations view shows unrealized positions, paper-performance degraded states, and unavailable-metric caveats. |
| Pipeline and scheduler visibility | `/mission-control` `SignalsPipelinePanel` | Command Center operations view shows `/pipeline/status`, `/decisions/recent`, and `/scheduler/status` with offline and empty states. |
| Validation gates and strategy ledger | `/mission-control` `ValidationGatesPanel` | Command Center operations view shows the same proactive validation and ledger readiness signals, or links to a retained drilldown with no loss of authority context. |
| Engine and broker diagnostics | `/mission-control` `EngineDataPanel` | Command Center operations view preserves health, broker-position, and stale/unknown diagnostics. |
| Local fleet and loop state | `/mission-control` `EnvironmentFleetPanel` | Command Center operations view keeps `/api/fleet` visibility, including empty and unreachable states. |

Test gates before redirect:

- Add a route test proving `/command-center?view=operations` renders the operations view directly.
- Add a route test proving `/mission-control` redirects to `/command-center?view=operations` only after the parity blockers above are closed.
- Keep the existing route-consolidation test proving `/mission-control` remains reachable until redirect readiness is explicitly completed.
- Keep `pnpm run guards`, `pnpm run typecheck`, and the focused Command Center route-consolidation E2E green.

Non-blocking cleanup after redirect:

- Archive retired route-only code under `C:\Users\mattm\Archive\2026\jarvis-command-center-route-consolidation\`.
- Remove primary navigation to `/mission-control`; keep a contextual Operations drilldown only if the operations view remains separate inside Command Center.
- Preserve `/today` and `/trust-pane` as drilldowns until their own parity plans close.

## Sidebar/Nav Policy

- Primary nav should point to `/command-center` for the operator shell.
- `/mission-control` should leave primary nav after parity and redirect.
- `/today` should appear as a secondary Daily Brief link.
- `/trust-pane` should appear as a secondary Trust Audit link.

## Non-Goals

- Do not remove files during consolidation; archive retired route code under `C:\Users\mattm\Archive\2026\jarvis-command-center-route-consolidation\` if a future task retires a route.
- Do not merge research intake, strategy readiness, or trust evidence into trade authorization without backend-owned gating fields.
- Do not replace detailed drilldowns with first-screen cards if the detail is still needed for diagnosis.
