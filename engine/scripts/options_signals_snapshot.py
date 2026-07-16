"""
SPY/QQQ market-implied options snapshot generator for JARVIS TRADER.

Fetches the free CBOE delayed chains + VIX/VIX3M daily CSVs, computes the
market-implied analytics (ATM-straddle expected move, delta-implied
probability ladder, IV context, VIX/VIX3M term-structure regime) via
``analysis.options_implied``, and writes ``engine/data/options_signals/
latest.json`` for ``routers/options_signals_router.py`` to serve to the
/signals dashboard page.

Read-only pipeline: public data in, local JSON out. No LLM, no DB, no broker,
no Discord, no execution. Runs every 30 minutes via the ``jarvis-options-
signals`` scheduled task and self-gates to weekday RTH.

Unlike morning_framing_brief.py there is no ``--date`` flag — the source is a
live delayed feed, so a historical snapshot is not computable.

Usage
-----
    python -m engine.scripts.options_signals_snapshot            # RTH-gated live write
    python -m engine.scripts.options_signals_snapshot --dry-run  # fetch + print, write nothing
    python -m engine.scripts.options_signals_snapshot --force    # ignore the RTH gate

Exit codes: 0 = ok (or RTH-skip), 1 = usage error, 2 = degraded/partial.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("options_signals_snapshot")

# ---------------------------------------------------------------------------
# Path bootstrap — same pattern as morning_framing_brief.py
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = Path(__file__).resolve().parent
_ENGINE_DIR = _SCRIPTS_DIR.parent
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

from analysis.options_implied import (  # noqa: E402
    DEFAULT_SYMBOLS,
    build_snapshot,
    fetch_regime_block,
)

_CT = ZoneInfo("America/Chicago")

_DATA_DIR = _ENGINE_DIR / "data" / "options_signals"
_LATEST_PATH = _DATA_DIR / "latest.json"
_REGIME_CACHE_PATH = _DATA_DIR / "vix_term_structure.json"
_IV_HISTORY_PATH = _DATA_DIR / "iv_history.jsonl"
_EM_TRACKING_PATH = _DATA_DIR / "em_tracking.jsonl"

# RTH gate in CT: first fire a few minutes after the 08:30 CT equity open,
# last useful snapshot just after the 15:00 CT close print settles.
_RTH_START = (8, 30)
_RTH_END = (15, 5)

_LOG_TAG = "[OPTIONS SIGNALS]"


def _inside_rth(now_ct: datetime) -> bool:
    if now_ct.weekday() >= 5:  # Sat/Sun
        return False
    minutes = now_ct.hour * 60 + now_ct.minute
    return _RTH_START[0] * 60 + _RTH_START[1] <= minutes <= _RTH_END[0] * 60 + _RTH_END[1]


# ---------------------------------------------------------------------------
# Regime block with a once-per-day cache
# ---------------------------------------------------------------------------


def _load_regime_cache() -> Optional[dict]:
    try:
        return json.loads(_REGIME_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


async def _regime_for_today(today_iso: str) -> tuple[Optional[dict], Optional[str]]:
    """→ (regime_block | None, error_message | None).

    The daily CSVs only move once per session, so one fetch per generator-day
    is enough; on fetch failure a same-week cache is reused (with a note) so a
    transient CBOE hiccup doesn't blank the regime strip for the whole day.
    """
    cache = _load_regime_cache()
    if cache and cache.get("cache_date") == today_iso:
        return cache["regime"], None

    try:
        regime = await fetch_regime_block()
    except Exception as exc:  # noqa: BLE001 — degrade, never sink the run
        if cache and cache.get("regime"):
            logger.warning("%s VIX fetch failed (%s); reusing %s cache", _LOG_TAG, exc, cache.get("cache_date"))
            stale = dict(cache["regime"])
            stale["source"] = f"{stale.get('source', '')} [cached {cache.get('cache_date')}; refresh failed]"
            return stale, None
        return None, f"regime: VIX/VIX3M fetch failed ({exc})"

    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _REGIME_CACHE_PATH.write_text(
        json.dumps({"cache_date": today_iso, "regime": regime}, indent=2), encoding="utf-8"
    )
    return regime, None


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _atomic_write_json(path: Path, payload: dict) -> None:
    """temp file + os.replace — atomic on NTFS, so the router never reads a
    half-written snapshot."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _update_iv_history(snapshot: dict, today_iso: str) -> None:
    """One JSONL row per symbol per day, last snapshot of the day wins —
    accumulates toward an honest local ATM-IV rank (usable after ~20 sessions;
    until then the dashboard shows raw ATM IV with no rank claim)."""
    regime = snapshot.get("regime") or {}
    fresh: dict[str, dict] = {}
    for symbol, block in (snapshot.get("symbols") or {}).items():
        if not block:
            continue
        ivs = {h["label"]: h.get("atm_iv") for h in block.get("horizons", [])}
        fresh[symbol] = {
            "date": today_iso,
            "symbol": symbol,
            "atm_iv_nearest": ivs.get("nearest"),
            "atm_iv_eow": ivs.get("end_of_week"),
            "vix": regime.get("vix"),
            "vix3m": regime.get("vix3m"),
        }
    if not fresh:
        return

    rows: list[dict] = []
    if _IV_HISTORY_PATH.exists():
        for line in _IV_HISTORY_PATH.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not (row.get("date") == today_iso and row.get("symbol") in fresh):
                rows.append(row)
    rows.extend(fresh.values())
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _IV_HISTORY_PATH.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )


def _update_em_tracking(snapshot: dict, today_iso: str) -> None:
    """Accumulate expected-move-vs-realized calibration from real delayed quotes.

    One JSONL row per symbol per day (last snapshot of the day wins) recording the
    nearest-horizon straddle expected move, for horizons expiring on a LATER day
    (dte >= 1 — a 0-DTE row would measure its own overwritten spot against itself).
    Each update also resolves any earlier unresolved row whose expiry date now has
    a same-symbol row to read the closing spot from: realized = |spot(expiry) −
    spot(record)|, ratio = realized / em_abs. The expiry-day spot is the last RTH
    snapshot (~15:05 CT, after the 15:00 CT close) — close-approximate, disclosed.

    Historical baseline (dense SPY 2010-2023, Study 3a): hit rate |realized| < EM
    ≈ 70% overall, ~71% in CONTANGO vs ~55% in BACKWARDATION, median ratio 0.60.
    """
    fresh: dict[str, dict] = {}
    for symbol, block in (snapshot.get("symbols") or {}).items():
        if not block or block.get("spot") is None:
            continue
        nearest = next(
            (h for h in block.get("horizons", []) if h.get("label") == "nearest"), None
        )
        if (
            nearest is None
            or nearest.get("expected_move_abs") is None
            or nearest.get("quality") != "ok"
            or (nearest.get("dte_calendar") or 0) < 1
        ):
            continue
        fresh[symbol] = {
            "date": today_iso,
            "symbol": symbol,
            "spot": block["spot"],
            "expiry": nearest.get("expiry"),
            "dte_calendar": nearest.get("dte_calendar"),
            "em_abs": nearest["expected_move_abs"],
            "em_pct": nearest.get("expected_move_pct"),
        }

    rows: list[dict] = []
    if _EM_TRACKING_PATH.exists():
        for line in _EM_TRACKING_PATH.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not (row.get("date") == today_iso and row.get("symbol") in fresh):
                rows.append(row)
    rows.extend(fresh.values())
    if not rows:
        return

    # Resolution pass: close-approximate spot per (symbol, date) from the rows
    # themselves plus today's snapshot spots (covers expiry days that produced no
    # trackable row of their own, e.g. Fridays where the next expiry is 0 DTE).
    spot_at: dict[tuple[str, str], float] = {
        (r["symbol"], r["date"]): r["spot"] for r in rows if r.get("spot") is not None
    }
    for symbol, block in (snapshot.get("symbols") or {}).items():
        if block and block.get("spot") is not None:
            spot_at[(symbol, today_iso)] = block["spot"]
    for r in rows:
        if r.get("realized") is not None or not r.get("em_abs"):
            continue
        s_exp = spot_at.get((r["symbol"], r.get("expiry")))
        if s_exp is None:
            continue
        r["realized"] = round(abs(s_exp - r["spot"]), 4)
        r["ratio"] = round(r["realized"] / r["em_abs"], 4)
        r["resolved_on"] = today_iso

    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _EM_TRACKING_PATH.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def _run(symbols: tuple[str, ...], dry_run: bool) -> int:
    now_ct = datetime.now(_CT)
    today_iso = now_ct.date().isoformat()

    regime, regime_error = await _regime_for_today(today_iso)
    snapshot, exit_code = await build_snapshot(
        symbols, regime=regime, regime_error=regime_error, now_ct=now_ct
    )

    sym_status = " | ".join(
        f"{s} {'ok' if snapshot['symbols'].get(s) else 'FAIL'}" for s in symbols
    )
    logger.info(
        "%s %s CT | %s | regime=%s | quality=%s",
        _LOG_TAG,
        now_ct.strftime("%Y-%m-%d %H:%M"),
        sym_status,
        (regime or {}).get("regime", "none"),
        snapshot["data_quality"],
    )

    if dry_run:
        print(json.dumps(snapshot, indent=2))
        logger.info("%s dry run — nothing written", _LOG_TAG)
        return exit_code

    all_failed = all(v is None for v in snapshot["symbols"].values())
    if all_failed:
        # Preserve the previous good snapshot: its own generated_at/stale_after_s
        # make it self-expire on the dashboard, which is a more honest failure
        # surface than an empty file.
        logger.error("%s every chain failed — latest.json left untouched", _LOG_TAG)
        return 2

    _atomic_write_json(_LATEST_PATH, snapshot)
    _update_iv_history(snapshot, today_iso)
    _update_em_tracking(snapshot, today_iso)
    logger.info("%s wrote %s", _LOG_TAG, _LATEST_PATH)
    return exit_code


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="SPY/QQQ market-implied options snapshot")
    parser.add_argument(
        "--symbols",
        default=",".join(DEFAULT_SYMBOLS),
        help="comma-separated CBOE underlyings (default: %(default)s)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="fetch + compute + print JSON; write nothing"
    )
    parser.add_argument(
        "--force", action="store_true", help="run even outside weekday RTH (manual testing)"
    )
    args = parser.parse_args(argv)

    symbols = tuple(s.strip().upper() for s in args.symbols.split(",") if s.strip())
    if not symbols:
        parser.error("--symbols parsed to nothing")

    now_ct = datetime.now(_CT)
    if not args.force and not _inside_rth(now_ct):
        # Exit 0 on purpose: the scheduled trigger repeats around the clock and
        # the loop wrapper writes a GREEN heartbeat on 0, so weekend/overnight
        # fires stay quiet instead of paging.
        logger.info("%s outside weekday RTH (%s CT) — skipped", _LOG_TAG, now_ct.strftime("%a %H:%M"))
        return 0

    return asyncio.run(_run(symbols, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
