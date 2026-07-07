---
repo: GoogleCloudPlatform/agent-starter-pack
url: https://github.com/GoogleCloudPlatform/agent-starter-pack
stars: 6265
language: Python
license: Apache-2.0
archived: false
pushed_at: 2026-04-16T15:56:59Z
analyzed_at: 2026-04-17
recommendation: partial-integrate
surfaces_with_value: [dev-tooling, ops-messaging, docs]
shipped:
  - file: engine/schemas/decision_log.py
    surface: engine-code
    date: 2026-04-17
    what: "Typed Pydantic v2 models for the existing decisions table and full_pipeline_json embedded payload (5 stages + confidence gate + final outcome). Adapts ASP's Vertex AI Evaluation logging pattern (Apache-2.0) to the already-built 5-stage debate pipeline. 20 passing tests lock the contract against real row shapes."
audit_correction:
  - original_claim: "Current AgentFeedbackTracker in agent_feedback.py logs outcomes, not *decisions*"
    actual_state: "decisions_router.py + _mixins_decisions.py + migration 019 already provide decision logging with stage-by-stage full_pipeline_json. The real gap was the TYPED CONTRACT — everything passed around raw dict objects."
    caught_by: "verify-before-reporting before writing decision_log.py"
deferred:
  - what: "Multi-stage CI/CD gate doc (dev -> staging -> prod) — Action 1 in the original integration plan"
    reason: "doc-only, lower leverage than the typed schema which actively benefits existing code"
  - what: "Terraform pattern doc for future cloud deployment — Action 3"
    reason: "jarvis-trader runs local + IB Gateway; Terraform is post-paper-trading consideration"
---

# GoogleCloudPlatform/agent-starter-pack

## Core value proposition
GCP's production-ready Python template library for deploying GenAI agents to Google Cloud with automated infrastructure (Terraform), CI/CD (Cloud Build / GitHub Actions), observability (Cloud Logging), and evaluation harnesses. Not a trading strategy repo, but focuses on operationalization and LLM observability patterns that transfer to non-GCP contexts.

## Surface analysis

### 1. Engine code
**no-fit** — Agent templates (ReAct, RAG, LangGraph, ADK) are domain-agnostic but optimized for Google Cloud APIs (Vertex AI, Vector Search, Gemini). Jarvis-trader has its own agent framework (debate.py, advisor_client.py) incompatible with ASP's patterns.

### 2. Project rules
**no-fit** — ASP focuses on GCP-specific guardrails (Gemini, Vertex AI quotas, Cloud Logging limits). Jarvis-trader rules (meta-discipline.md, engine-python.md, safety.md) are trading-specific and already established.

### 3. Project skills
**no-fit** — ASP templates are GCP project setup scaffolds, not reusable workflows. Jarvis-trader's skills (jarvis-trader, backtest-report, agent-debate-explain) serve trading operations.

### 4. Slash commands
**no-fit** — No CLI command patterns applicable to jarvis-trader. ASP's `uvx agent-starter-pack create` and `enhance` subcommands are GCP deployment-only.

### 5. Subagents
**no-fit** — ASP uses Vertex AI Agents, Cloud Run workers, and ADK-native orchestration. Jarvis-trader uses OpenClaw + Claude API; no compatibility.

### 6. Docs
**partial-integrate** — ASP's CI/CD & observability architecture docs (Deployment Guide, Observability section at docs/images/asp_high_level_architecture.png) offer patterns for: (a) multi-stage deployment gates (dev → staging → prod), (b) structured logging schemas for agent decisions, (c) evaluation metrics dashboards. Jarvis-trader currently lacks formalized staging gates and agent decision logging. Recommendation: reference ASP's Deployment Guide structure in `docs/runbooks/deployment.md`; apply observability schema to engine/notifications/ and engine/analytics/.

### 7. Dev tooling
**partial-integrate** — ASP's Terraform modules (infrastructure-as-code, VPC networking, Cloud Run secrets) are GCP-locked, but the *pattern* (parametrized Terraform + GitHub Actions secrets injection) is portable. ASP uses `uv` for CLI distribution; jarvis-trader uses `pnpm` (Node.js) and `engine/.venv` (Python). No direct code reuse, but test patterns (pytest with Vertex AI evaluation mocks) and Make targets may inspire jarvis-trader's CI/CD hygiene.

### 8. Dashboard
**no-fit** — ASP provides a Firebase/Cloud Console integration frontend for agent deployment visualization. Jarvis-trader dashboard (Next.js) is custom trading-focused; no component or UI pattern overlap.

### 9. Ops / messaging
**dedup-ops-messaging** — ASP's observability and monitoring (Cloud Logging, Monitoring alerts) are already covered by jarvis-trader's engine/notifications/ suite (WhatsApp, Discord, OpenClaw integrations) and morning_brief.py. ASP's cron-style scheduled alerts (EOD summaries, proactive health checks) mirror jarvis-trader's scheduler model; no new patterns.

## Integration plan

### Action 1: Reference ASP's multi-stage CI/CD gate pattern
Add a note to `docs/runbooks/deployment.md` (create if missing) documenting the three-stage flow:
- **Dev**: local `pnpm dev` + `engine/.venv` + PM2 test harness
- **Staging**: GitHub Actions smoke tests (engine health, portfolio endpoints, paper-trade E2E)
- **Prod**: manual approval gate before live IB Gateway activation

Reference: ASP's `guide/deployment` docs and GitHub Actions workflow (`.github/workflows/ci.yml`).

### Action 2: Standardize agent decision logging schema
Create `engine/analytics/decision_log_schema.py` with a Pydantic model for structured agent decisions (signal, confidence, regime, approval status, LLM advisor reasoning). Wire into debate.py output and openclaw_notifier.py for audit trails. Inspired by ASP's Vertex AI Evaluation logging, but implemented locally (no GCP dependency).

**Why**: Current `AgentFeedbackTracker` in agent_feedback.py logs outcomes, not *decisions*. ASP's logging schema for agent reasoning (agent_id, action, model, tokens_used, latency, fallback_flag) ports directly.

### Action 3: (Optional) Adopt ASP's Terraform patterns for future cloud deployment
Document in `docs/architecture.md` (reference-only, no integration yet): how to parameterize engine deployment if jarvis-trader ever moves to Cloud Run. ASP's Terraform templates (vpc.tf, service.tf, secrets.tf) are not applicable now (jarvis-trader runs locally + IB Gateway), but the patterns are reusable post-paper-trading.

## License & attribution
Apache 2.0 license — permissive, code reuse allowed. If integrating decision_log_schema.py and observability patterns, add to file header:
```python
# Inspired by GoogleCloudPlatform/agent-starter-pack
# https://github.com/GoogleCloudPlatform/agent-starter-pack
# Licensed under Apache 2.0
```

## Effort estimate
**S** (< 2 hours) — Action 1 is doc-only (reference + note). Action 2 is a ~80-line Pydantic model + two wire-in points. Action 3 is deferred (reference-only doc, 0 effort now).

## Red flags
- **GCP-locked**: All deployment infrastructure assumes Google Cloud. Zero value for jarvis-trader's local + IB Gateway model until cloud migration.
- **Observability tooling**: ASP uses Cloud Logging + Monitoring; jarvis-trader uses OpenClaw + WhatsApp. Schemas port, tools don't.
- **Agent framework mismatch**: ASP templates (ADK, LangGraph, RAG) incompatible with jarvis-trader's debate + advisor model.

---

**Conclusion**: ASP is a production deployment accelerator for GCP, not a trading codebase. Integration value is narrow: adopt observability schema for agent decision audit trails, reference multi-stage CI/CD gates. Skip unless decision logging is a near-term priority.
