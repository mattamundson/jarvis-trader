# Backtest bar cache — `engine/backtest/cache/`

**The cache directory is intentionally git-ignored** (`.gitignore:102`). Bar CSVs are
large and fully regenerable, so they live only on the machine that fetched them. A fresh
clone (or a cloud sandbox) has **no bars** — regenerate them before backtesting.

## File naming

```
{SYMBOL}_{START}_{END}_{TIMEFRAME}[_cont].csv
e.g.  MES_2024-09-22_2026-05-29_5m_cont.csv
```

- `_cont` = back-adjusted **continuous** contract (rolled), used by the backtester/optimizer.
- Loaders pick the cache file by **latest END date** (not lexicographic filename) — see
  `_pick_cache_file` in `run_atr_trail_bounce.py` and `_find_latest_cache` in
  `_gate_v2_helpers.py`. Do not assume `sorted(glob)[-1]`.

## Regenerating the cache

Futures bars come from **IBKR Gateway** (paper port 4002 must be up). Polygon's free plan
has had futures **blocklisted since 2026-04-16**, so Polygon only works for equities/ETFs.

### Futures (MES, MNQ, MGC, MCL, M2K) — IBKR, canonical

```bash
cd engine
# extend every cached futures CSV to the current date (1h default):
.venv/Scripts/python -m backtest.refresh_ibkr_futures_data
# dry run / subset:
.venv/Scripts/python -m backtest.refresh_ibkr_futures_data --dry-run
.venv/Scripts/python -m backtest.refresh_ibkr_futures_data --symbols MES MGC
```

For 5m / 15m intraday futures pulls, use the IBKR intraday fetcher:

```bash
.venv/Scripts/python -m scripts.fetch_ib_intraday --symbol MES --interval 5m
```

### Equities / ETFs — Polygon

```bash
cd engine
.venv/Scripts/python -m backtest.fetch_intraday --symbol SPY --interval 5m --days 730
```
Requires `POLYGON_API_KEY` (in `engine/.env`).

## Known data-quality caveats (MES 5m)

- The MES 5m cache has ~8 gaps Aug–Dec 2025; only **Dec-2025 → Jun-2026** is fully
  trustworthy. Treat full-sample 5m results before Dec-2025 with caution.

## Why not commit the bars?

They are large (multi-MB each, 40+ files), binary-ish, and regenerable from IBKR/Polygon
in minutes. Committing them bloats the repo and the history. Regenerate instead.
