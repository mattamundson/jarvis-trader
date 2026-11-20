# ES read system (`/workspace/tape/system`)

Paper / read-only tooling that grades overnight reads, gates bias changes, prints a pre-read checklist, finds analog sessions, and summarizes event playbooks.

**Live legal? NO, size 0. Never places orders. Never touches engine/IB processes beyond existing read-only data files.**

## What is here

| Path | Role |
|------|------|
| `calls.jsonl` | Append-only call log (schema in `schema/call.schema.json`) |
| `grade_calls.py` | Scores each call at +30m / +60m / session-end; hit-rate by hour & setup; baselines |
| `bias_gate.py` | Bias may change only on a **15m close** beyond a **pre-named** level |
| `checklist.py` | Pre-read header; missing/stale items first; stale gamma (>60m) excludes levels |
| `analogs.py` | Top-10 similar overnight sessions + 1h/3h/RTH-open outcome distros |
| `event_stats.py` | NFP/CPI/FOMC first 5/15/30m ES move distributions (sample size marked) |
| `dashboard-scoreboard-spec.md` | Draft (no PR) for nightly dashboard scoreboard page |
| `data/` | Yahoo bars, VIX, event calendar, bias state (local cache) |
| `reports/` | Graded calls, hit rates, checklist, analogs, event stats |
| `tests/` | pytest |

Sibling context builder owns `/workspace/tape/context/es-context-latest.md` + `build_context.py`. This package **consumes** that file when present and does not rebuild it.

## Repo layout (imported from JarvisBox 2026-11-20)

In this repo the package lives at `scripts/tape/system/` (box: `/workspace/tape/system/`).
Every hardcoded `/workspace/tape/...` path now resolves through `TAPE_ROOT`:

- unset → defaults to `scripts/tape/` in the repo (data/reports committed here are the 2026-11-13 box snapshot)
- on the box → `export TAPE_ROOT=/workspace/tape` to keep the original behaviour

Box-only inputs that are **not** in the repo (large or live): `ovn/es_1m_dbn.parquet` (Databento),
`state/*.json` (IB/engine mirrors), `context/es-context-latest.md`. Modules degrade to the Yahoo
fallback or report the input as missing; they never invent values.

```powershell
# Windows, from the repo root
cd scripts\tape\system
..\..\..\engine\.venv\Scripts\python.exe -m pytest tests regime\tests -q   # 27 tests
$env:TAPE_ROOT = "$env:TEMP\tape-scratch"   # point writes at a scratch copy so committed reports stay frozen
```

## Quick start (box)

```bash
cd /workspace/tape/system
/workspace/tape/databento/.venv/bin/python -m pytest tests -q
python3 checklist.py
python3 bias_gate.py --demo
python3 grade_calls.py
python3 analogs.py
python3 event_stats.py
```

## Call schema (one JSON object per line)

Required: `ts_ct`, `bias`, `lean_pct`, `named_levels`, `triggers`, `invalidation`, `data_freshness`, `setup_type`.

See `schema/call.schema.json`. Tonight’s six Claude overnight reads (21:22–22:44 CT) are backfilled in `calls.jsonl` with Yahoo ES=F 1m prices.

## Grading rules

- **Bullish HIT**: window close ≥ price_at_call, or upside trigger level traded.
- **Bearish HIT**: window close ≤ price_at_call, or downside trigger level traded.
- **Neutral HIT**: contained move (|Δ|≤8 or window range ≤12).
- **MFE/MAE**: points in lean direction from price_at_call.
- **Baselines**: (1) no-change abs error; (2) prior RTH range holds (databento meta preferred).

Windows that extend past available bars are marked `INCOMPLETE`.

## Bias gate

Named levels live in `data/bias_state.json` (`break_up`, `break_down`). A mid-bar “bearish flip” without a 15m close ≤ `break_down` is rejected and the prior bias is kept. Neutral/watch is always allowed (de-risk).

## Data sources (no new purchases)

- **Primary (IB/engine):** `/workspace/tape/state/price-latest.json`, `engine-bars-es-1m.json`, `engine-bars-nq-1m.json`, `engine-prices-snapshot.json`, `flow-latest.json` — fed by engine `GET /analyze/bars/{symbol}` and `GET /prices/snapshot` on AmoSZN (`http://127.0.0.1:8010`, IB Gateway 4001). Checklist prints `Price source` + age; Yahoo only if IB/engine unreachable or age > 2 min.
- Yahoo ES=F / NQ=F / ^VIX (delayed ~10m) → `data/es_yahoo_7d_*.json` (**labeled fallback only**)
- Databento GLBX.MDP3 already on box (`/workspace/tape/databento`, `/workspace/tape/ovn/es_1m_dbn.parquet`) — any fresh pull must use existing `backfill.py --max-cost`
- ZeroGEX snapshot in `/workspace/tape/state/gex-latest.json` (read-only)

## Gaps / paid options (needs Matt’s yes before buying)

See report section in the parent handoff. Nothing was purchased in this build.

## Proof-record files

Do **not** edit `state/proof-record.json`, `scored-setups.csv`, or `paper-journal.md` from this package.
