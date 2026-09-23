# Sentinel / Observability Runbook Consolidation

**Status:** draft · **Owner:** ops + strategy-research · **Audience:** operators, on-call, strategy researchers, agent workflow authors  
**Scope:** one place for the JARVIS health and observability probes that matter — IB Gateway, engine, dashboard, PM2 dump secret hygiene, feed freshness, paper order drift, kill-switch state — with machine-readable evidence on every probe.

> This runbook consolidates the Sentinel-style probe concepts from `jarvis-sentinel`, `jarvis-mission-control`, and the existing `home-scripts` hygiene tooling into one living doc. It is the contract for what we probe, how often, what evidence we keep, and who acts on it. It is not a third always-on process unless a clear PM2/scheduled-task owner emerges.

---

## 1. Why consolidate

Across the JARVIS ecosystem there are several overlapping ideas about health and observability:

- `jarvis-sentinel`: deadman/probe concepts for the trading system.
- `jarvis-mission-control`: durable, evidence-driven control plane ideas.
- `home-scripts`: Windows/Hermes/JARVIS maintenance and audit scripts.
- Engine health router and dashboard readiness checks: runtime probes already in the product.

Consolidation means one doc that says what each probe is for, how it emits evidence, and where the evidence lands — so we stop maintaining three vague "monitoring" ideas and start maintaining one probe set with clear ownership.

---

## 2. Probe inventory

Each probe below has: what it checks, expected healthy state, evidence artifact, cadence, and owner.

### 2.1 IB Gateway

- **What:** IB Gateway is reachable and responding on its expected port; connection state is as expected for the current mode (paper/live, connected/disconnected).
- **Healthy:** gateway heartbeat/connectivity check passes; no unexplained disconnect streak.
- **Evidence:** probe result with timestamp, connectivity verdict, and any retry/drift note.
- **Cadence:** sufficient for the operating mode (e.g. frequent enough to catch a dropout before the next decision cycle).
- **Owner:** engine + ops; the engine's own IB connectivity watchdog is the first line.

### 2.2 Engine

- **What:** core engine service is up, health endpoint responds, critical routes are reachable, and the runtime snapshot reflects the expected state.
- **Healthy:** `/health` or equivalent returns the expected provider/runtime snapshot; no unexplained degradation in the snapshot panel.
- **Evidence:** health snapshot and any degradation note attached to the probe run.
- **Cadence:** aligned with the dashboard/runtime snapshot refresh cycle and any on-demand checks before sensitive operations.
- **Owner:** engine + dashboard.

### 2.3 Dashboard

- **What:** dashboard is reachable, key widgets render, and the master-api bridge (if used) is in the expected state.
- **Healthy:** dashboard loads, Mission Control/runtime panels render, master-api unreachable state is only present when expected.
- **Evidence:** render-state note or readiness check result.
- **Cadence:** on deploy, on restart, and before any review that depends on dashboard state.
- **Owner:** dashboard.

### 2.4 PM2 dump secret hygiene

- **What:** the PM2 process dump does not leak live secrets; the loaded env in the dump is consistent with the expectation that apps load secrets from their own `.env` (with `load_dotenv` override), not from the shell that started them.
- **Healthy:** dump inspection shows no plaintext secret where it should not be; apps still load config from their own env files.
- **Evidence:** dump inspection result, ideally machine-readable, with the fields checked and the verdict.
- **Cadence:** on PM2 restart/save, and on a periodic hygiene run.
- **Owner:** ops. The existing `verify_dump.py` (32-key recursive check) is the canonical checker here.

### 2.5 Feed freshness

- **What:** each data feed used by active strategies is within its freshness gate; stale feeds are flagged rather than silently used.
- **Healthy:** all feeds used by current strategies are within their freshness gate; any stale feed is annotated with how old it is and which strategies it affects.
- **Evidence:** freshness report with per-feed age, gate, and affected strategies.
- **Cadence:** before any decision cycle that depends on the feed, and on a periodic background check.
- **Owner:** data + strategy researchers.

### 2.6 Paper order drift

- **What:** paper-mode orders and fills behave as expected relative to the configured paper/live boundary; no unexpected drift between paper behavior and the documented paper contract.
- **Healthy:** paper orders follow the documented paper contract; any deviation is flagged and investigated.
- **Evidence:** probe result with the contract checked and any drift noted.
- **Cadence:** sufficient to catch drift before it is mistaken for a strategy signal.
- **Owner:** engine + strategy researchers.

### 2.7 Kill-switch state

- **What:** the kill-switch state is what we think it is; no component is acting as if the kill-switch is off when it is on, or vice versa.
- **Healthy:** kill-switch state is consistent across the components that read it; any disagreement is flagged immediately.
- **Evidence:** kill-switch state read from each relevant component, with a consistency verdict.
- **Cadence:** before any sensitive operation and on any state change.
- **Owner:** engine + ops. This is a safety-critical probe; it gets the strictest evidence standard.

---

## 3. Evidence contract

Every probe emits machine-readable evidence. "Looks fine" is not evidence.

Minimum evidence for each probe run:

- `probe_id` — stable identifier for the probe.
- `timestamp` — when the probe ran.
- `verdict` — healthy / degraded / unhealthy / skipped.
- `authority_class` — advisory / paging / hard-gate (from `sentinel-health-probe-contract.md:24-34`).
- `fail_closed` — whether the probe fails closed (e.g. stale feed → treat as no data, not as "ok").
- `action_class` — what the probe is allowed to do (e.g. block readiness, page, log only).
- `explicit_non_actions` — what the probe must NOT do (e.g. no order placement, no kill-switch reset, no strategy promotion).
- `observed` — what was actually observed (concrete values, not narratives).
- `expectation` — what healthy means for this probe.
- `note` — optional human context.
- `affected` — optional list of strategies, workflows, or components affected by a degraded/unhealthy verdict.

Evidence lands where the relevant consumer can use it: engine logs, dashboard state, the ops hygiene log, or the strategy record, depending on the probe. The point is that each probe's evidence is stored, not just printed.

---

## 4. Ownership and silence

- Every probe has exactly **one** owner for interpretation and response. When multiple components contribute to a probe (e.g. engine + ops, engine + dashboard, data + strategy researchers), designate one responding owner and list the other components separately as contributors. During an incident, both groups must not be able to assume the other owns the response.
- A probe that has been healthy for a documented stretch may run less often, but it does not become "someone's memory."
- A probe that cannot run (e.g. IAM/refreshed key missing, feed down) is itself an evidence event: skipped with a reason, not silently omitted.

---

## 5. No third always-on process without an owner

The audit's Wave 1 note was explicit: avoid maintaining a third always-on process unless it has a clear PM2 or scheduled-task owner. This runbook does not create one by default.

- If a probe is cheap and high-value, run it from the existing engine health path, dashboard readiness path, or a scheduled script in `home-scripts`.
- If a probe needs its own daemon, propose the owner, the failure mode, and the restart policy before it becomes a permanent process.

---

## 6. Related

- Backtest critique checklist: `docs/research/backtest-critique-checklist.md`
- Strategy registry schema: `docs/research/strategy-registry-schema.md`
- Chart review runbook: `docs/research/chart-review-runbook.md`
- Macro/FRED regime-context spec: `docs/research/macro-regime-context-spec.md`
- Source concepts: `jarvis-sentinel`, `jarvis-mission-control` (existing repos; this runbook consolidates their probe ideas, not their entire codebases)
- Existing engine health router, dashboard runtime snapshot, and `home-scripts` hygiene tooling
- PM2 dump secret hygiene: existing `verify_dump.py` and related ops scripts

---

*This runbook consolidates probe concepts from existing repos into one doc. It does not replace any probe's implementation; it defines the contract those implementations should meet.*
