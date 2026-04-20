---
repo: NousResearch/hermes-agent
url: https://github.com/NousResearch/hermes-agent
language: Python
license: MIT
analyzed_at: 2026-04-19
recommendation: partial-integrate
surfaces_with_value: [dev-tooling, docs]
shipped_related:
  - file: engine/utils/scheduler_safety.py
    surface: dev-tooling
    date: 2026-04-17
    what: "StaggeredCronRunner — deterministic per-job-id stagger + quiet-hours gate + dedupe window. Already shipped via garrytan/gbrain port (gbrain IS a Hermes adaptation). This dedups most of Hermes' cron-discipline value."
  - file: engine/notifications/supervisor.py
    surface: ops-messaging
    date: prior
    what: "SupervisorAgent already ports Hermes' marker state machine + ACK-terminal pattern. Cross-modal fallback also present."
---

# NousResearch/hermes-agent

## Core value proposition

Parent repo for Hermes — Nous Research's agent framework. Closed-loop
learning via 21 autonomous crons (data ingest → procedural memory → LLM
creates skills). Already partially adapted into jarvis-trader via
`engine/notifications/supervisor.py` (marker state machine) and via
`garrytan/gbrain` (which ported the scheduler-safety pattern).

## License

**MIT** — free to port with attribution.

## 9-surface grid

| # | Surface | Classification | Finding |
|---|---|---|---|
| 1 | Engine code | defer | Closed-loop learning requires persistent memory (vector embeddings + ingestion crons) — blocker on same architecture decision as gbrain analysis |
| 2 | Project rules | no-fit | No direct rule extraction |
| 3 | Skills | defer | Memory-search skill blocked on persistent-memory decision |
| 4 | Slash commands | no-fit | — |
| 5 | Subagents | dedup | Process-fork + RPC pattern doesn't match jarvis-trader's Agent SDK model |
| 6 | Docs | partial-integrate | Attribution + scheduler-discipline doc at `docs/strategy/scheduling-discipline.md` (S, 1h) |
| 7 | Dev tooling | **dedup** | Scheduler stagger / quiet-hours / idempotency heartbeat — **already shipped** via gbrain port (`engine/utils/scheduler_safety.py`). Add Hermes attribution only |
| 8 | Dashboard | no-fit | — |
| 9 | Ops / messaging | **dedup** | Multi-platform gateway (Telegram/Discord/Slack/WhatsApp/Signal) blocked on messaging-gateway roadmap; supervisor.py already has cross-modal fallback |

## Integration plan

1. **Attribution sweep** (S, 1h). Add `Pattern source: NousResearch/hermes-agent
   (MIT)` header to `engine/utils/scheduler_safety.py` and
   `engine/notifications/supervisor.py` noting the Hermes lineage (both were
   originally attributed to gbrain / Graeme — Hermes is the upstream source).
2. **Doc** (S, 1h). `docs/strategy/scheduling-discipline.md` — synthesize
   the cron discipline pattern.
3. **[DEFERRED]** Memory-search skill + multi-platform gateway — gated on
   the persistent-memory architecture decision (same blocker flagged in
   `garrytan__gbrain.md`).

## Red flags

- **Stateless vs stateful**: Hermes' value depends on persistent data
  ingestion. jarvis-trader is largely stateless between sessions.
- **Subagent model mismatch**: Hermes uses fork+RPC; jarvis-trader uses
  Agent SDK sequential/parallel stages. Don't try to port the subagent
  shell — port the patterns (markers, stagger, quiet-hours) only.
- **Attribution debt**: multiple files derived from Hermes via intermediate
  repos (gbrain). Address in the attribution sweep.

## Effort

Attribution + doc: **S (2h)**. Deferred items: blocked on architecture.
