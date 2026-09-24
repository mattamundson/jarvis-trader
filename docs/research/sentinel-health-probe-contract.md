# Sentinel health probe contract

`jarvis-sentinel` is useful to JARVIS as an **observability and dead-man evidence source**, not as a trading decision engine.

This contract converts the repo-consolidation finding into a concrete boundary between JARVIS trading runtime, `home-scripts` machine ops, and any future Sentinel service.

## Source evidence

- `jarvis-sentinel` README: self-healing observability for Hermes, trading engine, Ollama, gbrain, LLM providers, independent alert channels, and a dead-man switch.
- `jarvis-sentinel` design spec: probe layers for providers, Hermes, Ollama, engine, gbrain, scheduled tasks, system, and guardian checks.
- `sentinel.example.yaml`: concrete probe cadence/config examples for passive Hermes brain-health, engine health, Ollama pinned-model checks, routing drift, delivery auth, heartbeat file, and out-of-band heartbeat URL.
- Existing JARVIS monitoring docs: Prometheus/Grafana metrics, kill-switch metrics, LLM cost metrics, and autonomous monitoring runbooks.

## Authority boundary

| Concern | Authority |
|---|---|
| Trade authorization, order routing, kill-switch state | JARVIS trading engine only |
| Machine-local service probes and Windows scheduled-task evidence | `home-scripts` / Sentinel-style ops |
| Out-of-band paging / dead-man heartbeat | Sentinel-style ops, never the trading engine |
| Strategy promotion | Strategy registry + gate-v2 evidence only |
| Incident notes / operator memory | second-brain / handoff ledger |

## Required probe contract

A health-probe bundle is admissible to JARVIS only if it declares:

1. `probe_id` and `authority_class`.
2. Component under observation: `engine`, `ib_gateway`, `hermes`, `ollama`, `gbrain`, `scheduled_task`, `delivery`, `system`, or `guardian`.
3. Evidence source: HTTP endpoint, local file, command output, log window, scheduler readback, or external heartbeat.
4. Cadence and freshness SLA.
5. Fail-closed behavior.
6. Whether the probe is **advisory**, **paging**, or **hard gate**.
7. Explicit non-actions: no order placement, no strategy promotion, no kill-switch reset, no live restart unless separately authorized.

## Recommended minimum JARVIS bundle

| Probe | Evidence | Action class |
|---|---|---|
| Engine health | `/health`, `/metrics`, and last pipeline timestamp | hard gate for routing visibility, not order creation |
| IB Gateway state | existing engine IB connection field | hard gate for live readiness |
| Kill switch | existing engine kill-switch metric/state | hard gate; never auto-reset |
| Feed freshness | latest bar/event age by active instrument | hard gate; stale data fails closed |
| PM2 dump secret posture | recursive dump scan for known session/env keys | paging + remediation ticket |
| Hermes brain-health | passive log-window cascade detection; optional active canary | paging, not trading input |
| Delivery path | Discord/SMS/toast auth/readiness | paging readiness |
| Dead-man heartbeat | local heartbeat plus off-machine monitor | paging readiness |

## JARVIS integration rule

JARVIS may display Sentinel-derived status and use hard-gate probe failures to **block** live/paper readiness. JARVIS must not let Sentinel-derived status approve, promote, or route a trade.

The safe direction is one-way: observability may veto readiness; it may not create permission.

## Loop recommendation

For workstation safety, Sentinel-style loops should use conservative cadences and local evidence first. Any recurring agentic loop must follow Amo's standing constraint: no more frequently than every 6 hours unless explicitly overridden. Low-level non-agent probes may be more frequent only when they are deterministic, cheap, and non-LLM.
