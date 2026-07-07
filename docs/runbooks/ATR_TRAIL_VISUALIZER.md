# ATR-Trail Visualizer — local run

Renders the TOS `ATRTrailingStopLE/SE` flip strategy (the "dotted blue line")
on **your own cached bars**: price + the trail line colored by long/short state,
every flip entry/exit, the full-period equity curve, and the worst-12 losers.
This is the "show me WHERE and WHY it failed" view.

> The chart needs a **running engine** to read the cache bars. Vercel/preview
> deploys render the page shell but show "Could not load ATR-trail data" — there
> is no engine there. Local (engine + dashboard) is the only path that populates
> the chart.

## Prerequisites

- Cached bars for the symbol/timeframe under `engine/backtest/cache/`, e.g.
  `MES_..._5m_cont.csv`. As of `4ff0994d` the full bar cache (~164 CSVs, incl.
  several MES 5m files) is **committed to the repo**, so a clean clone already
  has them — no IBKR/Polygon fetch needed for the committed symbols. Newly-dated
  cache files stay gitignored unless force-added (see `CACHE_README.md`). The
  endpoint globs `{symbol}_*_{timeframe}*.csv` and picks the freshest by mtime;
  no bars → HTTP 404 "Run the IBKR fetch first."
- Engine venv (`engine/.venv/Scripts/python`) and dashboard deps (`pnpm install`).

## 1. Start the engine (http://localhost:8010)

```powershell
cd engine
.venv\Scripts\activate
python main.py        # or: .venv\Scripts\python -m uvicorn main:app --port 8010
```

Do **not** use `--reload` (duplicates IB connections). After config changes use
`.\restart_engine.ps1`.

## 2. Start the dashboard (http://localhost:3010)

```powershell
cd dashboard
pnpm install      # first time only
pnpm dev
```

Open **http://localhost:3010/atr-trail** (sidebar → Analysis → "ATR-Trail Viz").

Pick symbol / timeframe / period / factor. Defaults are `MES 5m`, period `5`,
factor `3.5` — the exact TOS line Matt watched. The page calls
`GET /backtest/atr-trail/trades` through `fetchEngine`; the badges show trade
count, net P&L, win rate, and the source cache file.

## 3. (optional) Verify the endpoint directly

Auth header is required (port 8010 is behind the API-key middleware). Read the
current key from `engine/.env` at use time — do not hardcode it.

```bash
curl -s "http://localhost:8010/backtest/atr-trail/trades?symbol=MES&timeframe=5m&period=5&factor=3.5" \
  -H "X-API-Key: <value from engine/.env>" | head -c 400
```

`200` with `n_trades`, `net_usd`, `win_rate`, `source_file` → working. `404` →
no cache bars for that symbol/timeframe. `500` → check engine logs.

## 4. (optional) Static PNG instead of the live page

For a shareable image + trade-by-trade JSON without the dashboard:

```bash
cd engine
.venv/Scripts/python -m backtest.plot_atr_trail_trades \
    --data-file backtest/cache/MES_..._5m_cont.csv \
    --out docs/reports/atr_trail_trades.png
# zoom to a window you watched live:
#   ... --start 2026-06-18 --end 2026-06-25
```

Writes `atr_trail_trades.png` + `atr_trail_trades.trades.json` (not gitignored —
safe to push for review).

## What the verdict already is

Across MES 1h and 5m, every MCPT variant of this strategy (bounce, flip,
confluence, Keltner, TPO-target) returns **REJECT** — see
`engine/docs/reports/atr_trail_modeall_MES.txt` and `..._5m.txt`. The visualizer
exists so the dead verdict is *shown*, not just asserted via a p-value. Per
`ml-pitfalls-defense.md`, REJECT means discard the spec — do not re-tune against
the same data.
