# Infra Module Synthesis

**Source digest**: `C:\Users\mattm\discord-export\digest-raw\by-module\infra.json` (1 item, 2026-04-12)
**Touch points**: `engine/main.py`, `engine/scripts/`, CI, `.mcp.json`

---

## Item 1 — joeynyc/hermes-hud (TUI consciousness monitor)

- **URL**: https://github.com/joeynyc/hermes-hud
- **Stack**: Python 3.11+, Textual TUI, reads from `~/.hermes/` data dir
- **What it is**: Terminal dashboard for the Hermes agent. 9 tabs surfacing memory, mistakes, corrections, cron history, health checks, project state, tmux operator view, prompt patterns. Snapshot diffs for day-over-day growth tracking.

### Cross-ref against jarvis-trader infra

| Hermes HUD feature | Closest jarvis-trader analog | Gap |
|---|---|---|
| Cron Monitor (jobs + exec history) | `engine/main.py:1410-1463` APScheduler (morning brief, Saturday discovery, EOD) + WSL `/root/.openclaw/cron/jobs.json` | No unified live view. Status scattered across PM2 logs + WhatsApp deliveries + `openclaw_notifier`. |
| Health Checks (keys, services, gateway) | `/health` endpoint, `port_guardian.py`, manual `netstat` for PM2 orphan hunts | No terminal dashboard. Diagnosing the 1,248-restart crash-loop required hand-rolled commands. |
| Corrections Log (mistakes + learnings) | `AgentFeedbackTracker` (`trade_outcomes` SQLite), ICWeightedEnsemble 30-day window, `patterns.py` feedback loop | Data is captured; there is no surface. Matt reads it via direct SQL or pipeline logs. |
| Snapshot Diffs (what changed since yesterday) | None. Session handoffs (`docs/session-logs/`) are manual YAML. | Fit for Obsidian vault standup flow too. |
| tmux Operator View (panes → agents → approval queue) | PM2 list + WhatsApp approval inbox | Parallel-agent standing order (10 concurrent) would benefit most; no single pane of glass today. |
| Prompt Patterns (clustering, peak hours, tool chains) | Nothing equivalent. Closest is TokenProxy cache stats. | Useful for cost monitoring given Opus Advisor tier. |

### Fit rating: **Medium — inspiration, not adoption**

Hermes HUD is bound to Hermes' `~/.hermes/` schema (agent profiles, conversations, skills). Direct install on jarvis-trader would read nothing. Windows support is not listed (macOS/Linux only), so Matt would run it in WSL at best.

### Actionable takeaways (no code changes this pass)

1. **TUI as a lens for existing data**: every jarvis-trader signal Hermes HUD shows already exists — it is a visualization problem, not a data problem. Natural home: a new `/status/dashboard` TUI fed by existing `/health`, `/portfolio`, AgentFeedbackTracker, and APScheduler introspection. Textual framework is pnpm-free pure Python, fits `engine/.venv`.
2. **Snapshot diff pattern pairs with Obsidian vault**: `hermes-hud --snapshot` → daily JSON written to vault; session-scribe agent already stubbed (`~/.claude/`). Closes the "hooks fire but don't close the loop" gap flagged in memory for the second-brain vault.
3. **PM2 orphan detection belongs in a health tab**: the 2026-04-14 port-8010 incident (`netstat -ano | grep :8010`, kill orphan, restart) is exactly the "Health Checks" surface Hermes HUD exposes. Worth porting the detection logic from `port_guardian.py` into a readable status row.
4. **No MCP angle**: Hermes HUD is a read-only consumer, not an MCP server. Does not extend `.mcp.json`.

### Priority: **P3 — file under future quality-of-life**

Jarvis-trader's P0/P1 queue (MCL inverted stop, Polygon futures blocklist, dashboard offline, Bayesian engine restart) outranks a TUI rebuild. Revisit after paper-trading greenlight.

---

**Output**: `C:\Users\mattm\ThinkorSwim\jarvis-trader\docs\digest\infra-synthesis.md`
