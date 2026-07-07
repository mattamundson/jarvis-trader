# Validation gates

**Purpose:** Single pointer doc for **instruments**, **WFE policy**, and **Tier-3 code**.  
**Do not duplicate numeric thresholds here** — authoritative tables live in linked files.

---

## 1. Instrument policy (authoritative)

| Source | Content |
|--------|---------|
| [.claude/imports/validated-instruments.md](../../.claude/imports/validated-instruments.md) | Approved / halted symbols, WFE snapshot, capital, validation gate inequality |
| [CLAUDE.md](../../CLAUDE.md) | Session-facing summary table |
| [CURRENT_STATE.md](../CURRENT_STATE.md) | Operational snapshot |

**Rule:** If this strategic doc disagrees with **validated-instruments**, update **this doc** immediately.

---

## 2. Validation gate inequality (reference only)

Per validated-instruments (verify there for changes):

- PF ≥ 2.0  
- Sharpe ≥ 1.5  
- Win rate ≥ 55%  
- Trades ≥ 60  
- Days ≥ 30  
- Max drawdown ≤ 15%  

Paper capital and instrument specs are in the same file.

---

## 3. Tier-3 files (change control)

These require **explicit Tier 3 / human confirmation** before merge to production-aligned branches:

| File | Role |
|------|------|
| [engine/risk/safety_layer.py](../../engine/risk/safety_layer.py) | Kill switch and hard limits — **never LLM-driven** |
| [engine/config.py](../../engine/config.py) | `TradingConfig` and risk parameters |
| [engine/backtest/signals.py](../../engine/backtest/signals.py) | Canonical STC / signal parameters |

**Review skill:** `/review` (gstack) mandatory for safety-layer changes per [AGENTS.md](../../AGENTS.md).

---

## 4. Research and WFE playbooks

| Doc | Use |
|-----|-----|
| [docs/research/GATED_SYMBOLS_WFE_PLAYBOOK.md](../research/GATED_SYMBOLS_WFE_PLAYBOOK.md) | How gated symbols are evaluated |
| [docs/strategy/](../strategy/) | Strategy canon, equations, rules |
| [engine/backtest/](../../engine/backtest/) | Runners, walk-forward, optimizers |

**MES note:** In-sample headline performance (e.g. the old PF 5.3 / WFE 0.09 figures) is **not** a license to trade. MES was promoted to active paper on 2026-05-24 via the gate-v2 ALT path (p_edge 0.75), not the in-sample headline. See validated-instruments narrative.

---

## 5. Phase 3 gating (process)

| Doc | Use |
|-----|-----|
| [docs/runbooks/PHASE3_READINESS.md](../runbooks/PHASE3_READINESS.md) | Operational and safety gates for live transition |
| [docs/backlog/PHASE3_TODOS.md](../backlog/PHASE3_TODOS.md) | Tracked Phase 3 work |

**Canon:** [JARVIS_TRADER_UNIFIED_CANON.md](../JARVIS_TRADER_UNIFIED_CANON.md) § research truth ledger — any change to headline performance or thresholds follows canon update protocol.

---

## 6. Enforcement surfaces (where gates should appear)

| Surface | Intent |
|---------|--------|
| Engine | Order path, instrument allowlist, paper validation routers |
| Dashboard | Display approved vs experimental symbols clearly; avoid “UI-only” benchmarks as risk truth |
| Runbooks | Human checklist before changing ports or `LIVE_TRADING_ENABLED` |

Gaps between policy and enforcement should become **RISK** rows in [05_RISK_REGISTER.md](05_RISK_REGISTER.md).
