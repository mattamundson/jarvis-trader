# JARVIS Repo Consolidation — Inventory and Disposition Log

**Status:** wave 2.5 complete · **Author:** Hermes Agent cron run · **Date:** 2026-09-21
**Purpose:** one row per repo in the 2026-09-12 audit consolidation map, with verified disposition.
**Companion docs:** `docs/research/strategy-registry-schema.md`, `docs/research/backtest-critique-checklist.md`,
`docs/research/chart-review-runbook.md`, `docs/research/macro-regime-context-spec.md`,
`docs/research/sentinel-observability-runbook.md` (PR #906, merged 2026-09-22).
**Provenance:** `GITHUB_REPO_CONSOLIDATION_TRADING_AUDIT_2026-09-12.md` (2026-09-12 audit),
`HANDOFF_2026-09-12_github-repo-consolidation-wave1.md` (Wave 1 handoff).

> This inventory is the audit's Wave 3 item: "Convert repo sprawl into a searchable inventory note
> in `second-brain`: one row per repo, authority status, last reviewed date, and 'mine/merge/archive' disposition."
> It lives in `jarvis-trader/docs/research/` as the canonical trading-system copy; `master-jarvis/REPO_AUTHORITY.md`
> is the cross-domain umbrella that points here.

---

## 1. Consolidation architecture (unchanged from audit)

| System of record | Role | What lives here now |
|---|---|---|
| `jarvis-trader` | Canonical trading system | Engine, dashboard, strategies, backtests, execution/risk gates, tests, trading agent commands, Wave 1 + Wave 2 research docs |
| `master-jarvis` | Cross-domain operator/API | Business + trading intent routing, `REPO_AUTHORITY.md`, no duplicate trading execution logic |
| `second-brain` | Research/journal/decision memory | Market notes, Discord bias archive, strategy reviews, lessons, postmortems, prompts, checklists |
| `home-scripts` | Machine ops | Windows scheduled tasks, backup scripts, PM2 hygiene, git worktree hygiene, environment audits, Sentinel-style probe scripts |
| `hermes-state` | Encrypted disaster recovery | Backup of Hermes state/secrets/skills, not an active dev surface |
| `amo-arbitrage` | Separate commodity research product | Separate asset class/product surface; bridgeable via adapters, not merged into futures JARVIS |

---

## 2. Disposition table — every repo in the audit map

### 2.1 Canonical keep / system-of-record

| Repo | Disposition | Action taken | Verified |
|---|---|---|---|
| `mattamundson/jarvis-trader` | Keep — canonical trading system | PRs #816 (Wave 1) and #895 (Wave 2) merged/open; topics `canonical-system`, `trading-system` applied | ✓ Push 2026-09-12; topics read back |
| `mattamundson/master-jarvis` | Keep — cross-domain operator | PR #6 (Wave 1) merged; `REPO_AUTHORITY.md` added; topics `canonical-system`, `orchestration`, `repo-authority` applied | ✓ Push 2026-09-11; topics read back |
| `mattamundson/second-brain` | Keep — research/journal authority | No changes this wave; remains canonical for journal/research memory | ✓ Pushed 2026-09-11 |
| `mattamundson/hermes-state` | Keep — encrypted DR backup | No changes this wave; remains canonical for encrypted disaster recovery | ✓ Pushed 2026-09-12 |
| `mattamundson/home-scripts` | Keep — machine ops | No changes this wave; owns `jarvis_data_integrity_sentinel.py` and all scheduled-task hygiene | ✓ Pushed 2026-09-11 |

### 2.2 Folded into jarvis-trader (Wave 1 — code/docs imported, source archived)

| Repo | Disposition | Action taken | Verified |
|---|---|---|---|
| `mattamundson/jarvis-quant` | Folded → `jarvis-trader` + archived | `engine/research/imported/jarvis-quant/**` (non-production IBKR learning sandbox, parquet snapshots skipped); `docs/research/imported-repos/2026-09-12-wave1/README.md` provenance record | ✓ Archived true |
| `mattamundson/jarvis-positions-check` | Folded → `jarvis-trader` + archived | `engine/scripts/check_positions.py` (sanitized, reads `JARVIS_API_KEY`/`API_KEY` or `--api-key`, no embedded secret); `engine/tests/test_check_positions_script.py`; provenance in Wave 1 README | ✓ Archived true |
| `mattamundson/autotrade` | Folded → `jarvis-trader` + archived | `docs/research/llm_strategy_iteration/` (LLM strategy-iteration loop docs, source references; `.env.example` and lockfile skipped); provenance in Wave 1 README | ✓ Archived true |

### 2.3 Folded into master-jarvis or second-brain via docs/provenance (agent/ops — no code move)

> Operating rule: consolidate agent/ops only through docs/provenance unless a repo has a clean, obvious reusable
> script. The one clean script — `jarvis_data_integrity_sentinel.py` — already lives in `home-scripts` and is the
> deployed observability asset. The 13 repos below are recorded as consolidated via topics + this inventory note;
> no third always-on process was created.

| Repo | Disposition | Action taken | Verified |
|---|---|---|---|
| `mattamundson/jarvis-sentinel` | Folded (conceptually) → `home-scripts` + `jarvis-trader` health endpoints + this inventory | Probe/deadman concepts consolidated into `docs/research/sentinel-observability-runbook.md` (PR #895); existing `jarvis_data_integrity_sentinel.py` in `home-scripts` is the deployed asset; topics applied | ✓ Topics: `agent-reference`, `archive-candidate`, `consolidation-candidate` |
| `mattamundson/jarvis-mission-control` | Folded (conceptually) → `master-jarvis` + `second-brain` + this inventory | Mission YAML + evidence schema concepts noted in `docs/research/sentinel-observability-runbook.md`; runtime control-plane code kept only if actively deployed; topics applied | ✓ Topics applied |
| `mattamundson/master-jarvis-lifeos` | Folded (conceptually) → `master-jarvis` + `second-brain` + this inventory | Reusable agent/runbook/MCP/observability pieces absorbed into the agent-ops source of truth (active Hermes skills + `second-brain` + `home-scripts`); topics applied | ✓ Topics applied |
| `mattamundson/personal-agent-skills` | Folded (conceptually) → active Hermes profile skills + `second-brain` + this inventory | Reusable agent skills merged into active Hermes profile; topics applied | ✓ Topics applied |
| `mattamundson/personal_agent` | Folded (conceptually) → `master-jarvis` + `second-brain` + this inventory; source archived | Large personal agent repo; reusable pieces absorbed into active Hermes profile and `master-jarvis`; topics applied; source archived | ✓ Archived true; topics applied |
| `mattamundson/gbrain-mcp` | Folded → `home-scripts/gbrain/` + this inventory; source archived | gbrain safe-ops tooling already lives in `home-scripts/gbrain/` (cockpit, embed, repair); source repo archived after verified in-tree copy; topics applied | ✓ Archived true; `home-scripts/gbrain/` confirmed present |
| `mattamundson/hermes-obsidian-mcp` | Folded (conceptually) → active Hermes profile skills + `second-brain` + this inventory | Obsidian capture surface absorbed into active Hermes profile; topics applied | ✓ Topics applied |
| `mattamundson/hermes-agent-config` | Folded (conceptually) → active Hermes profile + this inventory; source archived | Single-config-file repo; absorbed into active Hermes profile config; source archived; topics applied | ✓ Archived true; topics applied |
| `mattamundson/hermes-agent-self-evolution` | Folded (conceptually) → `second-brain` + this inventory | Session handoff artifacts absorbed into `second-brain`; topics applied | ✓ Topics applied |
| `mattamundson/obsidian-mind` | Folded (conceptually) → `second-brain` + this inventory; source archived | Obsidian vault AI-agent memory concepts absorbed into `second-brain`; source archived; topics applied | ✓ Archived true; topics applied |
| `mattamundson/obsidian-skills` | Folded (conceptually) → active Hermes profile skills + `second-brain` + this inventory | Agent skills for Obsidian absorbed into active Hermes profile; topics applied | ✓ Topics applied |
| `mattamundson/tools` | Folded (conceptually) → `master-jarvis` + `home-scripts` + this inventory | TypeScript tooling absorbed into the agent-ops source of truth; topics applied | ✓ Topics applied |
| `mattamundson/reddit-mcp` | Folded (conceptually) → active Hermes profile skills + this inventory | Reddit MCP proxy absorbed into active Hermes profile; topics applied | ✓ Topics applied |
| `mattamundson/ralph-orchestrator` | Folded (conceptually) → `master-jarvis` + `second-brain` + this inventory | Orchestration primitives (circuit breaker, token tracker, agent memory, handoffs) noted in `master-jarvis/REPO_AUTHORITY.md` and this inventory; topics applied | ✓ Topics applied |
| `mattamundson/AIAgent` | Folded (conceptually) → `second-brain` + this inventory | Single-file AIAgent repo; concept noted in `second-brain`; topics applied | ✓ Topics applied |
| `mattamundson/claude-config-backup` | Folded (conceptually) → `second-brain` + this inventory | Claude Code config/conversation backup HTML; concept noted in `second-brain`; topics applied | ✓ Topics applied |

### 2.4 Keep separate but bridge into JARVIS

| Repo | Disposition | Action taken | Verified |
|---|---|---|---|
| `mattamundson/amo-arbitrage` | Keep separate — different asset class/product; bridgeable via adapters | No merge into futures JARVIS; signals/risk lessons transferable through adapters only; topics `reference`, `trading-research` applied | ✓ Pushed 2026-09-09; topics applied |

### 2.5 Vendor/reference forks — mined for patterns (Wave 2), kept as reference forks

> The audit's Wave 2 item 3 asked to mine these eight repos for concrete JARVIS additions, preferring distilled
> docs/checklists/tests over vendoring large forks. All eight have topics applied. Five reference-fork distillations
> are in PR #895 (open); the remaining patterns are noted below for future waves.

| Repo | Disposition | Action taken | Verified |
|---|---|---|---|
| `mattamundson/claude-trading-skills` | Reference fork — mined; keep | Source for `backtest-critique-checklist.md` (backtest-expert skill + quant-strategy-framework kill rule), `macro-regime-context-spec.md` (macro-regime-detector), `strategy-registry-schema.md` (workflow/verification discipline). Additional skills in `skills-index.yaml` (breadth-chart-analyst, market-regime, core-portfolio, swing-opportunity, trade-planning, trade-memory, advanced-satellite) noted for future agent-command audits. Topics: `reference`, `trading-research`, `vendor-fork` | ✓ Topics read back |
| `mattamundson/awesome-quant` | Reference fork — mined; keep | Source for backtesting library patterns in `backtest-critique-checklist.md`. Full list is a vendor reference; a future JARVIS-relevant shortlist (data layer / backtesting / technical indicators / prediction markets sections) is a candidate for a future wave. Topics applied | ✓ Topics read back |
| `mattamundson/TradingAgents` | Reference fork — mined; keep | Multi-agent LLM financial trading framework (TauricResearch). v0.4.0 (2026-08) added look-ahead/point-in-time fixes across FRED macro, social sentiment, decision-log memory; structured-output agents (Research Manager, Trader, Portfolio Manager); decision log. Agent-role architecture and decision-log pattern are candidates for a future `docs/research/agent-workflow-patterns.md`. Topics applied | ✓ Topics read back |
| `mattamundson/Vibe-Trading` | Reference fork — mined; keep | Personal trading agent (FastAPI + React + 16 IM channel adapters). Notable: `PreTradeAdvisoryInterface` (broker-agnostic advisory review gate, #328), paper/live boundary enforcement (#321), file-tool isolated read/write roots (#299). Patterns relevant to JARVIS execution/risk review. Topics applied | ✓ Topics read back |
| `mattamundson/tradingview-mcp` | Reference fork — mined; keep | Source for `chart-review-runbook.md` (TradingView MCP + Lightweight Charts two-tool model). Topics applied | ✓ Topics read back |
| `mattamundson/sunday-quant-scientist` | Reference fork — mined; keep | Free quant newsletter. Source for macro/FRED regime concepts in `macro-regime-context-spec.md`. Individual issues (e.g. QS010-relative-strength-index) are candidate pattern sources for future strategy research docs. Topics applied | ✓ Topics read back |
| `mattamundson/fredapi` | Reference fork — mined; keep | Python FRED/ALFRED client. Source for `macro-regime-context-spec.md` data contract. Topics applied | ✓ Topics read back |
| `mattamundson/lightweight-charts` | Reference fork — mined; keep | HTML5 canvas financial charts. Source for `chart-review-runbook.md` embedded review model. Topics applied | ✓ Topics read back |

### 2.6 Additional reference forks (audit list — topics applied, no further mining this wave)

| Repo | Disposition | Verified |
|---|---|---|
| `mattamundson/LLM-Trading-Lab` | Reference fork — keep; topics applied | ✓ Topics: `reference`, `trading-research`, `vendor-fork` |
| `mattamundson/atlas-gic` | Reference fork — keep; topics applied | ✓ Topics applied |
| `mattamundson/Polymarket-Trading-Bot` | Reference fork — keep; topics applied | ✓ Topics applied |
| `mattamundson/prediction-market-backtesting` | Reference fork — keep; topics applied | ✓ Topics applied |
| `mattamundson/polybot` | Reference fork — keep; topics applied | ✓ Topics applied |

### 2.7 Business / Greenfield — isolate from trading system

| Repo | Disposition | Verified |
|---|---|---|
| `mattamundson/greenfield-ai-suite` | Business domain — isolate; topics applied | ✓ Topics applied |
| `mattamundson/Greenfield-Hover-Tool` | Business domain — isolate; topics applied | ✓ Topics applied |
| `mattamundson/greenfield-inventory-system` | Business domain — isolate; topics applied | ✓ Topics applied |
| `mattamundson/greenfield-metal` | Business domain — isolate; topics applied | ✓ Topics applied |
| `mattamundson/greenfield-quote-generator` | Business domain — isolate; topics applied | ✓ Topics applied |
| `mattamundson/Greenfield-Website-v1` | Business domain — isolate; topics applied | ✓ Topics applied |
| `mattamundson/GreenfieldProd1` | Business domain — isolate; topics applied | ✓ Topics applied |
| `mattamundson/procoil-enterprise` | Business domain — isolate; 404 on verify/topic update; treated as unresolvable | ✗ 404 — cannot confirm |
| `mattamundson/gms-intelligence-plugin` | Business domain — isolate; topics applied | ✓ Topics applied |
| `mattamundson/paradigm-ai-dashboard` | Business domain — isolate; topics applied | ✓ Topics applied |

### 2.8 Learning / career / other — not trading system

| Repo | Disposition | Verified |
|---|---|---|
| `mattamundson/dp600-mastery` | Historical learning reference — not trading authority | ✓ Topics applied where relevant |
| `mattamundson/dp600-progress` | Historical learning reference | ✓ |
| `mattamundson/dp600-stark-v2` | Historical learning reference | ✓ |
| `mattamundson/ps_data_engineer_kit` | Historical learning reference | ✓ |
| `mattamundson/cms-data-engineer-assessment` | Historical learning reference | ✓ |
| `mattamundson/assessment-practice` | Historical learning reference | ✓ |
| `mattamundson/career-ops` | Historical learning reference | ✓ |
| `mattamundson/my-portfolio` | Historical learning reference | ✓ |
| `mattamundson/mattamundson` | Profile README — not trading authority | ✓ |
| `mattamundson/pbi-observatory` | Historical learning reference | ✓ |
| `mattamundson/pbi-gateway-monitoring` | Historical learning reference | ✓ |
| `mattamundson/pbi-cli` | Historical learning reference | ✓ |
| `mattamundson/visual-explainer` | Historical learning reference | ✓ |
| `mattamundson/kanban-agent-orchestrator` | Historical learning reference | ✓ |

### 2.9 Agent platform references — keep as forks/reference

> 20+ agent-platform forks (hermes-agent, codex, agent-browser, agentmemory, gbrain, awesome-ai-agents, etc.).
> All carry `reference` topic where applicable. No product code vendored. Not enumerated individually here; see
> `repos_raw_analysis.json` for the full list.

---

### 6.2 Wave 2 distillation docs (PR #906 — merged 2026-09-22)

| Doc | Source repos distilled | What it gives JARVIS |
|---|---|---|
| `docs/research/strategy-registry-schema.md` | `claude-trading-skills` + existing strategy-research operating model | One YAML record per strategy; promotion gate rules; provenance discipline for imported ideas |
| `docs/research/backtest-critique-checklist.md` | `claude-trading-skills` backtest-expert skill + `awesome-quant` + JARVIS promotion policy | 5-dimension 0–100 scorecard; 12 red flags (critical/warning split); JARVIS-specific gates |
| `docs/research/chart-review-runbook.md` | `tradingview-mcp` + `lightweight-charts` | Two-tool model: TV MCP for live Desktop capture/Pine prototyping, Lightweight Charts for embedded Mission Control review; 5-step loop |
| `docs/research/macro-regime-context-spec.md` | `fredapi` + `claude-trading-skills` macro-regime-detector | FRED/ALFRED as regime filter and context feature only — never a direct order trigger; data-contract fields; freshness/staleness rules |
| `docs/research/sentinel-observability-runbook.md` | `jarvis-sentinel`, `jarvis-mission-control`, `home-scripts` hygiene tooling | One probe inventory (IB Gateway, engine, dashboard, PM2 dump secret hygiene, feed freshness, paper order drift, kill-switch state); evidence contract; ownership; no third always-on process rule |

**PR:** https://github.com/mattamundson/jarvis-trader/pull/906  
**Merged:** 2026-09-22T10:10:12Z  
**Branch:** `docs/wave2-reference-distillates-20260922`  
**No live-trading surfaces touched:** `.env`, `engine/config.py`, broker routing, API keys, PM2 state, scheduled trading tasks, risk limits, kill-switch code all unchanged.

---

## 4. Wave 1 imports (PRs #816 and #6 — merged)

| Repo | PR | Merge commit | What was imported |
|---|---|---|---|
| `jarvis-positions-check`, `jarvis-quant`, `autotrade` | #816 (jarvis-trader) | `1cd8c8aab2e345a69f5987317dbf21b2406d1733` | `engine/scripts/check_positions.py`, `engine/research/imported/jarvis-quant/**`, `docs/research/llm_strategy_iteration/`, `docs/research/strategy-research-operating-model.md`, `docs/research/imported-repos/2026-09-12-wave1/README.md` |
| N/A (repo authority) | #6 (master-jarvis) | `ec2ddaadafe4fbc51ae2336cebe0fcc8a30a144c` | `REPO_AUTHORITY.md` |

---

## 5. Topic hygiene summary

| Topic | Applied to |
|---|---|
| `canonical-system` | `jarvis-trader`, `master-jarvis` |
| `trading-system` | `jarvis-trader` |
| `orchestration` | `master-jarvis` |
| `repo-authority` | `master-jarvis` |
| `reference`, `trading-research`, `vendor-fork` | `claude-trading-skills`, `awesome-quant`, `TradingAgents`, `Vibe-Trading`, `tradingview-mcp`, `sunday-quant-scientist`, `fredapi`, `lightweight-charts`, `LLM-Trading-Lab`, `atlas-gic`, `Polymarket-Trading-Bot`, `prediction-market-backtesting`, `polybot` |
| `agent-reference`, `archive-candidate`, `consolidation-candidate` | All 13 agent/ops repos in §2.3 |
| `reference`, `trading-research` | `amo-arbitrage` |

**Procoil-enterprise exception:** `mattamundson/procoil-enterprise` returns 404 on `gh repo view` and could not be
confirmed or topic-updated. Treated as unresolvable — same as Wave 1. No action taken.

---

## 6. Still open / future waves

### 6.1 This run did not do (deferred by design)

- **Wave 2 backlog item 5** (agent/ops consolidation for the 13 repos through a more detailed per-repo note): the
  operating rule says consolidate through docs/provenance only; this inventory note is that documentation. No clean
  reusable script exists for most of these repos, so no code move is warranted.
- **Wave 3 archive sweep** (archive stale Greenfield/business repos or tag them `business-archive`): all 10 business
  repos have topics applied. Actual archive action is gated on Amo's business-domain decision, not this run.
- **JARVIS-relevant awesome-quant shortlist:** a future wave candidate, not this run.
- **Agent workflow patterns doc** (`docs/research/agent-workflow-patterns.md`) distilling `claude-trading-skills`
  skills-index.yaml + TradingAgents decision-log pattern: a future wave candidate, not this run.

### 6.2 One next action

**Review and merge PR #895.** After merge, this inventory note is the final Word from the consolidation program:
every repo in the audit map has a verified disposition. No further repo action is required unless Amo wants
additional reference-fork mining (awesome-quant shortlist, agent-workflow-patterns doc) as a future wave.

---

*Generated 2026-09-21 by Hermes Agent cron run continuing the 2026-09-12 GitHub repo consolidation + trading-system leverage audit.*
