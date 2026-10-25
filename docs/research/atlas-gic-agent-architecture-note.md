# Atlas-GIC agent architecture note — from `mattamundson/atlas-gic`

**Source:** `mattamundson/atlas-gic` (reference fork, 20 files, public)
**Date mined:** 2026-09-28
**Scope:** research note / architectural reference. No code. No prompts (proprietary). No execution wiring.

---

## What it is

ATLAS by General Intelligence Capital — a 4-layer multi-agent trading system using Karpathy-style autoresearch (self-improving prompts via trial-and-error with git-based versioning), Soros-style reflexivity, and a MiroFish-inspired agent swarm. The system ran 2024-09-01 to 2026-03-07 (378 trading days), starting at $1M and ending at $940,938 — a −5.91% result.

---

## The 4-layer architecture

### Layer 1 — Macro regime (10 agents)

Agents: central bank, geopolitical, China, dollar, yield curve, commodities, volatility, emerging markets, news sentiment, institutional flow.

Role: produce a macro regime assessment that filters what Layer 2 pays attention to. This is the "what regime are we in?" layer — the same conceptual role as JARVIS' `macro_regime.py` labeling, but implemented as a panel of prompted agents rather than a deterministic function.

### Layer 2 — Sector desks (7 sectors + relationship mapper)

Role: take the macro regime from Layer 1 and translate it into sector-level views. Each sector desk is a specialist. The relationship mapper tracks cross-sector linkages (e.g. dollar strength → emerging markets → commodities).

### Layer 3 — "Superinvestor" personas (4 personas)

Druckenmiller, Aschenbrenner, Baker, Ackman. Each persona is a prompt-based agent embodying a specific investment style. They consume Layer 2's sector views and produce positioning recommendations through the lens of their style.

### Layer 4 — Decision (4 agents: CRO risk, alpha discovery, autonomous execution, CIO final)

Role: the gate. CRO risk reviews for risk discipline. Alpha discovery looks for edge. Autonomous execution prepares orders. CIO final is the last review before anything goes to market. The CRO→CIO gating is the safety layer — parallel to JARVIS' kill-switch and mandate gate discipline.

---

## The autoresearch keep/revert loop

This is the most concrete, reusable pattern. The loop:

1. **Identify the worst-performing agent** (by rolling Sharpe ratio over a recent window).
2. **Generate one prompt tweak** targeting that agent's weakness.
3. **Create a feature branch** in git with the tweaked prompt.
4. **Run a 5-day trial** with the tweaked agent.
5. **Keep or revert:**
   - If the agent's Sharpe improved → `git merge` the feature branch (the tweak is kept).
   - If not → `git reset` to discard the tweak (no drift, fully auditable).

**Key safety property:** every modification is either committed or reset. There is no silent drift. The git history is the audit trail. The 5-day window is short enough to iterate but long enough to get a meaningful Sharpe sample.

**Honest result:** 54 modifications attempted, 16 kept, 37 reverted — a 29.6% keep rate. Most tweaks don't help. This is exactly the kind of evidence JARVIS' backtest critique and strategy registry should cite when resisting overengineering: a fancy autoresearch loop that tries 54 things keeps only 16.

---

## Agent Sharpe as the loss function

The system weights recommendations by conviction, flips the sign for shorts, computes a rolling Sharpe ratio per agent, and targets the worst performer for modification. This is a concrete, defensible metric for "which agent needs attention." JARVIS' existing gate-v2 already computes similar per-component metrics; the atlas-gic pattern shows how to drive agent improvement from them rather than just monitoring them.

---

## What JARVIS should borrow

1. **Layered multi-agent filtration as a reference architecture.** The 4-layer structure (regime → sector → persona → decision) is a clean way to think about a discretionary-oversight multi-agent flow where no single agent has execution authority. JARVIS' current agent pipeline (`engine/llm/`) is more linear; the atlas-gic layering is a useful reference for how to structure a discretionary overlay without giving every agent trade authority. The CRO→CIO gating at Layer 4 is especially relevant to JARVIS' risk/kill-switch discipline.

2. **Autoresearch keep/revert loop with git versioning.** The pattern — modify → trial → measure → `git merge` if better, `git reset` if worse — is a clean, auditable evolution loop that JARVIS could adopt for any prompt-based strategy component. The safety property (no silent drift) is the valuable part.

3. **Per-agent Sharpe as improvement driver.** Computing a rolling Sharpe per agent and targeting the worst performer is a concrete, defensible metric for agent improvement. JARVIS' gate-v2 already computes similar metrics; the atlas-gic pattern shows how to use them to drive improvement, not just monitoring.

4. **Honest negative result as anti-overengineering evidence.** −5.91% over 378 days, 29.6% keep rate. A fancy 4-layer autoresearch system still lost money. This is a strong data point for JARVIS' strategy registry and backtest critique: sophisticated agent infrastructure does not guarantee profit. The `backtest-critique-checklist.md` and strategy registry promotion gate should cite this.

---

## What JARVIS should NOT borrow

1. **No autoresearch loop that modifies prompts based on live PnL without its own safety review.** JARVIS already has deterministic gates (kill-switch, mandate gate, risk limits). An autoresearch loop that modifies agent prompts based on live PnL would need its own safety review and must not touch the kill-switch or broker routing. The atlas-gic loop is a *research* pattern, not a deployment recipe.

2. **No prompts.** The `prompts/` directory in atlas-gic contains proprietary agent prompts — excluded. The architecture note describes the *structure* of the agent flow, not the specific prompts.

3. **No execution wiring.** The autonomous execution agent at Layer 4 is venue-specific and excluded. JARVIS' execution/risk layer is IB Gateway futures — a different surface.

4. **No expectation that the 4-layer structure transfers directly.** atlas-gic is equity-focused with a macro→sector→persona chain that doesn't map 1:1 onto JARVIS' futures strategy surface. The *pattern* (layered filtration with a gated final decision) is transferable; the specific layers are not.

---

## Verification

- File-tree census and content extraction read back from GitHub API / raw.githubusercontent.com before writing.
- No fork default branch modified.
- `gh repo view` confirms `mattamundson/atlas-gic` is `isFork: true`, `isArchived: false`, `visibility: PUBLIC`, topics `reference, trading-research, vendor-fork`.

---

*This note distills architectural patterns from a reference fork for JARVIS' agent-governance and strategy-research documentation. It is not a trading strategy, not an execution surface, and not a recommendation to deploy any autoresearch loop in production. The −5.91% result and 29.6% keep rate are the honest headline.*
