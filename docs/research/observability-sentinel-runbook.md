# Observability and sentinel runbook consolidation

**Status:** draft · **Owner:** JARVIS ops · **Related:** `REPO_AUTHORITY.md` (master-jarvis), `docs/research/strategy-registry.md`

A consolidation of sentinel-style observability concepts from the reference skills into a single JARVIS-native runbook. Not vendored — patterns extracted, runbook written fresh.

## Purpose

Define the probes, alerts, and evidence contract that keep the JARVIS trading system observable: IB Gateway, engine, dashboard, PM2 dump secret hygiene, feed freshness, paper order drift, and kill-switch state. Every probe emits machine-readable evidence, not just "look at this."

Inspired by `mattamundson/claude-trading-skills/skills/drawdown-circuit-breaker`, `pre-trade-discipline-gate`, and `position-sizer`.

## Probe inventory

### IB Gateway health

- **What:** IB Gateway connection state, API responsiveness, contract/order reachability.
- **How often:** heartbeat interval appropriate to live/paper state (more frequent in live).
- **Evidence:** connection state, latency, last successful API call timestamp.
- **Escalation:** dead gateway → alert + paper/live pause per execution policy.

### Engine health

- **What:** engine process alive, event loop not stalled, memory/CPU within bounds, no deadlock indicators.
- **Evidence:** process state, event-loop lag, resource usage, last processed event timestamp.
- **Escalation:** stalled engine → alert; if live, treat as kill-switch-adjacent event.

### Dashboard health

- **What:** dashboard service reachable, API routes responding, runtime snapshot endpoint healthy.
- **Evidence:** HTTP status, latency, key endpoint responses.
- **Escalation:** stale dashboard → degraded observability alert; not necessarily a trading stop, but a visibility problem.

### PM2 dump secret hygiene

- **What:** periodic check that PM2 dump (`~/.pm2/dump.pm2`) does not contain plaintext secrets leaked from environment.
- **Why:** agent-session shells export `SUPABASE_PAT`, `DISCORD_WEBHOOK_URL`, `JARVIS_LOOP_WEBHOOK`, `SENTINEL_DISCORD_WEBHOOK`, etc. Starting PM2 from those shells or running `pm2 save` leaks them into the dump.
- **Evidence:** list of suspicious keys found (or clean), last check timestamp, dump file hash.
- **Remediation:** clean-shell restart; verify dump with the dump verification script.
- **Note:** PM2 apps load real secrets from their own `.env` (engine `config.py: load_dotenv(override=True)`), so clean-shell restarts are safe.

### Feed freshness

- **What:** data feeds (Databento/IBKR/YFinance/FRED/CSV) are alive and recent, with freshness and provenance columns.
- **Evidence:** last update timestamp per feed, staleness flag, provenance note.
- **Escalation:** stale feed → strategy that depends on it is flagged; macro features with stale data must flag themselves stale (see `macro-fred-regime-context-spec.md`).

### Paper order drift

- **What:** paper-simulation orders, fills, and state tracked so paper behavior can be compared to expected/backtested behavior.
- **Evidence:** paper order log, fill discrepancies, drift metric.
- **Escalation:** paper fill drift beyond tolerance → investigate before promoting paper results.

### Kill-switch state

- **What:** kill-switch is queryable, its current state is known, and probes confirm it is reachable and responsive.
- **Evidence:** kill-switch state, last state change, last successful query.
- **Escalation:** kill-switch unreachable or unresponsive → treat as a risk event; do not assume it is off.

## Alert contract

Every probe emits:

- `probe_name`
- `timestamp`
- `state` (ok / degraded / down / stale / drift / secret_leak)
- `evidence` (machine-readable payload, not prose)
- `escalation` (what happens if state is not ok)

Alerts are machine-readable first; human-readable notification is secondary.

## Runbook ownership

- Probes are owned by the service they observe (engine owns engine probes, dashboard owns dashboard probes, etc.) where possible.
- `home-scripts` owns Windows/Hermes/JARVIS operational probes (PM2 dump hygiene, scheduled-task health) where no product service owns them.
- `master-jarvis` owns cross-domain routing/observation where it coordinates rather than executes.

## Relationship to strategy registry

A strategy in `live_eligible` or `live` state must have its kill-switch, paper drift, and relevant feed freshness probes wired into its promotion record. A probe failure that affects a live strategy is a promotion-record event, not just a generic alert.

## Source notes

Distilled from `mattamundson/claude-trading-skills/skills/drawdown-circuit-breaker/SKILL.md`, `pre-trade-discipline-gate/SKILL.md`, and `position-sizer/SKILL.md` (discipline, risk, and sizing concepts), and the audit report's observability recommendation. Not vendored.
