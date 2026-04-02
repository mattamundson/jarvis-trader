# P0 — Paper trading & IB Gateway verification checklist

**Purpose:** Close the gap between “engine says healthy” and **broker truth** (fills, positions), and between **`paper_runner` JSON** and **engine portfolio APIs**.  
**Tier:** Operational — does not change `signals.py` or safety limits.  
**Related:** [PAPER_TRADING.md](PAPER_TRADING.md) (full IB setup), [INTEGRATED_ROADMAP_2026-04.md](../plans/INTEGRATED_ROADMAP_2026-04.md) (priorities P0–P4).

---

## 1. Preconditions

| Item | Expected |
|------|----------|
| Engine | `LIVE_TRADING_ENABLED = False`, paper mode |
| API key | Dashboard `NEXT_PUBLIC_ENGINE_API_KEY` matches engine `API_KEY` |
| Approved symbols | MCL 1h, MNQ 1h only for production paper attention per [CLAUDE.md](../../CLAUDE.md) |

---

## 2. IB Gateway (paper) — quick verify

1. Start **IB Gateway** (paper), socket **7497** on the host the engine uses (`IBKR_HOST` / `IBKR_PORT` in [engine/config.py](../../engine/config.py) or `.env`).
2. From the machine running the engine, confirm the port is open (PowerShell):

   ```powershell
   Test-NetConnection -ComputerName 127.0.0.1 -Port 7497
   ```

3. Start the engine (venv): `cd engine` → `.venv\Scripts\python -m uvicorn main:app --reload --port 8010`
4. Call health with your API key:

   ```powershell
   curl.exe -s -H "X-API-Key: YOUR_KEY" http://127.0.0.1:8010/health
   ```

   Note `ibkr_connected` (or full health payload). If disconnected, fix Gateway/login/API settings before trusting any “live” position data from IB paths.

**Deep setup:** use [PAPER_TRADING.md](PAPER_TRADING.md) Section 1–2.

---

## 3. Engine portfolio vs `paper_runner` (two paper worlds)

| Source | What it is | When it is authoritative |
|--------|------------|---------------------------|
| **A** `paper_runner` | `engine/backtest/results/paper_positions.json`, `paper_trades_live.json` | Hourly signal loop **without** full FastAPI |
| **B** Engine `PortfolioTracker` | SQLite + `/portfolio/paper/*`, `/portfolio/history/trades` | Dashboard and API consumers |

**Optional sync (A → B):** set on the host that runs `paper_runner`:

```text
JARVIS_ENGINE_URL=http://127.0.0.1:8010
JARVIS_API_KEY=<same as engine API_KEY>
```

Then entries/exits POST to `/portfolio/paper/trade` and positions can carry `engine_trade_id` in JSON.

**Checklist**

- [ ] You know which source ops uses today (A only, B only, or A+B with sync).
- [ ] Dashboard pages that show paper P&amp;L/positions are documented as reading **B** (or explicitly “file-backed” if you build that later).
- [ ] After a closed trade in A, if sync is on, **B** shows the close in `/portfolio/history/trades` (smoke test).

---

## 4. Dashboard ↔ engine (auth)

Global API key middleware is on the engine: unauthenticated browser calls to the engine **401**.

- [ ] `dashboard/.env.local` includes `NEXT_PUBLIC_ENGINE_API_KEY` matching engine.
- [ ] `pnpm dev` → open **Health** or **Paper** page; no repeated 401 in network tab for `/api/engine/*` proxy.

---

## 4.5 Automated checks (script)

With the engine listening on `8010` and `JARVIS_API_KEY` matching engine `API_KEY`:

```powershell
cd engine
$env:JARVIS_API_KEY = "your-key"
# optional: $env:CHECK_IB_PORT = "1"
.venv\Scripts\python scripts\verify_p0_paper_ib.py
```

The script prints JSON with per-route results. Use it before filling the sign-off table.  
**Paper source-of-truth** (A / B / A+B) is documented in [PAPER_DATA_SOURCES.md](PAPER_DATA_SOURCES.md).  
IB connector behavior summary: [IB_CONNECTOR_OVERVIEW.md](IB_CONNECTOR_OVERVIEW.md).

---

## 5. End-to-end smoke (paper, no live orders unless you intend)

**Only if** you are deliberately testing order submission through the stack (still paper account):

1. IB Gateway paper logged in; engine shows IB connected.
2. Use the smallest contract size your test plan allows; confirm human-approval gates if enabled.
3. Verify position appears in IB paper account **and** in engine portfolio/health surfaces you use.

If you are **not** sending orders yet, mark this section **N/A** and still complete Sections 2–4.

---

## 6. Sign-off

| Gate | Pass |
|------|------|
| IB socket reachable + engine reports connection state | ☐ |
| API key: dashboard ↔ engine aligned | ☐ |
| Paper data story documented (A / B / A+B) | ☐ |
| Optional `paper_runner` → engine sync tested or explicitly disabled | ☐ |
| E2E order smoke (optional) | ☐ N/A / ☐ Done |

**Owner / date:** _______________

---

*Add findings to [SESSION_LOG_2026-04-02.md](../session-logs/SESSION_LOG_2026-04-02.md) or the next session log when this checklist is executed.*
