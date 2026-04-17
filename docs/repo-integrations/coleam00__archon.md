---
repo: coleam00/Archon
url: https://github.com/coleam00/Archon
stars: 18412
language: TypeScript
license: MIT
archived: false
pushed_at: 2026-04-16T23:32:06Z
analyzed_at: 2026-04-17
recommendation: defer
surfaces_with_value: [dev-tooling, docs, skills]
---

# coleam00/Archon

## Core value proposition

Archon is a workflow orchestration engine for AI-assisted development, enabling deterministic, repeatable automation of multi-step development tasks through YAML-defined DAGs (directed acyclic graphs). It combines fixed deterministic nodes (bash, tests, git ops) with AI nodes (planning, implementation, review) and supports multi-platform execution (CLI, Web UI, Slack, Telegram, GitHub Webhooks). The system enforces process rigor: every workflow run gets isolated git worktrees, human approval gates are composable, and the same workflow can be kicked off from any platform.

## Surface analysis

### 1. Engine code

**no-fit** — Archon is a workflow meta-orchestrator (TypeScript/Bun/SQLite), not a trading signal, risk model, or execution strategy. JARVIS operates at agent-dispatch level (debate → trader) rather than general CI/CD automation. No direct port target.

### 2. Project rules

**partial-integrate** — Archon's design philosophy on determinism and repeatability mirrors JARVIS's disciplinary needs. Specifically: (a) workflow validation gates (prevent unprompted AI steps), (b) isolated execution contexts (worktrees = no cross-agent file corruption), and (c) audit trails (all node outputs logged). The jarvis-trader codebase already enforces (a) via `.claude/agents/safety-reviewer.md` and (b) via `.claude/imports/parallel-agents.md` task manifests, but Archon's formalized approach to workflow-as-code + approval gates could sharpen `.claude/rules/git-workflow.md`. Defer implementation: requires decision on whether to adopt Archon as tooling vs. document workflow discipline inline.

### 3. Project skills

**partial-integrate** — Archon demonstrates two reusable skill patterns: (1) **router skill** (user intent → workflow selection), (2) **custom workflow instantiation** (user provides task spec → generate YAML). JARVIS skill infrastructure (.claude/skills/) is already mature (agent-debate-explain, backtest-report, gstack, jarvis-trader, jarvis-cost-routing). Archon's router and the ability to author reusable workflow templates could inform a new `/archon-integration` skill that wraps Archon for multi-phase tasks (plan-implement-validate-approve-deploy loops). Defer: requires Archon binary availability on system PATH and decision on whether to vendor Archon workflows into JARVIS repo.

### 4. Slash commands

**no-fit** — Archon's slash commands are platform-specific (Slack, Telegram, GitHub triggers). JARVIS uses `.claude/commands/` for Claude Code agents only (jarvis-commit-with-receipts.md, jarvis-ib-gateway-health.md). No mapping.

### 5. Subagents

**dedup-agents** — JARVIS already has structured subagent protocol at `.claude/agents/` (backtest-runner.md, dashboard-qa.md, pipeline-debugger.md, memory-curator.md, safety-reviewer.md). Archon's multi-agent review workflows (5 parallel reviewers, smart PR review, comprehensive PR review) are reference patterns but not implemented in JARVIS code. Architecture is present; specific PR-review-loop agents would be a custom implementation orthogonal to Archon framework.

### 6. Docs

**dedup-docs** — Archon's runbooks cover platform setup, workflow authoring, configuration, deployment, and troubleshooting. JARVIS has equivalent structure in `docs/runbooks/` (DAILY_AUTOMATION.md, API_KEY_ROTATION.md, IB_CONNECTOR_OVERVIEW.md, HEALTH_API_CONTRACT.md, DEPLOYMENT.md). Archon's "Book of Archon" narrative tutorial demonstrates workflow patterns (plan → implement → validate → review → PR) that parallel JARVIS's phase structure in debate → trader → risk_manager → execution. Documented pattern, not new content to integrate.

### 7. Dev tooling

**defer** — **Safety-critical integration requiring [safety-review] tag.** Archon's core value (isolated worktrees, approval gates, multi-platform dispatch) directly overlaps JARVIS infrastructure points: (a) `.github/workflows/ci.yml` (CI/CD gates), (b) `.github/workflows/claude-pr-review.yml` (PR review automation), (c) `engine/main.py:1454-1500` (APScheduler cron jobs for daily automation). **Current state:** JARVIS uses GitHub Actions for CI + APScheduler for scheduling + native Claude Code agents for multi-phase tasks (ralph loops via `/ralph` skill). **Archon fit:** Could replace the three independently managed orchestration layers (GH Actions + APScheduler + Claude agents) with unified YAML-defined DAGs. **Blocker:** Requires PoC that Archon's workflow execution model preserves safety invariants (trade_invariants.py, kill-switch logic, position-limit checks). Risk: Archon nodes execute arbitrary bash; a malformed workflow YAML could bypass risk guards. Recommendation: Request [safety-review] before integration. Candidate: `ecosystem.config.js` PM2 restart patterns could be automated via Archon after safety audit.

### 8. Dashboard

**no-fit** — Archon's web dashboard is a Workflow Execution Monitor (chat, real-time progress, history filtering, DAG visualization). JARVIS dashboard (`dashboard/components/`) is a trading operations center (positions, PnL, fills, agent decisions, regime). Different domains; no reusable UI components.

### 9. Ops / messaging

**partial-integrate** — Archon's notification pattern (workflow state → Slack/Telegram/Discord) mirrors JARVIS's OpenClaw integration (`engine/notifications/openclaw_notifier.py`, `engine/schedulers/` cron triggers). Archon demonstrates: (1) message templating for agent outcomes, (2) approval gates with message-driven human intervention, (3) multi-platform dispatch. JARVIS currently sends BUY/SELL/risk alerts via OpenClaw → WhatsApp; Archon's pattern would standardize approval workflows (e.g., "large position → human approval via Slack → trade execute or reject"). Defer: requires OpenClaw/Slack integration test with Archon SDK.

## Integration plan

**No integrations proceed without explicit safety review and user decision.**

If deferred to [safety-review]:
1. **Dev tooling deep-dive (2-4 hours)**: Map Archon DAG schema against JARVIS workflow patterns (daily automation cron, PR review gates, position management approval). Create PoC YAML for one existing workflow (e.g., `archon-validate-pr` equivalent to `ci.yml`). Identify risk vectors.
2. **Safety invariant audit (1-2 hours)**: Verify that Archon's bash-node execution cannot circumvent `engine/risk/` or `engine/execution/paper_trade_logger.py` guards. Test policy: Archon workflow + malformed node → trade attempt → confirm kill-switch still fires.
3. **Ops/messaging integration (1 hour)**: Prototype Archon → OpenClaw approval gate (workflow suspends, sends Slack message, resumes on human approval).
4. **Decision checkpoint**: User reviews PoC + safety audit findings. Green-light integration or document as "reference only" in `docs/external-frameworks-evaluated.md`.

## License & attribution

**MIT License** — Code can be copied with attribution. If integrations proceed, add attribution to file header in any `.archon/workflows/` or dev tooling files, e.g.:
```
# Workflow orchestration patterns adapted from Archon (github.com/coleam00/Archon, MIT License)
```

## Effort estimate

**M** (2-8 hours) — PoC + safety audit only. Full integration (replace .github/workflows + APScheduler) would be **XL** (>3 days multi-session).

## Red flags

1. **Archon is meta-orchestrator, not domain-specific.** No direct trading value. Integrates only if it *improves* existing workflow discipline (approvals, isolation, auditability).
2. **Safety-critical blocker.** Archon allows arbitrary bash execution in workflows. JARVIS has hard safety boundaries (kill_switch_deactivated checks, position limits, stop-loss invariants). Any integration must be formally verified not to introduce workflow-based bypasses.
3. **TypeScript/Bun toolchain.** JARVIS engine is Python + Node.js dashboard. Archon CLI would be an additional runtime dependency. Must be optional (dev tooling, not engine-critical).
4. **Workflow-as-code adoption cost.** JARVIS already has informal workflows (ralph loops, parallel agents, GitHub Actions). Moving to Archon YAML requires standardization discipline — team must commit to workflow definitions and versioning.
5. **Multi-platform dispatch capability is interesting but unproven for trading context.** Triggering trades from Slack/Telegram via Archon adds complexity; approval workflows benefit more than market-responding workflows.

## Strategic context

Archon is a well-built open-source tool (18.4k stars, active development, MIT) that solves a real problem: deterministic AI-assisted development at scale. For trading codebases, the strongest fit is *dev process automation* (test → review → PR approval) rather than *trading automation* (signal → order execution). JARVIS's core trading loop (debate → trader → risk_manager → execution) is deterministic by design and needs no orchestration layer. However, the *surrounding* development practices (daily routine cron jobs, PR validation gates, multi-agent code review) could be unified under Archon's formalism. Recommend filing as "reference architecture for workflow discipline" until safety review is complete.
