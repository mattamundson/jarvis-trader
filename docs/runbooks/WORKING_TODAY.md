# Working TODAY — single vertical slice

**One-sentence definition:** Engine on **8010**, dashboard on **3010**, `GET /health` OK, you **open one paper position** on **MCL or MNQ** via `POST /portfolio/paper/trade`, and **`GET /portfolio/paper/positions`** shows it — no LLM pipeline required.

---

## Authoritative path for this slice (default Tier-3)

| Path | Role |
|------|------|
| **Portfolio API** (`/portfolio/paper/trade`, `/portfolio/paper/positions`, `/portfolio/paper/performance`) | **Source of truth for “works today.”** Mutates `PortfolioTracker` directly. Does **not** require `LIVE_TRADING_ENABLED=True` or `REQUIRE_HUMAN_APPROVAL=False`. |

Use this path for daily smoke and dashboard alignment when you want the system demonstrable under repo-default safety posture.

---

## Optional: gated simulated fills (SafetyLayer + connector)

Orders that go through `SafetyLayer.check_order` / `submit_paper_order` (e.g. `IBOrderManager` → `IBGatewayConnector`) are blocked by `_check_gating_conditions()` when `LIVE_TRADING_ENABLED=False` **unless** you **explicitly** set:

```bash
ALLOW_PAPER_SIMULATED_ORDERS=True
```

**Semantics:** With `PAPER_TRADING=True`, `LIVE_TRADING_ENABLED=False`, and this flag **True**, gating allows order checks to proceed so **JSON/simulated** paper fills can run. This is **not** live broker submission. Default remains **False** — opt-in only, logged at INFO when active.

You still need order size/value within `TradingConfig` limits (e.g. `MAX_SINGLE_ORDER_VALUE`, `MAX_POSITION_SIZE_PCT`).

---

## Smoke automation

From repo root (Windows):

```powershell
.\scripts\smoke_working_today.ps1
```

Prerequisites: engine running on 8010. Auth: set `JARVIS_API_KEY` to match `engine/.env` `API_KEY`, or leave unset — the script reads `API_KEY` from `engine/.env` when present, else defaults to `jarvis-dev-key-change-me`.

Manual curl equivalents: see comments at top of `scripts/smoke_working_today.ps1`.

### IB-marked pytest (optional)

- **Offline** (no Gateway): `pytest engine/tests/test_ib_gateway_connector_offline.py -q`
- **With IB Gateway on paper port 4002**: `pytest engine/tests/test_ib_gateway_connector_safety_wiring.py -m integration_ib -v`  
  (`integration_ib` is registered in `engine/pyproject.toml`; without Gateway these tests skip.)

---

## What “working TODAY” is not

- Not the full 30-day validation metrics (see [CURRENT_STATE.md](../CURRENT_STATE.md)).
- Not IB Gateway **live** (port 4001 remains out of scope).
- Not “all 90+ routes green” — only the slice above.

---

## Related docs

- [PAPER_LEDGER_BOUNDARIES.md](PAPER_LEDGER_BOUNDARIES.md) — JSON vs tracker mirror
- [PAPER_TRADING.md](PAPER_TRADING.md) — paper runbook
- [../session-logs/SPRINT_BRIEF_TEMPLATE.md](../session-logs/SPRINT_BRIEF_TEMPLATE.md) — new-session charter
