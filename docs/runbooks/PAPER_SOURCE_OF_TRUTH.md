# Paper trading — source of truth (Tier A)

**Goal:** One default ledger for dashboard, alerts, and human decisions. Ambiguity between JSON files, `paper_runner`, and engine DB causes **RISK-006** (dual ledger divergence).

## Canonical recommendation (default)

| Surface | Primary source | Notes |
|---------|----------------|--------|
| **Dashboard / API** | Engine **SQLite** + `/portfolio/*` endpoints | Portfolio tracker, paper positions, history |
| **Validation progress** | `/paper/validation/*` and related routers | Aligns with WFE / gate UX |
| **Optional sync** | `paper_runner` → engine POST when `JARVIS_ENGINE_URL` + API key set | See [INTEGRATED_ROADMAP_2026-04.md](../plans/INTEGRATED_ROADMAP_2026-04.md) §1–2 |

## Operator rules

1. **Pick one** path for daily ops and document it in your session log.
2. If you use **both** standalone `paper_runner` files and the engine, run a **periodic reconciliation** (counts, last trade id, or notional) and treat divergence as a **P0 bug**.
3. **IB Gateway paper** remains the broker truth for fills when connected; engine state should **reflect** broker state after sync (see [P0_PAPER_IB_VERIFICATION.md](P0_PAPER_IB_VERIFICATION.md)).

## Definition of Done (P0-2)

- [ ] Default SoT named in this file or a one-line pointer in [docs/CURRENT_STATE.md](../CURRENT_STATE.md).
- [ ] Dashboard widgets that show paper P&amp;L / positions use that SoT only.
- [ ] Runbook note for “when `paper_runner` only” vs “engine only” vs “synced”.

## Related

- [07_EXECUTION_SPINE.md](../strategic/07_EXECUTION_SPINE.md) — P0-2
- [PAPER_LEDGER_BOUNDARIES.md](PAPER_LEDGER_BOUNDARIES.md) (if present in repo)
