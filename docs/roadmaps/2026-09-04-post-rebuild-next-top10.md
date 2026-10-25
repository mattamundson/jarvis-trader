# JARVIS Next Top 10 ROI Queue — Post-Rebuild (2026-09-04)

**Goal (next hour):** convert the rebuilt, runtime-green canonical dashboard into a decision-ready cutover state: inventory what must be preserved, audit PM2 bindings, and produce literal cutover/rollback commands from the verified authority candidate — without touching engine/risk/kill-switch state.

**Strategy:** safety boundary unchanged (no live trading/risk/kill-switch mutations). The serving boundary is green and `source_integrity` passes 2/2, so the frontier is deploy-authority normalization, not incident response. Prefer read-only audits and durable artifacts; any cutover executes only with an explicit preservation inventory and rollback commands in hand.

## Top 10 ROI tasks

1. Capture the canonical preservation inventory: enumerate deploy-only artifacts (`.env`, `.env.local`, `.next`, `logs/`, `phase0_runtime_truth_snapshot.json`, scheduled-task state, PM2 dump) that a cutover must carry over. [RISK]
2. Complete the PM2 binding audit: confirm `jarvis-dashboard` and `jarvis-engine` script/cwd/env paths in the live PM2 daemon match the canonical ecosystem configs exactly.
3. Write literal cutover commands (no placeholders) to rebind `jarvis-dashboard` to the authority candidate build, plus matching rollback commands. [RISK]
4. Dry-run the authority candidate on a non-production port (e.g. 3014) with canonical `.env.local` auth inputs and verify Basic Auth + `/api/runtime-snapshot` there.
5. Rotate/archive the stale PM2 dashboard error log (2.5MB of pre-build restart-storm noise) so future triage reads current truth.
6. Decide PR #779 disposition: keep blocked on GitHub Actions billing or promote as local-verification-only emergency merge candidate (requires Amo call).
7. Stage the `[safety-review]` provenance note for the earlier `engine/.env` restoration — documentation only, zero runtime value changes.
8. Add a `pnpm run verify:serving` script to the canonical dashboard that runs the secret-safe boundary probe (401/200 split + runtime-snapshot + engine-health + tailnet) as one command.
9. Schedule a rolling runtime-evidence capture (reuse `jarvis_runtime_evidence_bundle.py`) so post-cutover drift has a comparison baseline.
10. Re-rank the queue after items 1–4 land: execute the cutover if the packet is complete, else move to the next deploy-authority item.

## Recommended immediate next action

Start task 1 (preservation inventory) — it is read-only, gates every later cutover step, and has the highest information value per unit of risk.
