# LLM decision audit pattern — from `mattamundson/LLM-Trading-Lab`

**Source:** `mattamundson/LLM-Trading-Lab` (reference fork, 114 files, public)
**Date mined:** 2026-09-28
**Scope:** research note / journal template reference. No code. No execution wiring.

---

## What the experiment was

A 6-month live experiment (2024-2025) where ChatGPT, driven by structured weekly deep-research prompts, managed a real-money micro-cap equity portfolio starting near $1M. The repo ships:

- 26 weekly research reports (one written *after* each week closes)
- A full trade log (`csv_files/Trade_Log.csv`)
- Daily updates (`csv_files/Daily_Updates.csv`)
- A formal evaluation paper (`evaluation/paper.pdf`)

**Honest result:** −5.91% over 378 days. Detailed in `docs/research/atlas-gic-agent-architecture-note.md` alongside the atlas-gic negative result — two independently built LLM-driven systems both losing money is a meaningful data point, not noise.

---

## The weekly forward-only research artifact structure

Each week produces a written summary *after* the week ends. The structure is the reusable artifact — not the specific stock picks. A weekly artifact covers:

1. **Thesis review** — what the prevailing thesis was at the start of the week
2. **What worked** — positions/decisions that paid off, and why
3. **What didn't** — positions/decisions that failed, and why (the honest part)
4. **Risk re-rating** — how the risk view changed during the week (stops re-rated post-catalyst, position sizing adjusted)
5. **Position adjustments** — what was added, trimmed, or closed, and the rationale

This maps directly onto JARVIS' existing journal cadence in `second-brain` and the post-trade/postmortem step in `docs/research/strategy-research-operating-model.md`. The LLM-Trading-Lab structure is a concrete exemplar of what a *forward-only* (written after the fact, never peeking) weekly decision journal looks like.

---

## The LLM decision audit pattern

The deeper lesson is methodological. If an LLM shapes a portfolio, you need to evaluate the *decision process*, not just the bottom line. The pattern:

1. **Log every recommendation with timestamp, rationale, and forward outcome.**
   Every time the LLM recommends a position change, record: when it was made, what it recommended, the stated rationale, and — critically — what actually happened to that position subsequently. This turns a narrative into an auditable decision ledger.

2. **Pre-register the evaluation framework.**
   The repo ships a formal evaluation paper. The methodological point: you can't retrospectively invent success criteria. Define *before the experiment* what counts as a good decision (e.g. risk-adjusted return, adherence to stated thesis, stop discipline) and what counts as a bad one.

3. **Separate decision quality from outcome quality.**
   A good decision can have a bad outcome (bad luck / market noise). A bad decision can have a good outcome (dumb luck). The audit pattern forces you to classify decisions on their own terms, then compare the distribution of decision quality to the realized PnL. If the decision process is sound but the PnL is negative, that's a different problem than a broken decision process with positive PnL.

---

## Micro-cap specific risk lessons (example text, not reusable code)

The weekly summaries show the kind of position-level reasoning a discretionary overlay needs — useful as example text for JARVIS' trade-journal template, not as logic to import:

- **Catalyst tracking** — micro-caps move on binary events; the journal tracks what catalyst was expected, when it landed, and how the position reacted.
- **Stop re-rating post-catalyst** — a stop that made sense before a binary event may not make sense after; the journal records the re-rating rationale.
- **Sell-the-news behavior** — the pattern of "run-up into the event, fade on the print" appears in several weekly summaries; useful as a labeled pattern in the journal, not as an automatic rule.

---

## What JARVIS should absorb

1. **Weekly journal template.** Add the LLM-Trading-Lab weekly artifact structure as a suggested template in `second-brain`'s weekly-summary template and in the `strategy-research-operating-model.md` post-trade/postmortem section. The structure is vendor-neutral and improves any journal, LLM-driven or not.

2. **LLM decision audit log concept.** If JARVIS ever lets an LLM shape a portfolio (e.g. the agent pipeline's `fundamental_analyst` or `risk_manager` recommendations), the recommendation log should carry: timestamp, recommendation, rationale, and forward outcome. This is the minimal auditable unit. `docs/research/llm-trading-agent-evidence-checklist.md` already covers evidence standards for LLM trading agents — this note adds the *decision audit* angle (process evaluation, not just outcome).

3. **Honest negative result as anti-overengineering evidence.** Two independently built LLM-driven trading systems (LLM-Trading-Lab: −5.91%; atlas-gic: −5.91%) both losing money over 6–18 months is a strong data point for JARVIS' backtest critique and strategy registry: fancy LLM infrastructure does not guarantee profit. The `backtest-critique-checklist.md` and strategy registry promotion gate should cite this when resisting pressure to overengineer the agent layer.

---

## What JARVIS should NOT absorb

- **No execution wiring.** The `trading_script.py` in LLM-Trading-Lab is venue-specific (micro-cap equity broker API) and is explicitly excluded. JARVIS' execution/risk layer is futures via IB Gateway — completely different surface.
- **No prompts or raw trade data.** The weekly reports and trade log are raw experiment artifacts, not reusable strategy logic. They're cited as *examples* of journal structure, not imported as content.
- **No LLM-as-portfolio-manager promotion.** The honest result (−5.91%) is the gate: there is no case for letting an LLM directly manage JARVIS capital based on this evidence. The auditable-decision-log pattern is the only transferable artifact.

---

## Verification

- File-tree census and content extraction read back from GitHub API / raw.githubusercontent.com before writing.
- No fork default branch modified.
- `gh repo view` confirms `mattamundson/LLM-Trading-Lab` is `isFork: true`, `isArchived: false`, `visibility: PUBLIC`, topics `reference, trading-research, vendor-fork`.

---

*This note distills research patterns from a reference fork for JARVIS' journal/agent-governance documentation. It is not a trading strategy, not an execution surface, and not a recommendation to deploy any LLM-driven capital allocation.*
