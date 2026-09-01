# Command Center Route Consolidation Plan

## Decision Rule

`/command-center` is the canonical first-screen operator shell. Other broad operator routes should either become drilldowns from that shell or redirect after their unique safety/context value has been migrated.

## Route Actions

| Route | Action | Final State | Risk Notes |
|---|---|---|---|
| `/mission-control` | Redirected after merge | `/mission-control` redirects to `/command-center?view=operations` | Parity is proven by focused route-consolidation E2E. |
| `/today` | Demoted to Daily Brief drilldown | Keep route as `/today` for the detailed chart and market/session context; Command Center owns the compact Daily Brief summary | Daily Brief first-screen facts are migrated; route remains useful as a detailed chart/context drilldown. |
| `/trust-pane` | Merge trust summary into Command Center; keep route as deep audit view | Keep route as `/trust-pane` until dual-system provenance and audit rows have a compact Command Center summary | [RISK] Immediate redirect would hide cross-system trust evidence, edge ledger detail, bar-quality context, and post-trade snippets that are too dense for the first screen. |

## Migration Checklist

1. Add Command Center drilldown links for `Operations`, `Daily Brief`, and `Trust Audit`.
2. Move `/mission-control` unique panels into Command Center or linked drilldowns. **Done:**
   - `TradingStatusReconciliation`
   - `RiskSafetyPanel`
   - `EngineDataPanel`
   - `EnvironmentFleetPanel`
3. Extract `/today` first-screen facts into Command Center. **Done:**
   - mode banner
   - engine/execution status
   - session trade counts
   - market context strip link
4. Extract `/trust-pane` first-screen facts into Command Center:
   - live/static provenance summary
   - edge-ledger summary
   - bar-quality summary
   - post-trade audit link
5. Add route-level tests proving. **Done:**
   - `/command-center` remains the canonical first screen.
   - `/mission-control` redirects only after parity.
   - `/today` and `/trust-pane` remain reachable as drilldowns.

## Mission-Control Redirect Readiness

Current status: **redirected**. `/command-center?view=operations` is implemented, the mission-control operational panels are mounted there, and `/mission-control` redirects to the canonical operations view.

Redirect target contract:

- `/mission-control` redirects only to `/command-center?view=operations`.
- The `operations` view is a real routable state, not an ignored query string.
- The redirected view preserves degraded-state visibility for each migrated panel.

Parity blockers before redirect:

| Blocker | Current owner | Required before redirect |
|---|---|---|
| Risk and kill-switch details | `components/command-center/operations/RiskSafetyPanel` | Done. Command Center operations view renders equivalent `/safety/status`, `/health`, and paper-position failure states. |
| Trading split-brain reconciliation | `components/TradingStatusReconciliation` | Done. Command Center operations view renders the reconciliation contract and does not collapse disagreement into a green aggregate. |
| Paper positions and performance | `components/command-center/operations/PositionsPerformancePanel` | Done. Command Center operations view shows unrealized positions, paper-performance degraded states, and unavailable-metric caveats. |
| Pipeline and scheduler visibility | `components/command-center/operations/SignalsPipelinePanel` | Done. Command Center operations view shows `/pipeline/status`, `/decisions/recent`, and `/scheduler/status` with offline and empty states. |
| Validation gates and strategy ledger | `components/command-center/operations/ValidationGatesPanel` | Done. Command Center operations view shows the same proactive validation and ledger readiness signals. |
| Engine and broker diagnostics | `components/command-center/operations/EngineDataPanel` | Done. Command Center operations view preserves health, broker-position, and stale/unknown diagnostics. |
| Local fleet and loop state | `components/command-center/operations/EnvironmentFleetPanel` | Done. Command Center operations view keeps `/api/fleet` visibility, including empty and unreachable states. |

Test gates before redirect:

- Route tests prove `/command-center?view=operations` renders the operations view directly.
- Route tests prove `/mission-control` redirects to `/command-center?view=operations`.
- Route tests prove `/today` and `/trust-pane` remain reachable after the mission-control redirect.
- Keep `pnpm run guards`, `pnpm run typecheck`, and the focused Command Center route-consolidation E2E green.

Post-redirect ownership:

- Pre-redirect route source is archived under `C:\Users\mattm\Archive\2026\jarvis-command-center-route-consolidation\`.
- Reusable operations panels are owned under `dashboard/components/command-center/operations`.
- `dashboard/app/mission-control/page.tsx` remains a redirect stub only.
- Primary and secondary Operations navigation targets `/command-center?view=operations`.
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
