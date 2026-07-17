"""
LONG_GAP_FILL options paper-track logger for JARVIS TRADER.

Study 2 (2026-07-16) showed a BS-synthetic 0DTE call debit spread expression of
the gate-v2-PASS LONG_GAP_FILL signal has a positive sign but cannot be
validated on synthetic prices. This script gathers the REAL evidence: whenever
the live pipeline opens a LONG_GAP_FILL paper trade on MES, it records actual
15-minute-delayed CBOE SPY quotes for the corresponding call debit spread at
entry and again at the futures exit. After n >= 30 completed records the
per-trade return-on-debit series goes through the options-vrp gate for an
honest verdict.

INSTRUMENTATION ONLY: reads the paper_trades DB READ-ONLY, fetches public CBOE
delayed quotes, appends to a local JSONL. No LLM, no broker, no execution
wiring, no engine HTTP — per the June-2026 no-validated-options-edge rule
nothing trades until a real-quote gate passes AND Amo authorizes.

Trade selection: paper_trades rows with symbol=MES, side buy/long, and
strategy_params.stark_signal == "LONG_GAP_FILL" (persisted by signal_scanner
as of this change; older rows without the key are invisible by design).

Spread mapping (MES trades ~ 10x SPY):
    width_spy = max(1, round((take_profit - entry_price) / 10))   # POC target
    K_long    = SPY strike nearest spot at recording time
    K_short   = K_long + width_spy
    expiry    = nearest listed expiry (0DTE when available — the signal is
                intraday with an EOD exit)

Lifecycle per trade_id in gapfill_papertrack.jsonl:
    entry leg recorded  -> exit leg recorded when the futures trade closes
    -> return-on-debit computed at bid/ask cross AND at mid.
    A trade whose exit is seen only after its option expiry is marked
    quality="missed_exit" (kept for the record, excluded from the gate series).

Usage
-----
    python -m engine.scripts.gapfill_options_papertrack            # RTH-gated
    python -m engine.scripts.gapfill_options_papertrack --dry-run  # print, no write
    python -m engine.scripts.gapfill_options_papertrack --force    # ignore RTH gate

Exit codes: 0 = ok (or RTH-skip / nothing to do), 1 = usage error, 2 = degraded
(chain fetch failed with work pending).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("gapfill_options_papertrack")

_SCRIPTS_DIR = Path(__file__).resolve().parent
_ENGINE_DIR = _SCRIPTS_DIR.parent
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

from analysis.options_implied import (  # noqa: E402
    CBOE_CHAIN_URL,
    Contract,
    parse_chain,
)

_CT = ZoneInfo("America/Chicago")
_LOG_TAG = "[GAPFILL PAPERTRACK]"

# Env override mirrors paper-stop-sentinel's PAPER_STOP_SENTINEL_DB pattern
# (worktree checkouts have no data dir; the loop always runs on the live checkout).
import os  # noqa: E402

_DB_PATH = Path(os.environ.get(
    "GAPFILL_PAPERTRACK_DB", str(_ENGINE_DIR / "data" / "jarvis_trader.db")
))
_DATA_DIR = _ENGINE_DIR / "data" / "options_signals"
_TRACK_PATH = _DATA_DIR / "gapfill_papertrack.jsonl"

OPTION_SYMBOL = "SPY"
FUTURES_SYMBOL = "MES"
FUT_TO_OPT_SCALE = 10.0  # MES index points -> SPY dollars

# Same RTH window as the options-signals snapshot loop.
_RTH_START = (8, 30)
_RTH_END = (15, 5)


def _inside_rth(now_ct: datetime) -> bool:
    if now_ct.weekday() >= 5:
        return False
    minutes = now_ct.hour * 60 + now_ct.minute
    return _RTH_START[0] * 60 + _RTH_START[1] <= minutes <= _RTH_END[0] * 60 + _RTH_END[1]


# ---------------------------------------------------------------------------
# DB (read-only)
# ---------------------------------------------------------------------------


def fetch_gapfill_trades(db_path: Path = _DB_PATH) -> list[dict]:
    """LONG_GAP_FILL MES paper trades, open or closed, read-only."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            """
            SELECT trade_id, symbol, side, entry_price, exit_price, entry_time,
                   exit_time, status, stop_loss, take_profit, strategy_params
            FROM paper_trades
            WHERE symbol = ?
              AND json_extract(strategy_params, '$.stark_signal') = 'LONG_GAP_FILL'
              AND lower(side) IN ('buy', 'long')
            ORDER BY entry_time
            """,
            (FUTURES_SYMBOL,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Spread selection / quoting
# ---------------------------------------------------------------------------


def _leg_quote(contracts: list[Contract], expiry: date, strike: float) -> Optional[dict]:
    for c in contracts:
        if c.right == "C" and c.expiry == expiry and c.strike == strike:
            return {
                "strike": strike,
                "bid": c.bid,
                "ask": c.ask,
                "mid": c.mid,
                "iv": c.iv,
                "delta": c.delta,
            }
    return None


def select_spread(
    contracts: list[Contract], spot: float, trade: dict, today_ct: date
) -> Optional[dict]:
    """Pick expiry + strikes for the entry->target call debit spread."""
    expiries = sorted({c.expiry for c in contracts if c.expiry >= today_ct})
    if not expiries:
        return None
    expiry = expiries[0]
    strikes = sorted(
        {c.strike for c in contracts if c.right == "C" and c.expiry == expiry}
    )
    if not strikes:
        return None
    k_long = min(strikes, key=lambda k: abs(k - spot))
    target, entry = trade.get("take_profit"), trade.get("entry_price")
    if target and entry and target > entry:
        width = max(1.0, round((float(target) - float(entry)) / FUT_TO_OPT_SCALE))
    else:
        width = max(1.0, round(spot * 0.005))  # fallback: ~0.5% of spot
    shorts = [k for k in strikes if k >= k_long + width]
    if not shorts:
        return None
    k_short = shorts[0]
    long_q = _leg_quote(contracts, expiry, k_long)
    short_q = _leg_quote(contracts, expiry, k_short)
    if long_q is None or short_q is None:
        return None
    return {"expiry": expiry.isoformat(), "k_long": k_long, "k_short": k_short,
            "long": long_q, "short": short_q}


def leg_snapshot(spread: dict, spot: float, quote_ts: Optional[int], when: str) -> dict:
    long_q, short_q = spread["long"], spread["short"]
    snap = {
        "recorded_at": when,
        "spot": spot,
        "quote_ts": quote_ts,
        "long": long_q,
        "short": short_q,
    }
    # cross = worst-case fill; mid = frictionless bracket
    if all(v is not None for v in (long_q["ask"], short_q["bid"])):
        snap["debit_cross"] = round(long_q["ask"] - short_q["bid"], 4)
    if all(v is not None for v in (long_q["bid"], short_q["ask"])):
        snap["credit_cross"] = round(long_q["bid"] - short_q["ask"], 4)
    if all(v is not None for v in (long_q["mid"], short_q["mid"])):
        snap["value_mid"] = round(long_q["mid"] - short_q["mid"], 4)
    return snap


# ---------------------------------------------------------------------------
# JSONL state
# ---------------------------------------------------------------------------


def load_records(path: Path = _TRACK_PATH) -> dict[str, dict]:
    records: dict[str, dict] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("trade_id"):
                records[row["trade_id"]] = row
    return records


def save_records(records: dict[str, dict], path: Path = _TRACK_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r) for r in records.values()) + "\n", encoding="utf-8"
    )


def _finalize(rec: dict) -> None:
    """Compute return-on-debit brackets once entry + exit legs both exist."""
    entry, exit_ = rec.get("entry_leg") or {}, rec.get("exit_leg") or {}
    debit_cross, credit_cross = entry.get("debit_cross"), exit_.get("credit_cross")
    if debit_cross and debit_cross > 0 and credit_cross is not None:
        rec["ret_cross"] = round((credit_cross - debit_cross) / debit_cross, 4)
    d_mid, v_mid = entry.get("value_mid"), exit_.get("value_mid")
    if d_mid and d_mid > 0 and v_mid is not None:
        rec["ret_mid"] = round((v_mid - d_mid) / d_mid, 4)


# ---------------------------------------------------------------------------
# Main pass
# ---------------------------------------------------------------------------


def process(
    trades: list[dict],
    records: dict[str, dict],
    chain: Optional[tuple[float, Optional[int], list[Contract]]],
    now_ct: datetime,
) -> tuple[int, int, bool]:
    """Reconcile trades vs records. Returns (n_entries, n_exits, changed)."""
    today_ct = now_ct.date()
    now_iso = now_ct.isoformat(timespec="seconds")
    n_entry = n_exit = 0
    changed = False

    for trade in trades:
        tid = trade["trade_id"]
        rec = records.get(tid)

        if rec is None:
            if chain is None:
                continue  # degraded fetch — pick the trade up next run
            spot, quote_ts, contracts = chain
            spread = select_spread(contracts, spot, trade, today_ct)
            if spread is None:
                logger.warning("%s no quotable spread for trade %s", _LOG_TAG, tid[:8])
                continue
            rec = {
                "trade_id": tid,
                "signal": "LONG_GAP_FILL",
                "futures_symbol": trade["symbol"],
                "option_symbol": OPTION_SYMBOL,
                "futures_entry_price": trade["entry_price"],
                "futures_entry_time": trade["entry_time"],
                "futures_take_profit": trade["take_profit"],
                "expiry": spread["expiry"],
                "k_long": spread["k_long"],
                "k_short": spread["k_short"],
                "entry_leg": leg_snapshot(spread, spot, quote_ts, now_iso),
                "quality": "open",
            }
            records[tid] = rec
            n_entry += 1
            changed = True

        if rec.get("exit_leg") is None and trade.get("exit_time"):
            rec["futures_exit_price"] = trade.get("exit_price")
            rec["futures_exit_time"] = trade.get("exit_time")
            rec["futures_pnl"] = trade.get("pnl")
            expired = date.fromisoformat(rec["expiry"]) < today_ct
            if expired:
                # The spread expired before we saw the exit — quotes no longer
                # exist. Keep the record, exclude it from the gate series.
                rec["quality"] = "missed_exit"
                changed = True
                continue
            if chain is None:
                continue
            spot, quote_ts, contracts = chain
            expiry_d = date.fromisoformat(rec["expiry"])
            spread = {
                "long": _leg_quote(contracts, expiry_d, rec["k_long"]),
                "short": _leg_quote(contracts, expiry_d, rec["k_short"]),
            }
            if spread["long"] is None or spread["short"] is None:
                logger.warning("%s exit legs unquotable for %s", _LOG_TAG, tid[:8])
                continue
            rec["exit_leg"] = leg_snapshot(spread, spot, quote_ts, now_iso)
            rec["quality"] = "complete"
            _finalize(rec)
            n_exit += 1
            changed = True

    return n_entry, n_exit, changed


async def _run(dry_run: bool) -> int:
    now_ct = datetime.now(_CT)
    trades = fetch_gapfill_trades()
    records = load_records()

    pending = [
        t for t in trades
        if t["trade_id"] not in records
        or (records[t["trade_id"]].get("exit_leg") is None
            and records[t["trade_id"]].get("quality") != "missed_exit"
            and t.get("exit_time"))
    ]
    open_unexited = [
        t for t in trades
        if t["trade_id"] in records and not t.get("exit_time")
    ]
    if not pending and not open_unexited:
        logger.info("%s nothing to do (%d trades, %d records)",
                    _LOG_TAG, len(trades), len(records))
        return 0

    chain = None
    if pending:
        try:
            from analysis.options_implied import _default_fetch_json

            raw = await _default_fetch_json(CBOE_CHAIN_URL.format(symbol=OPTION_SYMBOL))
            chain = parse_chain(raw, OPTION_SYMBOL)
        except Exception as exc:
            logger.error("%s %s chain fetch failed: %s", _LOG_TAG, OPTION_SYMBOL, exc)

    n_entry, n_exit, changed = process(trades, records, chain, now_ct)
    complete = sum(1 for r in records.values() if r.get("quality") == "complete")
    logger.info(
        "%s %s CT | trades=%d entries+%d exits+%d | complete=%d (gate at n>=30)",
        _LOG_TAG, now_ct.strftime("%Y-%m-%d %H:%M"), len(trades), n_entry, n_exit,
        complete,
    )

    if dry_run:
        print(json.dumps(list(records.values()), indent=2))
        logger.info("%s dry run — nothing written", _LOG_TAG)
    elif changed:
        save_records(records)
        logger.info("%s wrote %s", _LOG_TAG, _TRACK_PATH)

    return 2 if (pending and chain is None) else 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="LONG_GAP_FILL options paper-track logger (instrumentation only)"
    )
    parser.add_argument("--dry-run", action="store_true", help="print, write nothing")
    parser.add_argument("--force", action="store_true", help="ignore the RTH gate")
    args = parser.parse_args(argv)

    now_ct = datetime.now(_CT)
    if not args.force and not _inside_rth(now_ct):
        logger.info("%s outside RTH (%s CT) — skipping", _LOG_TAG,
                    now_ct.strftime("%a %H:%M"))
        return 0

    if not _DB_PATH.exists():
        logger.error("%s paper trades DB missing: %s", _LOG_TAG, _DB_PATH)
        return 1

    return asyncio.run(_run(args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
