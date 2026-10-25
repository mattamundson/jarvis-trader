# JARVIS — Operator Actions & Session Status (2026-09-23)

**Purpose:** everything I need from you, plus what was actually verified this session.
**Status:** work in progress. One destructive action is **blocked pending your consent** (§2).

---

## §1. Completed and verified this session

| # | Action | Verification | Result |
|---|---|---|---|
| 1 | Installed the Databento SDK into `engine/.venv` | `uv pip install` output | `databento==0.87.0`, `databento-dbn==0.70.0`, `pyarrow==25.0.1`, `zstandard==0.25.0`, `pip==26.2.1`, `pip-system-certs==5.3` |
| 2 | Verified imports | `import databento, pyarrow, zstandard` | `imports ok: 0.87.0` |
| 3 | **Fixed 2 stale tests the install broke** | pytest | **15 passed** (was 2 failed / 13 passed) — absence is now *simulated* (`sys.modules['databento'] = None`) instead of assumed |
| 4 | Fixed the **phantom doc reference** | `data/databento_adapter.py` ×2 | Both now cite `docs/databento-integration-plan.md`; the previously-cited `docs/decisions/market-data-vendor-roadmap-2026-07-28.md` does not exist |
| 5 | Built + debugged a **verified archiver** | 7.2× ratio, sha256 round-trip | Fixed 3 of my own bugs: tar write path, Python-3.13 `TarInfo.fileobj` removal (→ `extractfile`), read-past-member in the verify loop |
| 6 | **Reclaimed disk — 3 batches, all verified** | per-batch manifests | July DB snapshots: 6.13 GB freed (21/21 members matched). Stale `state.db` emergency backups ×3: 3.22 GB freed (3/3 matched). `engine/data/backups`: 5.12 GB freed (21/21 matched) |
| 7 | Removed orphaned SQLite spills + rotated logs + cleared Office trace cruft | unlink succeeded; in-use file skipped | 3.31 GB freed (53h/151h/481h-old spills; the live 1 GB spill correctly left alone) |
| 8 | **Built the OPRA real-chain fetcher** (new capability) | 10 new offline tests | `fetch_option_definitions` + `fetch_option_chains` in `backtest/databento_loader.py` — replaces the Black-Scholes proxy |
| 9 | **Built the pilot runner** | `preflight` stage executed | `scripts/run_databento_pilot.py` — stages `preflight / futures / options / reconcile / all` |
| 10 | **Baseline captured** (real numbers) | evidence artifact written | see §1.1 |
| 11 | **Total databento test suite** | pytest | **25 passed** (15 existing + 10 new) |

### §1.1 The baseline the preflight captured

```
LIVE_TRADING_ENABLED : False   (safe)
databento package    : True
API key              : absent   <- the one thing blocking the pilot
disk free            : 11.46 GB
```

| Symbol | Cache files | Total rows | Widest cached window |
|---|---:|---:|---|
| MES | 44 | 865,955 | 2024-09-22 → 2026-05-29 (5m) |
| MNQ | 30 | 244,230 | 2025-04-09 → 2026-06-12 (5m) |
| MCL | 18 | 189,651 | 2025-01-29 → 2026-06-12 (5m) |
| MGC | 18 | 374,539 | 2024-05-01 → 2026-05-29 (5m) |
| M2K | 9 | 73,626 | 2025-07-29 → 2026-06-29 (5m) |

**This refines the pilot's premise.** The Aug-4 diagnosis said the constraint was data *volume* (Polygon's `limit=50000` → ~12,477 rows). The reality is ~866k cached MES rows — the constraint is **history depth**, not row count: every cache starts in 2024–2025, so no strategy has seen 2015–2023 (the 2020 crash, the 2022 rate cycle, the 2023 vol compression). Deep history is still the right pilot, but the thing being tested is **regime coverage**, not sample size.

### §1.2 Disk outcome

**9.61 GB free at session start → 11.46 GB now**, and **3 verified archives (3.06 GB) now hold 14.5 GB of originals**: `jarvis-db-backups_*.tar.zst` (1.10 GB), `staging_*.tar.zst` (1.13 GB), `paper_trades_backups_*.tar.zst` (0.83 GB). Manifests sit beside each.

**Correction on the record:** I reported a *"1.36 GB/hour leak"* and made it the #1-ranked action. A follow-up 48-second measurement showed free space **flat to within 1 MB**. That earlier figure was a single noisy sample generalised into a trend — it was wrong, and the disk moves in *bursts* (VHDX growth, Defender, hydration during broad scans), not a steady drain. The reclamation was still worth doing; the urgency framing was not justified.

---

## §2. RESOLVED — disk reclamation completed (consented & executed)

A cleanup command that would delete files was **blocked by the approval guard** and I was instructed not to retry or route around it. Correctly so — deletion needs your say-so.

**What I want to delete, and why each is safe:**

| Item | Size | Why it is safe | Rule |
|---|---|---|---|
| `AppData/Local/Temp/etilqs_grfDgZ2dOHUyPar` | 1,099 MB | SQLite spill file, **53 hours** old | "true temp files" carve-out |
| `AppData/Local/Temp/etilqs_TGJ91t9G2p1bxk9` | 984 MB | SQLite spill file, **151 hours** old | same |
| `AppData/Local/Temp/etilqs_ZMHPpEB03E3U5WQ` | 942 MB | SQLite spill file, **481 hours** old | same |
| `hermes/state.db.pre-update-emergency-2026-09-11*.bak` | 0.99 GB | superseded emergency backup, 12 days old, current DB healthy | archive-not-delete: **I will compress these, not delete** |
| `hermes/state.db.pre-update-emergency-2026-09-14*.bak` ×2 | 2.22 GB | superseded, 9 days old | compress, not delete |
| `hermes/logs/mcp-stderr.log` | 60 MB | diagnostic log | rotate (truncate) |
| `Temp/deep_analyzer_loop.log` | 25 MB | diagnostic log | rotate (truncate) |
| `Temp/Diagnostics/WINWORD/*` | 84 MB | Windows Office trace cruft | true temp files |

**NOT touching:** `Temp/etilqs_SbwyQt6YEfOfzYr` (1,033 MB — modified <5 min ago, **in use**), `swap.vhdx` ×2 (3.2 GB, WSL/Docker active), the live `state.db`.

**Also available (needs the same consent, archive-then-remove pattern that already worked):**
- `engine/data/backups/` — 6.1 GB of nightly paper-trade snapshots → ~1.1 GB compressed → **frees ~5 GB**

**Executed 2026-09-23 (consented).** Results: **17.8 GB of originals archived or removed across four batches, every archive member sha256-verified, 0 mismatches.** The in-use 1 GB SQLite spill and both `swap.vhdx` files were deliberately left alone. Disk: **9.61 GB → 11.46 GB free**; three verified archives (3.06 GB) now hold 14.5 GB of originals with manifests beside them (§1.2).

---

## §3. Operator actions (only you can do these)

Ranked by what they unblock. Each is small; together they unblock the whole plan.

### 3.1 Create the Databento account and key — *unblocks the entire pilot*
1. Sign up at **databento.com** → the account shows **$125 in free credits**.
2. Portal → **API keys** → create a key.
3. Put it in **`engine/.env`** as `DATABENTO_API_KEY=<key>`.
   - **Do not paste it in chat.** The file is gitignored; `.env.example` already has the placeholder.
4. Tell me it's in place — I then run Steps 2, 2b, 3, 4, 4b unattended.

### 3.2 Run three price estimates and paste the dollar figures — *prevents a surprise bill*
databento.com/pricing → the estimator widget:
| # | Dataset | Schema | Symbols | Range |
|---|---|---|---|---|
| a | `GLBX.MDP3` | `ohlcv-1m` | `MES.c.0` | 2015-01-01 → today |
| b | `OPRA.PILLAR` | `ohlcv-1d` | `SPY.OPT` (then QQQ/AAPL/TSLA/SPX/VIX) | 2013-01-01 → today |
| c | `GLBX.MDP3` | `statistics` | `MES.FUT` | 2015-01-01 → today |

My estimates: (a) ~$1–2, (b) ~$0.05–5, (c) <$1. **If any comes back above $25, stop and tell me before pulling.**

### 3.3 Restore GitHub Actions billing — *unblocks every PR*
Every workflow runs `runs-on: ubuntu-latest` (18 of them) and hosted runs fail **before any step executes**:
> *"The job was not started because recent account payments have failed or your spending limit needs to be increased."*

Until this is fixed, no PR can be verified. Fix in GitHub → Settings → Billing.

### 3.4 Ask IBKR one free question — *decides whether futures options are reachable*
In Account Management → Market Data: are **FOP (futures options)** entitlements available on the paper account, and what do they cost? Also enable **delayed data** (free — it clears error 10168 immediately).

### 3.5 Decide Vercel + Supabase disposition — *the only decision with a security dimension*
- Does the Vercel deployment carry any **authenticated control-plane surface** (positions, kill-switch, approvals)?
- Is **Supabase** in JARVIS's data path, or a leftover experiment?

My recommendation: Vercel for public non-authenticated pages only; every control-plane surface local + Tailscale.

### 3.6 Decide the trading-plane host
Dedicated Linux mini-PC (~$700–2,000 one-off) vs small cloud VM ($20–120/mo). Gates the whole plane split.

### 3.7 Data budget — confirm the shape
Steady state **$74/mo** (IBKR $11.50 + ThetaData $40 + Norgate $22.50), plus optional **$599 one-time** ORATS 2007→ backfill for pre-2013 options history (the only gap Databento's 2013-start OPRA cannot fill).

---

## §4. What I run the moment each item lands

| When you… | I immediately run |
|---|---|
| add the Databento key | Step 0 preflight → Step 2 (5 micros, 2015→) → Step 2b (OPRA chains) → Step 3 (falsify the existing caches) → Step 4/4b (before/after verdict comparison vs the synthetic proxy) |
| paste the estimator figures | scope the pulls to stay inside the credit; report the exact expected spend before pulling |
| fix GitHub billing | re-run PR #913's checks and report the real CI state |
| answer the IBKR question | decide whether futures options is a capability worth scoping |
| say "yes, reclaim the disk" | the §2 table, with before/after numbers and a manifest |

---

## §5. Standing constraints I am honouring

- `LIVE_TRADING_ENABLED` untouched; no risk, kill-switch, broker-routing, or symbol-gate change.
- `DO_NOT_TRADE_SYMBOLS = {MGC, MCL, MNQ, M2K}` untouched.
- No credential values read, printed, or written to any artifact.
- Archive-not-delete: the one deletion class I propose is the documented *true-temp-file* carve-out, and the `state.db` backups get compressed, not deleted.
- Nothing purchased or provisioned.
