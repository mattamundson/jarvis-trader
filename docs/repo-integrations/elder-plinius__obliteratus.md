---
repo: elder-plinius/OBLITERATUS
url: https://github.com/elder-plinius/OBLITERATUS
stars: 4691
language: Python
license: AGPL-3.0
archived: false
pushed_at: 2026-04-01T20:47:50Z
analyzed_at: 2026-04-17
recommendation: defer
surfaces_with_value: [rules]
---

# elder-plinius/OBLITERATUS

## Core value proposition

OBLITERATUS is a toolkit for identifying and surgically removing refusal behaviors from LLMs through mechanistic interpretability techniques (SVD extraction, sparse autoencoder decomposition, norm-preserving projection). It exposes the internal geometry of guardrails via abliteration — a set of methods to map, extract, and neutralize refusal directions while preserving core language capabilities. The repo includes Gradio UI, CLI, Python API, and Colab notebook entry points, plus distributed telemetry for community research.

## Surface analysis

### 1. Engine code
**defer** — OBLITERATUS focuses on model *training-time* guardrail removal via weight surgery. JARVIS TRADER's threat surface is *inference-time* prompt injection and adversarial input to trading agents. The mechanistic interpretability techniques (SVD of activation matrices, MoE-expert decomposition, CoT-aware layer selection) are orthogonal to input validation. While the repo's refusal geometry mapping could theoretically inform defensive prompts, porting the ~2k-line abliteration pipeline into `engine/risk/` or `engine/agents/` would introduce unrelated research code with no operational payoff for a paper-trading system. No fit for engine/agents/, engine/backtest/, engine/strategies/, engine/risk/, engine/analytics/.

### 2. Project rules
**partial-integrate** — The OBLITERATUS design philosophy contains two ideas applicable to `.claude/rules/safety.md`: (a) **Transparency of constraints:** OBLITERATUS publishes exactly which layers enforce refusal; jarvis-trader could document which system prompts (technical_analyst, debate, risk_manager) are critical to safety and why agents should NOT override them; (b) **Iterative verification:** OBLITERATUS re-probes after each intervention; jarvis-trader's existing safety.md could expand with "Re-verify safety assumptions when agent system prompts change" as a rule-authoring principle. Current safety.md is trading-risk-focused; a defensive-prompt-integrity rule would complement it but requires deliberate design (not a port from OBLITERATUS). Effort is small (1-2hr to write a new rule file `.claude/rules/defensive-prompts.md`), but decision is needed first: does jarvis-trader want to treat prompt-integrity as a formal rule surface?

### 3. Project skills
**no-fit** — OBLITERATUS is a research tool for model weight surgery. No skill pattern (reusable workflow) translates to jarvis-trader's trading pipeline.

### 4. Slash commands
**no-fit** — OBLITERATUS does not suggest workflow shortcuts or quick diagnostics applicable to trading. The repo is a research harness, not operational tooling.

### 5. Subagents
**no-fit** — OBLITERATUS has no agent personas. The repo is a monolithic analysis pipeline, not a multi-role reasoner.

### 6. Docs
**no-fit** — OBLITERATUS documentation covers mechanistic interpretability, refusal geometry, and abliteration techniques. Jarvis-trader's runbooks focus on trade execution, P&L monitoring, and broker integration. No operational crossover.

### 7. Dev tooling
**no-fit** — OBLITERATUS ships Gradio UI, Colab notebook, and HuggingFace Spaces integration. Jarvis-trader's dev tooling is PM2, FastAPI, pytest, and OpenClaw integrations. No shared infrastructure patterns.

### 8. Dashboard
**no-fit** — OBLITERATUS offers layer-wise heatmaps, cross-model universality charts, and refusal topology visualizations — mechanistic interpretability outputs. Jarvis-trader's dashboard tracks P&L, positions, regime, and execution metrics. No UI reuse.

### 9. Ops / messaging
**no-fit** — OBLITERATUS telemetry pipeline publishes abliteration runs to a crowd-sourced research dataset. Jarvis-trader's ops surface handles market hours gates, kill-switch alerts, and WhatsApp approvals. No operational overlap.

## Integration plan

**Conditional defer on rules formalization:**

If you decide to make prompt-integrity a first-class safety rule in jarvis-trader, a follow-up session (effort M, 2-8 hours) would:
1. Write `.claude/rules/defensive-prompts.md` with principles like:
   - System prompts are not meant to be overridden by agent-generated continuations
   - Agent output parsing must not execute LLM-suggested changes to system prompts
   - When in doubt, the hardcoded Python safety layer (not LLM reasoning) is the authority
2. Cross-reference OBLITERATUS's concept of "verification layers" (re-probe after intervention) to document that system prompt changes require regression testing
3. Add a test at `engine/tests/test_system_prompt_integrity.py` to validate that agent outputs cannot exfiltrate or override the debate prompt or technical analyst constraints

This is **defensive writing**, not integration of OBLITERATUS code. The repo informs the *principle* but contributes no code.

No integration at this time without explicit user confirmation of the rules strategy.

## License & attribution

**AGPL-3.0** — GNU Affero General Public License v3.0. This is a copyleft license. If jarvis-trader were to **import OBLITERATUS code** (e.g., SVD direction extraction, CoT-aware layer selection), the entire jarvis-trader engine would need to be distributed under AGPL-3.0 as well. This is incompatible with any closed-source or proprietary trading use.

**Decision:** Do not copy code from OBLITERATUS. References to design principles (in docs/repo-integrations/elder-plinius__obliteratus.md or `.claude/rules/defensive-prompts.md` if written) do not trigger copyleft obligations.

## Effort estimate

- **No integration (status quo)**: 0 hours
- **Rules formalization** (if user decides): M (2-8 hours)
  - 1 hour: write `.claude/rules/defensive-prompts.md`
  - 2-3 hours: update existing safety.md to cross-reference and clarify LLM vs hardcoded authority
  - 2-4 hours: add regression tests and code review

## Red flags

1. **AGPL-3.0 copyleft risk** — Any code copied from OBLITERATUS contaminates the entire project. Do not import without legal review and willingness to relicense the engine.
2. **Architectural mismatch** — OBLITERATUS is a research harness for model weight modification. Jarvis-trader is an inference-only trading system. The problem domains (training-time alignment research vs. runtime prompt injection defense) are orthogonal.
3. **Scope creep** — Mechanistic interpretability is an advanced research topic. Absorbing OBLITERATUS patterns would expand cognitive load for maintenance with no immediate payoff.
4. **Telemetry opt-in** — If anyone ever runs the OBLITERATUS Spaces or Colab version with telemetry enabled on a modified copy, it would contribute trading-related data to a public research dataset. Risk of data leakage.

## Recommendation summary

**Do not integrate OBLITERATUS code.** The repo's value is philosophical (transparency of constraints, iterative verification) not operational. A principles-based rules addition (`.claude/rules/defensive-prompts.md`) would be a standalone effort, informed by but not dependent on OBLITERATUS. Defer the rules work to a future session if you decide prompt-integrity is a formal safety surface for jarvis-trader.
