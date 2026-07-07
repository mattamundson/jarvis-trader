"""B4 -- nightly cache-vs-SQLite bar reconciliation.

The B2 write-gate (``_row_rejection`` in ``bars_repository.save_bars``) stops NEW
poison at write time. This is its READ-path complement: it catches divergence
that already exists between the two authoritative bar stores --

  - the canonical historical cache (``engine/backtest/cache/*.csv``), and
  - the live rolling SQLite store (``market_data_bars``).

It would have caught the original 2,655-row contamination incident by comparing
the SQLite store against the clean cache, instead of only discovering it when a
backtest produced an implausible PF.

Invariant
---------
For every ``(symbol, 1h, timestamp)`` present in BOTH stores, the OHLC must agree.
Because ``market_data_bars`` has ``PRIMARY KEY (symbol, interval, ts_utc)`` with
``INSERT OR IGNORE``, each timestamp holds exactly ONE row, sourced either from:

  - the cache backfill (``source='cache'``) -- must match the CSV near-exactly,
    so a mismatch means a cache-derived row was corrupted in SQLite; or
  - a live vendor (``source in {tv, ibkr, polygon}``) -- may differ slightly from
    the cache's vendor, but a GROSS divergence signals contamination / a bad tick
    (the ``100.5`` sentinel or the 5300-MES class).

Hence two tolerances: tight for cache-sourced rows (should always be zero
mismatches), loose for live-sourced rows (flag only gross divergence).

Also reports COVERAGE gaps: cache timestamps missing from SQLite (backfill drift)
and SQLite timestamps absent from the cache window.

Exit codes
----------
    0 -- clean (no mismatches, gaps within tolerance)
    1 -- divergence or excessive coverage gaps found
    2 -- error (could not run a meaningful comparison)

Usage
-----
    python -m engine.scripts.reconcile_bars                  # all symbols, report
    python -m engine.scripts.reconcile_bars --symbols MES MGC
    python -m engine.scripts.reconcile_bars --alert          # TG/Discord if dirty
    python -m engine.scripts.reconcile_bars --json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

_ENGINE_DIR = Path(__file__).resolve().parent.parent
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("reconcile_bars")

# Reuse the backfill module's symbol->cache mapping and CSV loader so the two
# jobs can never disagree about which CSV is canonical for a symbol.
from data.bars_repository import load_bars  # noqa: E402
from scripts.backfill_market_data_bars import (  # noqa: E402
    ALL_SYMBOLS,
    _find_all_csvs,
    _load_csv,
)

# --------------------------------------------------------------------------- #
# Tolerances
# --------------------------------------------------------------------------- #
# Cache-sourced rows in SQLite are written from the same CSV, so they must match
# to within float-rounding. Anything above this means corruption of a stored row.
CACHE_TOL = 0.0005          # 0.05% relative
# Live-vendor rows legitimately differ a little from the cache's vendor at the
# same bar. Only a gross gap (contamination / bad tick) is worth flagging.
LIVE_TOL = 0.05             # 5% relative
# If more than this fraction of cache timestamps are missing from SQLite inside
# the overlap window, the backfill has drifted (or rows were deleted) -- warn.
MISSING_WARN_FRAC = 0.10
# If the overlap is implausibly small relative to the cache, the two stores are
# probably keyed differently (tz / format) -- that is itself a finding, not a
# clean run, because the reconciliation could not actually verify anything.
MIN_MATCH_FRAC = 0.20
# A futures roll / back-adjustment shifts EVERY OHLC of a bar by ~the same
# proportion (same sign). That is honest divergence between two stores that rolled
# on different schedules -- NOT a corrupted bar. Distinguish it from real
# corruption (a sentinel, a bad tick) which moves one or a few fields on their
# own, producing a large spread across the four per-OHLC relative diffs. A
# cache-sourced divergence that is uniform (spread tiny), same-signed, and within
# a sane roll gap is classified as a basis divergence and does NOT raise a
# corruption finding. (Closes the 2026-06 MES March-roll ~0.78% false alarm.)
BASIS_SPREAD_TOL = 0.001    # max allowed spread among the 4 per-OHLC rel diffs
BASIS_MAX_OFFSET = 0.05     # a "roll" larger than 5% is implausible -> corruption
INTERVAL = "1h"
_OHLC = ("open", "high", "low", "close")


def _norm_ts(series: pd.Series) -> pd.Series:
    """Normalise a timestamp column to the exact string form ``save_bars`` writes
    (``%Y-%m-%dT%H:%M:%S``), so cache rows key-match their cache-sourced SQLite
    counterparts. Mirrors ``save_bars`` (no utc coercion -- strftime drops tz to
    wall-clock, identically on both sides)."""
    dt = pd.to_datetime(series, errors="coerce")
    return dt.dt.strftime("%Y-%m-%dT%H:%M:%S")


def _ohlc_map(df: pd.DataFrame, with_source: bool) -> dict:
    """Build {ts_iso: (o, h, l, c[, source])}. First row wins on duplicate ts
    (matches INSERT OR IGNORE keep-first semantics)."""
    out: dict = {}
    for row in df.itertuples(index=False):
        ts = row.ts_key
        if ts in out or ts != ts:  # skip dup / NaT
            continue
        vals = (row.open, row.high, row.low, row.close)
        out[ts] = (*vals, row.source) if with_source else vals
    return out


def reconcile_symbol(symbol: str, db_path: Optional[Path] = None) -> dict:
    """Compare cache vs SQLite for one symbol. Returns a structured result."""
    res: dict = {
        "symbol": symbol,
        "cache_rows": 0,
        "sqlite_rows": 0,
        "matched": 0,
        "match_frac": None,
        "cache_only": 0,        # in cache, missing from SQLite (backfill drift)
        "sqlite_only": 0,       # in SQLite window, absent from cache
        "mismatches": 0,
        "cache_src_mismatches": 0,
        "cache_basis_divergences": 0,  # uniform roll/back-adjustment offsets (not corruption)
        "samples": [],          # up to 5 worst mismatches (no secrets, just bars)
        "findings": [],
        "error": None,
    }

    paths = _find_all_csvs(symbol)
    if not paths:
        res["error"] = f"no cache CSV for {symbol}"
        return res

    try:
        frames = [_load_csv(p) for p in paths]
        cache = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]
    except Exception as exc:  # noqa: BLE001
        res["error"] = f"cache load failed: {exc}"
        return res

    cache = cache.copy()
    cache["ts_key"] = _norm_ts(cache["timestamp"])
    cache = cache.dropna(subset=["ts_key"])
    res["cache_rows"] = len(cache)
    if cache.empty:
        res["error"] = "cache empty after normalisation"
        return res

    lo, hi = cache["ts_key"].min(), cache["ts_key"].max()

    sql = load_bars(symbol, INTERVAL, start=lo, end=hi, db_path=db_path)
    if sql is None or sql.empty:
        res["findings"].append(
            f"{symbol}: SQLite has 0 rows in the cache window -- backfill never ran?"
        )
        res["cache_only"] = len(cache)
        return res
    sql = sql.copy()
    sql["ts_key"] = _norm_ts(sql["timestamp"])
    if "source" not in sql.columns:
        sql["source"] = "unknown"
    sql["source"] = sql["source"].fillna("unknown")
    sql = sql.dropna(subset=["ts_key"])
    res["sqlite_rows"] = len(sql)

    cmap = _ohlc_map(cache, with_source=False)
    smap = _ohlc_map(sql, with_source=True)

    cache_keys = set(cmap)
    sql_keys = set(smap)
    matched = cache_keys & sql_keys
    res["matched"] = len(matched)
    res["cache_only"] = len(cache_keys - sql_keys)
    res["sqlite_only"] = len(sql_keys - cache_keys)
    res["match_frac"] = round(len(matched) / max(1, len(cache_keys)), 4)

    worst: list[tuple] = []
    for ts in matched:
        co, ch, cl, cc = cmap[ts]
        so, sh, sl, sc, src = smap[ts]
        tol = CACHE_TOL if src == "cache" else LIVE_TOL
        signed = []   # (sqlite - cache) / |cache| per OHLC, sign preserved
        for cv, sv in ((co, so), (ch, sh), (cl, sl), (cc, sc)):
            try:
                denom = abs(float(cv)) or 1e-9
                signed.append((float(sv) - float(cv)) / denom)
            except (TypeError, ValueError):
                signed.append(1.0)  # uncomparable value = treat as gross mismatch
        abs_rels = [abs(s) for s in signed]
        max_rel = max(abs_rels)
        if max_rel <= tol:
            continue  # the two stores agree on this bar

        # Roll / back-adjustment basis: every OHLC shifted by ~the same proportion
        # and sign, within a sane roll gap. Honest divergence, not a corrupted bar.
        spread = max_rel - min(abs_rels)
        same_sign = all(s > 0 for s in signed) or all(s < 0 for s in signed)
        if (
            src == "cache"
            and same_sign
            and spread <= BASIS_SPREAD_TOL
            and max_rel <= BASIS_MAX_OFFSET
        ):
            res["cache_basis_divergences"] += 1
            continue

        res["mismatches"] += 1
        if src == "cache":
            res["cache_src_mismatches"] += 1
        worst.append((max_rel, ts, src, (co, ch, cl, cc), (so, sh, sl, sc)))

    worst.sort(reverse=True)
    res["samples"] = [
        {
            "ts": ts, "source": src, "max_rel": round(rel, 4),
            "cache_ohlc": [round(float(x), 4) for x in c],
            "sqlite_ohlc": [round(float(x), 4) for x in s],
        }
        for rel, ts, src, c, s in worst[:5]
    ]

    # ----- turn raw counts into findings -----
    if res["match_frac"] is not None and res["match_frac"] < MIN_MATCH_FRAC:
        res["findings"].append(
            f"{symbol}: only {res['match_frac']:.0%} of cache bars matched a SQLite "
            f"timestamp ({res['matched']}/{len(cache_keys)}) -- stores keyed "
            f"differently (tz/format)? reconciliation unverified"
        )
    if res["cache_src_mismatches"] > 0:
        res["findings"].append(
            f"{symbol}: {res['cache_src_mismatches']} cache-sourced row(s) DIVERGE "
            f"from the CSV (>{CACHE_TOL:.2%}) -- a stored bar was corrupted"
        )
    live_mm = res["mismatches"] - res["cache_src_mismatches"]
    if live_mm > 0:
        res["findings"].append(
            f"{symbol}: {live_mm} live-sourced bar(s) diverge grossly "
            f"(>{LIVE_TOL:.0%}) from the cache -- contamination / bad tick"
        )
    if matched and res["cache_only"] / max(1, len(cache_keys)) > MISSING_WARN_FRAC:
        res["findings"].append(
            f"{symbol}: {res['cache_only']} cache bar(s) "
            f"({res['cache_only'] / len(cache_keys):.0%}) missing from SQLite -- "
            f"backfill drift"
        )
    return res


def _send_alert(message: str) -> bool:
    """Standalone TG + Discord push (mirrors the data-integrity sentinel path);
    self-contained so this script does not depend on engine notifier internals."""
    import os
    import urllib.request

    from dotenv import load_dotenv

    load_dotenv(_ENGINE_DIR / ".env")
    ok = False
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if token and chat:
        try:
            body = json.dumps({"chat_id": chat, "text": message[:4000]}).encode()
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data=body, headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=20) as r:
                ok = ok or r.status == 200
        except Exception:  # noqa: BLE001
            pass
    hook = (os.environ.get("DISCORD_WEBHOOK_URL") or "").strip()
    if hook:
        try:
            body = json.dumps({"content": message[:1900]}).encode()
            req = urllib.request.Request(
                hook, data=body,
                headers={"Content-Type": "application/json", "User-Agent": "reconcile-bars/1.0"},
            )
            with urllib.request.urlopen(req, timeout=20) as r:
                ok = ok or r.status in (200, 204)
        except Exception:  # noqa: BLE001
            pass
    return ok


def run(symbols: list[str], alert: bool, as_json: bool, db_path: Optional[Path] = None) -> int:
    results = [reconcile_symbol(s, db_path=db_path) for s in symbols]
    findings = [f for r in results for f in r["findings"]]
    errors = [r["error"] for r in results if r["error"]]

    if as_json:
        print(json.dumps({"results": results, "findings": findings}, indent=2, default=str))
    else:
        for r in results:
            tag = "ERROR" if r["error"] else ("DIRTY" if r["findings"] else "clean")
            print(
                f"[{tag}] {r['symbol']}: cache={r['cache_rows']} sqlite={r['sqlite_rows']} "
                f"matched={r['matched']} ({r['match_frac']}) "
                f"mismatch={r['mismatches']} basis={r['cache_basis_divergences']} "
                f"cache_only={r['cache_only']} "
                f"sqlite_only={r['sqlite_only']}"
                + (f" :: {r['error']}" if r["error"] else "")
            )
            for f in r["findings"]:
                print(f"    - {f}")
            for s in r["samples"][:3]:
                print(f"      ~ {s['ts']} [{s['source']}] rel={s['max_rel']} "
                      f"cache={s['cache_ohlc']} sqlite={s['sqlite_ohlc']}")

    if alert and (findings or errors):
        header = (
            f"BAR RECONCILE: {len(findings)} finding(s)"
            + (f", {len(errors)} error(s)" if errors else "")
        )
        body = header + "\n- " + "\n- ".join(findings + [f"ERROR: {e}" for e in errors])
        sent = _send_alert(body)
        # In --alert mode, the alert IS the signal. Exit nonzero only if we could
        # not warn -- so a scheduled task does not flag ITSELF as failed for
        # merely reporting a real, delivered finding (same contract as
        # jarvis_system_status.py --alert).
        return 0 if sent else 1

    if errors:
        return 2
    return 1 if findings else 0


def main() -> int:
    p = argparse.ArgumentParser(description="Reconcile cache CSVs vs market_data_bars")
    p.add_argument("--symbols", nargs="+", default=ALL_SYMBOLS, metavar="SYM")
    p.add_argument("--alert", action="store_true", help="push TG/Discord if dirty")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    symbols = [s.upper() for s in args.symbols]
    return run(symbols, alert=args.alert, as_json=args.json)


if __name__ == "__main__":
    sys.exit(main())
