---
repo: grananqvist/Awesome-Quant-Machine-Learning-Trading
url: https://github.com/grananqvist/Awesome-Quant-Machine-Learning-Trading
stars: 3581
language: null
license: null
archived: false
pushed_at: 2025-05-21
analyzed_at: 2026-04-17
recommendation: partial-integrate
surfaces_with_value: [engine-code, docs, project-rules]
shipped:
  - file: .claude/rules/ml-pitfalls-defense.md
    surface: project-rules
    date: 2026-04-17
    what: "9-pitfall defensive checklist synthesizing López de Prado + Aronson; cites SSRN/Wiley primary sources rather than curated list since curated list has no LICENSE"
deferred:
  - what: "research-corpus doc at docs/strategy/ml-trading-research-corpus.md annotating 20-25 key papers for post-paper-trading roadmap"
    reason: "lower urgency than rule — rule is actionable on every optimizer PR; corpus is background reading"
---

# grananqvist/Awesome-Quant-Machine-Learning-Trading

## Core value proposition

Curated list of 200+ resources (books, papers, courses, blogs) focused on machine learning + quantitative trading. Awesome-list format: pointers only, no code. 3,500+ stars, actively maintained through 2025.

## Surface analysis

### 1. Engine code
**partial-integrate** — The README catalogs ML techniques (LSTM, CNN, ensemble, RL, time-series forecasting) that jarvis-trader already implements partially. Specific gaps: (a) Deep Reinforcement Learning (DRL) — jarvis-trader has basic `stable-baselines3` but not production-grade DRL agents in `engine/agents/`; (b) attention mechanisms / Transformers — not present; (c) adversarial training (GAN) — not present. Papers on these (e.g., "Deep Learning Networks for Stock Market Analysis", "Improving Stock Movement Prediction with Adversarial Training") are useful for future roadmap but don't provide code. Walk-forward eval (WFE) and ensemble scoring already wired (`engine/analytics/ic_ensemble.py`, WFE at `engine/backtest/`). No actionable code to integrate here.

### 2. Project rules
**integrate-now** — López de Prado's "10 Reasons Most ML Funds Fail" (paper link line 79) and "The Myth and Reality of Financial ML" (line 86) align directly with existing safety rules. Recommend documenting jarvis-trader's defenses against overfitting (WFE=0.82–0.57 passing threshold), portfolio concentration (MCL+MNQ only, $5K/instrument cap), and out-of-sample validation as a `.claude/rules/` entry referencing these papers. New file: `.claude/rules/ml-pitfalls-defense.md`.

### 3. Project skills
**no-fit** — Awesome-list has no skill templates. The papers and interviews (e.g., "Chat with Traders" episodes on ML) contain strategic wisdom but require manual synthesis, not direct skill wiring.

### 4. Slash commands
**no-fit** — No quick-action patterns applicable to list curation.

### 5. Subagents
**defer** — Papers on "CNNPred: CNN-based stock market prediction" (line 110) and "Genetic Algorithm-Optimized LSTM" (line 111) suggest specialized research subagent designs (e.g., neural-architecture search for regime classification). Not blocking; defer to post-paper-trading optimization cycle.

### 6. Docs
**integrate-now** — Add `.md` entry in `docs/strategy/` or `docs/digest/` referencing: (a) López de Prado's papers for ML risk framework; (b) Aronson's "Evidence-Based Technical Analysis" (line 24) for statistical rigor; (c) "Practical Deep Reinforcement Learning Approach for Stock Trading" (line 80) and "Deep Direct Reinforcement Learning for Financial Signal Representation" (line 107) as inspiration for extending debate agents to DRL. Link from existing roadmap (`docs/session-logs/roadmap-2026-04-15.md`). New file: `docs/strategy/ml-trading-research-corpus.md` (1-2 pages, abstract + 20–30 key papers with jarvis-trader relevance).

### 7. Dev tooling
**no-fit** — Awesome-list is pure content. No CI, build, or automation patterns.

### 8. Dashboard
**no-fit** — No dashboard component library in list. The papers reference visualization of limit-order books (Sirignano, line 115) and deep learning predictions, but no widget code.

### 9. Ops / messaging
**no-fit** — No operational patterns in list.

## Integration plan

**High priority (1 session, <2hr total):**
- Create `.claude/rules/ml-pitfalls-defense.md`: 1-page rule checklist covering López de Prado's 10 pitfalls, with cross-references to jarvis-trader code (WFE sentinel, portfolio caps, regime gates). Link in `.claude/rules/README.md`.
- Create `docs/strategy/ml-trading-research-corpus.md`: Annotated abstract of 20–25 key papers from the list (López de Prado, Aronson, Sirignano, Jansen, Halls-Moore, DRL subset). Format: `| Author | Title | Link | Relevance to JARVIS | Status (todo/deferred) |`.

**Low priority (roadmap, defer):**
- Subagent for neural-architecture search (paper: line 111, "Genetic Algorithm-Optimized LSTM Network"). Blocks: requires PyTorch + NAS framework (not in requirements).
- DRL extension to debate agents (papers: lines 80, 107). Blocks: current `stable-baselines3` is test-only; production wiring needed. Ties to roadmap item T3.X.

## License & attribution

**License:** Awesome-list itself is typically MIT (no LICENSE file present, but `.md` is curation not code). Pointers' own licenses vary: papers (SSRN, arXiv, ACM) have academic use licenses; books/courses are proprietary. Safe to reference all without code copy.

**Attribution:** Add to `docs/strategy/ml-trading-research-corpus.md` header: "Curated from [grananqvist/Awesome-Quant-Machine-Learning-Trading](https://github.com/grananqvist/Awesome-Quant-Machine-Learning-Trading) (3,500+ stars, maintained 2025)."

## Effort estimate

**S** (< 2 hours) — Two `.md` files, both synthesis of existing documentation + listed papers. No code, no testing.

## Red flags

- **No direct code:** Awesome-list is curation. Integration value is intellectual (rules, docs) not implementation.
- **License ambiguity:** Repository has no LICENSE file. Treat as "reference-only" — cite papers directly from list, not from repo's own writings.
- **Duplicate effort risk:** Some papers (López de Prado, Aronson) may already be referenced in existing roadmap or MEMORY. Check before writing corpus file.
- **DRL gap:** Papers on deep RL exist (lines 80, 107), but stable-baselines3 + torch in requirements are not production-wired. Don't oversell DRL capabilities in docs.

---

**Verdict:** Awesome-list serves as **research compass, not code library**. Recommend low-effort doc synthesis to anchor ML risk/safety culture and identify 2–3 high-ROI DRL research papers for post-paper-trading roadmap. Library itself: reference freely, no integration risk.
