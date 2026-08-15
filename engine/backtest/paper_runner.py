"""
JARVIS TRADER — Paper Trading Runner
=====================================
Consolidation note (US-1407): Unified state — SQLite only.
This module delegates ALL state writes to PaperTradeTracker (engine/backtest/paper_tracker.py).
No JSONL files are created or written. All state is in SQLite (paper_trades table).

Standalone hourly loop for MCL and MNQ paper trading.

Runs signal generation, open-position management, and trade logging
without requiring the full FastAPI server or Anthropic API key.

Flow per cycle (every hour at :05 past the bar close):
  1. Load open positions from SQLite
  2. Fetch last 150 1h bars via Polygon.io (MCL for MCL, MNQ for MNQ)
  3. Run generate_signals() with paper_config validated parameters
  4. Manage open positions: check stop/target hits on current bar
  5. Check for new ENTRY_NOW signal (only if no open position)
  6. Save updated positions to SQLite
  7. Log all activity + WhatsApp notification on entry/exit

Kill conditions (via PaperTradeTracker):
  - 3 consecutive losses  → halt instrument
  - WFE < minimum threshold → halt instrument
  - -3% monthly loss      → halt instrument

Usage:
  python -m backtest.paper_runner          # single run
  python -m backtest.paper_runner --watch  # continuous (runs every hour)
  python -m backtest.paper_runner --status # print open positions and metrics

Optional engine sync (POST /portfolio/paper/trade) so the FastAPI tracker matches the runner:
  JARVIS_ENGINE_URL=http://127.0.0.1:8010
  JARVIS_API_KEY=<same as engine API_KEY>
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

# ── Paths ────────────────────────────────────────────────────────────────────
_RESULTS_DIR = Path(__file__).parent / "results"
_RESULTS_DIR.mkdir(exist_ok=True)

RUNNER_LOG_FILE = _RESULTS_DIR / "paper_runner.log"

# ── Logging setup ─────────────────────────────────────────────────────────────
_logger_configured = False


def _setup_logging() -> None:
    global _logger_configured
    if _logger_configured:
        return
    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
        logging.handlers.RotatingFileHandler(
            str(RUNNER_LOG_FILE), maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        ),
    ]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )
    _logger_configured = True


# ── Deferred imports (avoid circular deps and heavy startup cost) ─────────────
def _import_signal_deps():
    from backtest.data_loader import FUTURES_MAP
    from backtest.paper_config import ACTIVE_INSTRUMENTS, PAPER_CONFIGS, resolve_underlying
    from backtest.paper_tracker import PaperTradeTracker
    from backtest.signals import generate_instrument_signals, generate_signals

    return (
        FUTURES_MAP,
        ACTIVE_INSTRUMENTS,
        PAPER_CONFIGS,
        PaperTradeTracker,
        generate_signals,
        generate_instrument_signals,
        resolve_underlying,
    )


# ── Position State I/O ────────────────────────────────────────────────────────


def _adapt_trade_row_to_position(trade: Dict[str, Any]) -> Dict[str, Any]:
    """
    Translate a SQLite paper_trades row into the dict shape that
    manage_open_position() / _print_summary() / _cmd_status() expect.

    The DB schema uses column names (stop_loss, entry_time, quantity), while
    the runner's legacy in-memory shape uses (stop, entry_date, contracts,
    targets, contracts_remaining, t{1,2,3}_hit). Targets and per-target hit
    flags live inside the JSON-serialised strategy_params column.

    This adapter is what Stage 5 (2026-04-10) added to fix a hourly
    KeyError: 'stop' crash in the paper runner when the DB-sourced trade
    dict did not match the legacy key names.
    """
    pos: Dict[str, Any] = dict(trade)

    # Field-name translation (copy, don't mutate original column values)
    pos["stop"] = trade.get("stop_loss")
    pos["entry_date"] = trade.get("entry_time")

    quantity = int(float(trade.get("quantity") or 1))
    pos["contracts"] = quantity

    # Parse strategy_params for per-target hit state + target list + dynamic state
    raw_params = trade.get("strategy_params") or "{}"
    try:
        params = json.loads(raw_params) if isinstance(raw_params, str) else (raw_params or {})
    except (json.JSONDecodeError, TypeError):
        params = {}

    raw_targets = params.get("targets") or []
    pos["targets"] = list(raw_targets) if isinstance(raw_targets, (list, tuple)) else []
    pos["contracts_remaining"] = int(params.get("contracts_remaining", quantity))
    pos["t1_hit"] = bool(params.get("t1_hit", False))
    pos["t2_hit"] = bool(params.get("t2_hit", False))
    pos["t3_hit"] = bool(params.get("t3_hit", False))
    pos["risk_pct_used"] = params.get("risk_pct_used", trade.get("risk_pct_used"))

    return pos


def load_positions() -> Dict[str, Any]:
    """
    Load open paper positions from SQLite via database manager.

    Returns dict mapping symbol -> position record, adapted to the
    legacy in-memory shape expected by manage_open_position().
    """
    try:
        from database.manager import get_db

        db = get_db()
        open_trades = db.get_open_trades()
        positions: Dict[str, Any] = {}
        for trade in open_trades:
            symbol = trade.get("symbol", "")
            if not symbol:
                continue
            positions[symbol] = _adapt_trade_row_to_position(trade)
        return positions
    except Exception as exc:
        logging.getLogger("paper_runner").warning(
            "Failed to load positions from SQLite: %s — starting with empty state", exc
        )
        return {}


def save_positions(positions: Dict[str, Any]) -> None:
    """
    Persist open positions to SQLite (via open trade records).

    This is a no-op since positions are already in SQLite
    as open paper_trades records. Called for compatibility.
    """
    # All updates happen via tracker.add_trade() and manage_open_position(),
    # which write directly to SQLite. This function is retained for API compatibility.
    pass


# ── Trade Persistence (SQLite via PaperTradeTracker) ──────────────────────────
# Note: All trade records are now persisted via PaperTradeTracker.add_trade(),
# which writes to SQLite. No JSONL file is maintained.


# ── Optional sync to engine PortfolioTracker (POST /portfolio/paper/trade) ───


def _engine_sync_url() -> Optional[str]:
    base = os.environ.get("JARVIS_ENGINE_URL", "").strip().rstrip("/")
    return base or None


def _engine_api_key() -> Optional[str]:
    k = (
        os.environ.get("JARVIS_API_KEY")
        or os.environ.get("X_API_KEY")
        or os.environ.get("API_KEY")
        or ""
    ).strip()
    return k or None


def _engine_base_url() -> str:
    """Engine base URL for the data feed. Defaults to the local engine so the
    standalone Jarvis-PaperCollect task works without any env wiring."""
    base = os.environ.get("JARVIS_ENGINE_URL", "").strip().rstrip("/")
    return base or "http://127.0.0.1:8010"


def _resolve_api_key() -> Optional[str]:
    """API key for engine calls. Prefer env vars; fall back to engine/.env (the
    canonical local secret store) so the scheduled task — which runs with a bare
    environment — can still authenticate to the bars endpoint."""
    k = _engine_api_key()
    if k:
        return k
    env_path = Path(__file__).resolve().parent.parent / ".env"
    try:
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"\s*(API_KEY|JARVIS_API_KEY|X_API_KEY)\s*=\s*(.+)", line)
            if m:
                return m.group(2).strip().strip('"').strip("'")
    except Exception:  # noqa: BLE001
        return None
    return None


def _post_engine_json(path: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """POST JSON to engine. Returns parsed body or None on failure."""
    base = _engine_sync_url()
    key = _engine_api_key()
    if not base or not key:
        return None
    url = f"{base}{path}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-API-Key": key,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        json.JSONDecodeError,
    ) as exc:
        logging.getLogger("paper_runner.engine_sync").warning("Engine sync failed: %s", exc)
        return None


def _try_sync_engine_open(position: Dict[str, Any]) -> None:
    """After local entry, register open trade with engine; sets engine_trade_id on success."""
    side = str(position.get("side", "long")).lower()
    body = {
        "action": "open",
        "symbol": position.get("symbol", ""),
        "side": side,
        "quantity": float(position.get("contracts", position.get("contracts_remaining", 1))),
        "entry_price": float(position.get("entry_price", 0)),
        "notes": "paper_runner",
    }
    res = _post_engine_json("/portfolio/paper/trade", body)
    if res and res.get("trade_id"):
        position["engine_trade_id"] = res["trade_id"]


def _try_sync_engine_close(position: Dict[str, Any], record: Dict[str, Any]) -> None:
    """On exit, close the linked engine paper trade."""
    tid = position.get("engine_trade_id")
    if not tid:
        return
    exit_px = float(record.get("exit_price", 0))
    body = {
        "action": "close",
        "symbol": record.get("symbol", position.get("symbol", "")),
        "trade_id": tid,
        "exit_price": exit_px,
        "pnl": record.get("pnl"),
    }
    _post_engine_json("/portfolio/paper/trade", body)


# ── WhatsApp Notification (optional, graceful failure) ───────────────────────


def _notify(message: str) -> None:
    """Send WhatsApp notification if Twilio env vars are configured."""
    try:
        account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
        auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
        from_num = os.environ.get("TWILIO_WHATSAPP_FROM", "")
        to_num = os.environ.get("WHATSAPP_TO", "")

        if not all([account_sid, auth_token, from_num, to_num]):
            return  # Silently skip if not configured

        import httpx

        url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
        httpx.post(
            url,
            data={"From": from_num, "To": to_num, "Body": message},
            auth=(account_sid, auth_token),
            timeout=10.0,
        )
    except Exception:
        pass  # Never let notification failure crash the runner


# ── Bar Fetching ──────────────────────────────────────────────────────────────


def fetch_bars(
    symbol: str,
    futures_map: Dict[str, str],
    bars: int = 150,
    timeframe: str = "1h",
) -> Optional[pd.DataFrame]:
    """
    Fetch recent OHLCV bars for a futures symbol from the running engine's
    /analyze/bars endpoint (IBKR Tier-1 / TradingView Tier-0 live feed).

    Replaces the old Polygon-only path: Polygon's free plan is futures-blocklisted
    (returns the wrong asset, e.g. CL=Colgate-Palmolive), so the standalone runner
    had no working data source and every cycle no-opped on `data_error`. The engine
    already maintains the live IBKR/TV feed, so the runner asks it directly — one
    source of truth shared with the dashboard and pipeline.

    `limit` is sized to clear the slowest SMA warmup (MES SMA-200 crossover needs
    >200 1h bars); the endpoint clamps to its own ceiling. Returns None on any
    failure so the cycle fails-soft (degrades to `data_error`, never crashes).
    """
    log = logging.getLogger(f"paper_runner.{symbol}")

    # Lookback window sized to guarantee enough completed bars for SMA warmup.
    days_map = {"5m": 7, "15m": 21, "1h": 60, "4h": 180, "1d": 500}
    days = days_map.get(timeframe, 60)
    # Request well above the SMA-200 floor; the endpoint clamps to its own cap.
    limit = max(bars, 400)

    base = _engine_base_url()
    key = _resolve_api_key()
    url = (
        f"{base}/analyze/bars/{symbol}"
        f"?interval={timeframe}&futures=true&days={days}&limit={limit}"
    )
    req = urllib.request.Request(url, headers={"X-API-Key": key or ""})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.load(resp)
    except Exception as exc:  # noqa: BLE001
        log.error(f"Engine bar fetch failed for {symbol} {timeframe}: {exc}")
        return None

    records = payload.get("bars") or []
    if not records:
        log.error(f"Engine returned no {timeframe} bars for {symbol}")
        return None

    df = pd.DataFrame(records)
    if "timestamp" not in df.columns:
        log.error(f"{symbol}: engine bars missing 'timestamp' column")
        return None

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.set_index("timestamp").sort_index()
    df.columns = [c.lower() for c in df.columns]
    cols = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[cols].dropna(subset=["open", "high", "low", "close"])

    if len(df) < 60:
        log.warning(
            f"Only {len(df)} {timeframe} bars for {symbol} — need >=60 for indicator warmup"
        )
        return None

    log.debug(f"Fetched {len(df)} {timeframe} bars for {symbol} from engine")
    return df


# ── Entry-evaluation dedup state (one entry decision per closed 1h bar) ────────


def _entry_eval_path() -> Path:
    return _RESULTS_DIR / "last_entry_eval.json"


def _load_entry_eval() -> Dict[str, str]:
    """Map of symbol -> last completed 1h bar timestamp already evaluated for entry.

    Persisted across the 5-minute task invocations so a crossover bar is acted on
    exactly once — without this, a position stopped out mid-hour would re-enter the
    same crossover bar on the next 5-minute poll.
    """
    try:
        return json.loads(_entry_eval_path().read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _atomic_write_json(path: Path, obj: Any) -> None:
    """Write JSON atomically (temp file + os.replace) so a torn write can never
    leave a half-written file. A corrupt state file is silently read back as {}
    by the loaders below — for entry_eval that wipes the crossover-bar dedup and
    re-enables a double entry. The standalone Jarvis-PaperCollect task and the
    in-process engine can both write these files, so torn writes are reachable.
    os.replace is atomic on the same filesystem (incl. Windows NTFS).
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj), encoding="utf-8")
    os.replace(tmp, path)


def _save_entry_eval(state: Dict[str, str]) -> None:
    try:
        _atomic_write_json(_entry_eval_path(), state)
    except Exception:  # noqa: BLE001
        pass


# ── Data-starvation guard (Initiative 1, Track A1) ─────────────────────────────
# A paper stop can only be enforced when bars are flowing. When fetch_bars()
# returns None the cycle silently skips management — so an open position is left
# UNPROTECTED with no signal to the operator. That silent no-op is exactly what
# turned trade #178's −$64 planned risk into a −$1,284 realized loss during the
# 2026-06-01 IB-Gateway outage. We persist a per-symbol consecutive-error counter
# and make the blindness LOUD once a starved symbol is also holding a position.
DATA_ERROR_ALERT_THRESHOLD = 3  # ~15 min at the 5-minute poll cadence
DATA_ERROR_REANNOUNCE_EVERY = 12  # re-alert hourly while the feed stays dark


def _data_error_path() -> Path:
    return _RESULTS_DIR / "data_error_state.json"


def _load_data_error_state() -> Dict[str, int]:
    """Map of symbol -> consecutive data_error count, persisted across cycles."""
    try:
        raw = json.loads(_data_error_path().read_text(encoding="utf-8"))
        return {str(k): int(v) for k, v in raw.items()}
    except Exception:  # noqa: BLE001
        return {}


def _save_data_error_state(state: Dict[str, int]) -> None:
    try:
        _atomic_write_json(_data_error_path(), state)
    except Exception:  # noqa: BLE001
        pass


def should_alert_data_error(
    count: int,
    threshold: int = DATA_ERROR_ALERT_THRESHOLD,
    reannounce_every: int = DATA_ERROR_REANNOUNCE_EVERY,
) -> bool:
    """Alert on the first cross of the threshold, then periodically while dark.

    Fires at exactly ``count == threshold`` (first time blindness is confirmed),
    then again every ``reannounce_every`` cycles after that — loud enough to be
    noticed, quiet enough not to spam every poll for hours.
    """
    if count < threshold:
        return False
    if count == threshold:
        return True
    return reannounce_every > 0 and (count - threshold) % reannounce_every == 0


def _latest_mgmt_bar(
    symbol: str,
    futures_map: Dict[str, str],
    df_1h_signals: pd.DataFrame,
) -> Tuple[pd.Series, str]:
    """Return the freshest bar to manage an open position against.

    Prefers the latest 5-minute bar (intrabar stop/target accuracy — the validated
    edge entered on 1h closes, but checking exits only hourly misses intrabar fills).
    Falls back to the latest 1h bar if the 5m feed is unavailable, so management never
    silently stops working.
    """
    df_5m = fetch_bars(symbol, futures_map, timeframe="5m")
    if df_5m is not None and not df_5m.empty:
        return df_5m.iloc[-1], str(df_5m.index[-1])
    if df_1h_signals is None or df_1h_signals.empty:
        # Both feeds dry: raise a clear error instead of letting an empty-frame
        # .iloc[-1] surface as a bare IndexError far from the cause. The caller
        # guards the per-symbol cycle, so this skips management for this poll.
        raise ValueError(
            f"_latest_mgmt_bar({symbol}): no 5m feed and empty 1h frame — cannot manage position"
        )
    return df_1h_signals.iloc[-1], str(df_1h_signals.index[-1])


# ── Position Management ───────────────────────────────────────────────────────


def _compute_pnl(
    entry_price: float,
    exit_price: float,
    side: str,
    contracts: int,
    multiplier: float,
    commission: float,
) -> float:
    """Compute realized P&L including round-trip commission."""
    raw = (exit_price - entry_price) * multiplier * contracts
    if side == "short":
        raw = -raw
    # Slippage is already baked into entry/exit price estimates
    return raw - (commission * contracts * 2)  # entry + exit legs


_RTH_CLOSE_HOUR_ET = 16  # 16:00 America/New_York, matches run_value_area_reentry_sd116.py


def _is_at_or_after_rth_close(current_time: str) -> bool:
    """True once the bar timestamp reaches 16:00 America/New_York (RTH close).

    Used only by configs that opt into ``session_close`` (sd-116/MES_VA30) --
    strategies validated to hold overnight are unaffected since they never
    set that flag.
    """
    ts = pd.Timestamp(current_time)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    ts_et = ts.tz_convert("America/New_York")
    return ts_et.hour >= _RTH_CLOSE_HOUR_ET


def manage_open_position(
    symbol: str,
    pos: Dict[str, Any],
    last_bar: pd.Series,
    current_time: str,
    cfg: Dict[str, Any],
    tracker: Any,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Check whether an open position's stop or targets were hit on the current bar.

    Returns (updated_position, closed_trade_record).
    - updated_position is None if the position was fully closed.
    - closed_trade_record is None if the position is still open.
    """
    log = logging.getLogger(f"paper_runner.{symbol}")

    entry_price = float(pos["entry_price"])
    side = pos["side"]
    stop = float(pos["stop"])
    targets: List[float] = [float(t) for t in pos["targets"]]
    contracts_remaining = int(pos.get("contracts_remaining", pos.get("contracts", 1)))
    multiplier = float(cfg["multiplier"])
    commission = float(cfg["commission_per_contract"])
    tick_size = float(cfg["tick_size"])
    slippage_ticks = int(cfg.get("slippage_ticks", 1))

    bar_high = float(last_bar["high"])
    bar_low = float(last_bar["low"])

    # ── Check stop first (highest priority) ──────────────────────────────────
    stop_hit = (side == "long" and bar_low <= stop) or (side == "short" and bar_high >= stop)

    if stop_hit:
        # Slippage against us on stop
        slip = slippage_ticks * tick_size
        exit_price = stop - slip if side == "long" else stop + slip
        pnl = _compute_pnl(
            entry_price, exit_price, side, contracts_remaining, multiplier, commission
        )

        record = {
            "symbol": symbol,
            "entry_date": pos["entry_date"],
            "exit_date": current_time,
            "entry_price": entry_price,
            "exit_price": round(exit_price, 4),
            "side": side,
            "contracts": contracts_remaining,
            "exit_reason": "stop",
            "regime_type": pos.get("regime", "unknown"),
            "pnl": round(pnl, 2),
            "risk_pct_used": pos.get("risk_pct_used"),
        }

        tracker.add_trade(record)
        _try_sync_engine_close(pos, record)

        log.info(
            f"STOP HIT {symbol} {side.upper()} | entry={entry_price:.2f} "
            f"exit={exit_price:.2f} PnL=${pnl:+.2f}"
        )
        _notify(
            f"📉 JARVIS PAPER | {symbol} STOP HIT\n"
            f"{side.upper()} {entry_price:.2f} → {exit_price:.2f}\n"
            f"PnL: ${pnl:+.2f}"
        )
        return None, record

    # ── Check targets (T1 → T2 → T3) ─────────────────────────────────────────
    for i, target_price in enumerate(targets, 1):
        target_key = f"t{i}_hit"
        if pos.get(target_key):
            continue  # Already booked this target

        target_hit = (side == "long" and bar_high >= target_price) or (
            side == "short" and bar_low <= target_price
        )

        if target_hit:
            # Partial exit: scale out 1/3 at T1, 1/3 at T2, remainder at T3
            if i == 1:
                exit_contracts = max(1, contracts_remaining // 3)
            elif i == 2:
                exit_contracts = max(1, contracts_remaining // 2)
            else:
                exit_contracts = contracts_remaining

            # Minor favorable slippage on target fills (2× tighter)
            slip = (slippage_ticks // 2) * tick_size
            exit_price = target_price - slip if side == "long" else target_price + slip
            pnl = _compute_pnl(
                entry_price, exit_price, side, exit_contracts, multiplier, commission
            )

            record = {
                "symbol": symbol,
                "entry_date": pos["entry_date"],
                "exit_date": current_time,
                "entry_price": entry_price,
                "exit_price": round(exit_price, 4),
                "side": side,
                "contracts": exit_contracts,
                "exit_reason": f"target_{i}",
                "regime_type": pos.get("regime", "unknown"),
                "pnl": round(pnl, 2),
                "risk_pct_used": pos.get("risk_pct_used"),
            }

            tracker.add_trade(record)

            log.info(
                f"T{i} HIT {symbol} {side.upper()} | target={target_price:.2f} "
                f"({exit_contracts}c) PnL=${pnl:+.2f}"
            )
            _notify(
                f"🎯 JARVIS PAPER | {symbol} T{i} HIT\n"
                f"{side.upper()} {entry_price:.2f} → {exit_price:.2f}\n"
                f"PnL: ${pnl:+.2f} ({exit_contracts} contracts)"
            )

            # Update position state
            pos[target_key] = True
            pos["contracts_remaining"] = contracts_remaining - exit_contracts

            if i == 1:
                # Move stop to breakeven after T1 hit (protect the trade)
                pos["stop"] = entry_price
                log.info(f"{symbol}: Stop moved to breakeven @ {entry_price:.2f}")

            # If all contracts exited, close position
            if pos["contracts_remaining"] <= 0 or i == len(targets):
                _try_sync_engine_close(pos, record)
                return None, record

            return pos, record

    # ── Session close (only for configs that opt in, e.g. sd-116/MES_VA30) ───
    if cfg.get("session_close") and _is_at_or_after_rth_close(current_time):
        bar_close = float(last_bar["close"])
        slip = slippage_ticks * tick_size
        exit_price = bar_close - slip if side == "long" else bar_close + slip
        pnl = _compute_pnl(
            entry_price, exit_price, side, contracts_remaining, multiplier, commission
        )

        record = {
            "symbol": symbol,
            "entry_date": pos["entry_date"],
            "exit_date": current_time,
            "entry_price": entry_price,
            "exit_price": round(exit_price, 4),
            "side": side,
            "contracts": contracts_remaining,
            "exit_reason": "session_close",
            "regime_type": pos.get("regime", "unknown"),
            "pnl": round(pnl, 2),
            "risk_pct_used": pos.get("risk_pct_used"),
        }

        tracker.add_trade(record)
        _try_sync_engine_close(pos, record)

        log.info(
            f"SESSION CLOSE {symbol} {side.upper()} | entry={entry_price:.2f} "
            f"exit={exit_price:.2f} PnL=${pnl:+.2f}"
        )
        _notify(
            f"🕓 JARVIS PAPER | {symbol} SESSION CLOSE\n"
            f"{side.upper()} {entry_price:.2f} → {exit_price:.2f}\n"
            f"PnL: ${pnl:+.2f}"
        )
        return None, record

    # No hit — position still active
    return pos, None


# ── Entry Signal Detection ────────────────────────────────────────────────────


def check_for_entry(
    symbol: str,
    df_signals: pd.DataFrame,
    cfg: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Look at the most recent N completed bars for an ENTRY_NOW signal.

    N is cfg["signal_lookback_bars"] (default 1).  When a signal is found in a
    lookback bar (not the most recent), we enter at the most-recent bar's close
    price (not the signal bar's stale close) but retain the signal bar's stop
    and target levels (calibrated to that bar's ATR).  This catches crossovers
    that occurred while the runner polled between 1h bar closes.

    Returns a new position dict or None.
    """
    log = logging.getLogger(f"paper_runner.{symbol}")

    lookback = max(1, int(cfg.get("signal_lookback_bars", 1)))
    n = len(df_signals)

    signal_bar = None
    for offset in range(1, lookback + 1):
        if n < offset:
            break
        bar = df_signals.iloc[-offset]
        if str(bar.get("entry_signal", "")) == "ENTRY_NOW":
            signal_bar = bar
            if offset > 1:
                log.info(f"{symbol}: ENTRY_NOW found in lookback bar -{offset}")
            break

    if signal_bar is None:
        log.debug(f"{symbol}: No entry signal in last {lookback} bars")
        return None

    last_bar = df_signals.iloc[-1]  # use current price for entry, signal-bar levels for stops
    bias = str(signal_bar.get("bias", ""))
    side = "long" if bias in ("STRONG_BULL", "LEAN_BULL") else "short"

    # Enter at most-recent bar's close; use signal bar's levels (ATR-calibrated to crossover bar)
    entry_price = float(last_bar["close"])
    stop_level = float(signal_bar.get("stop_level", 0))
    target_1 = float(signal_bar.get("target_1", 0))
    target_2 = float(signal_bar.get("target_2", 0))
    target_3 = float(signal_bar.get("target_3", 0))

    # Sanity check: stop and targets must be non-zero and directionally correct
    if side == "long":
        if not (stop_level < entry_price < target_1 < target_2 < target_3):
            log.warning(f"{symbol}: Signal levels invalid for long — skipping")
            return None
    else:
        if not (target_3 < target_2 < target_1 < entry_price < stop_level):
            log.warning(f"{symbol}: Signal levels invalid for short — skipping")
            return None

    current_time = str(df_signals.index[-1])
    regime = str(last_bar.get("regime", "unknown"))
    structure_position = str(last_bar.get("structure_position", "NEUTRAL"))
    stc_val = float(last_bar.get("stc_val", 0))

    # Compute risk-scaled position size using Layer 5 conviction logic
    from backtest.signals import compute_position_size

    base_risk_pct = float(cfg.get("risk_per_trade", 0.0025))
    risk_pct_used = compute_position_size(bias, regime, structure_position, base_risk_pct)

    position = {
        "symbol": symbol,
        "side": side,
        "entry_price": round(entry_price, 4),
        "entry_date": current_time,
        "stop": round(stop_level, 4),
        "targets": [round(target_1, 4), round(target_2, 4), round(target_3, 4)],
        "contracts": 1,
        "contracts_remaining": 1,
        "regime": regime,
        "structure_position": structure_position,
        "stc_at_entry": round(stc_val, 2),
        "bias": bias,
        "risk_pct_used": round(risk_pct_used, 6),
        "t1_hit": False,
        "t2_hit": False,
        "t3_hit": False,
    }

    log.info(
        f"ENTRY {symbol} {side.upper()} @ {entry_price:.2f} | "
        f"Stop: {stop_level:.2f} | T1: {target_1:.2f} | "
        f"T2: {target_2:.2f} | Regime: {regime} | STC: {stc_val:.1f}"
    )
    _notify(
        f"📊 JARVIS PAPER | {symbol} ENTRY {side.upper()}\n"
        f"Price: {entry_price:.2f}\n"
        f"Stop: {stop_level:.2f} | T1: {target_1:.2f}\n"
        f"Regime: {regime}"
    )
    return position


# ── Main Cycle ───────────────────────────────────────────────────────────────


def run_one_cycle(quiet: bool = False) -> Dict[str, Any]:
    """
    Execute one full paper trading cycle across all active instruments.

    Returns summary dict: {symbol: {"action": str, "position": dict|None, ...}}
    """
    _setup_logging()
    log = logging.getLogger("paper_runner")

    # The runner is invoked standalone (the hourly Jarvis-PaperCollect task) in a
    # separate process from the engine, so the SQLite singleton must be created
    # HERE or load_positions + every tracker write silently degrade to empty
    # state and no trades persist. init_db() is an idempotent locked singleton —
    # a no-op when the engine already initialised it in-process.
    try:
        from database.manager import init_db

        init_db()
    except Exception as exc:  # noqa: BLE001
        log.warning("init_db() failed (%s) — continuing with degraded persistence", exc)

    (
        FUTURES_MAP,
        ACTIVE_INSTRUMENTS,
        PAPER_CONFIGS,
        PaperTradeTracker,
        generate_signals,
        generate_instrument_signals,
        resolve_underlying,
    ) = _import_signal_deps()

    if not quiet:
        log.info("═" * 64)
        log.info(f"JARVIS Paper Runner — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        log.info(f"Active instruments: {ACTIVE_INSTRUMENTS}")

    positions = load_positions()
    last_entry_eval = _load_entry_eval()
    data_err_state = _load_data_error_state()
    summary: Dict[str, Any] = {}

    for symbol in ACTIVE_INSTRUMENTS:
        cfg = PAPER_CONFIGS[symbol]
        if not cfg.get("enabled", False):
            log.info(f"{symbol}: disabled in paper_config — skip")
            summary[symbol] = {"action": "disabled"}
            continue

        log.info(f"─── {symbol} ───────────────────────────────────────────")

        # Pseudo-symbols (e.g. "MES_VA30") trade a real underlying instrument
        # under a different key -- bar fetches must ask the data feed for the
        # REAL instrument (there is no "MES_VA30" ticker), while every other
        # use of `symbol` below (positions dict, tracker, dashboard sync)
        # stays on the pseudo-symbol so PR-A's risk aggregation and the
        # dashboard can tell the two MES strategies apart.
        fetch_symbol = resolve_underlying(symbol)

        # ── Kill-condition check ──────────────────────────────────────────────
        tracker = PaperTradeTracker(cfg)
        kill, kill_reason = tracker.check_kill_conditions()
        if kill:
            log.warning(f"{symbol} KILL SWITCH: {kill_reason}")
            _notify(f"🚨 JARVIS PAPER | {symbol} KILL SWITCH\n{kill_reason}")
            if symbol in positions:
                log.warning(f"{symbol}: Closing open position due to kill switch")
                # Force-close at last known price (market-close approximation)
                pos = positions.pop(symbol)
                log.warning(f"  Position abandoned: {json.dumps(pos, default=str)}")
            summary[symbol] = {"action": "kill_switch", "reason": kill_reason}
            continue

        # ── Fetch bars (validated entry timeframe -- per-symbol interval) ─────
        df = fetch_bars(fetch_symbol, FUTURES_MAP, timeframe=cfg.get("interval", "1h"))
        if df is None:
            has_open = symbol in positions
            count = data_err_state.get(symbol, 0) + 1
            data_err_state[symbol] = count
            log.error(
                f"{symbol}: bar fetch failed — skipping cycle "
                f"(consecutive data_error #{count}, open_position={has_open})"
            )
            # New entries are already skipped for this symbol (the `continue`
            # below). The defect this guards is the SILENT part: an open position
            # with a dark feed is unprotected and nothing said so. Make it loud.
            if has_open and should_alert_data_error(count):
                pos = positions.get(symbol, {})
                stop = pos.get("stop")
                side = str(pos.get("side", "?")).upper()
                log.critical(
                    f"{symbol}: STOP UNENFORCED — bar feed dark for {count} consecutive "
                    f"cycles (~{count * 5}m) with an OPEN {side} position "
                    f"(entry={pos.get('entry_price', '?')}, stop={stop}). The bar-loop "
                    f"cannot evaluate the stop until the feed recovers."
                )
                _notify(
                    f"🚨 JARVIS PAPER | {symbol} STOP UNENFORCED\n"
                    f"Bar feed dark {count} cycles (~{count * 5}m) with OPEN {side}.\n"
                    f"Entry {pos.get('entry_price', '?')} | Stop {stop}\n"
                    f"Bar-loop blind; in-process stop-monitor is the backstop."
                )
            summary[symbol] = {
                "action": "data_error",
                "consecutive": count,
                "open_position": has_open,
            }
            continue

        # Feed recovered for this symbol — clear the counter and, if we had been
        # alerting, announce the all-clear so the operator knows it's resolved.
        if data_err_state.get(symbol):
            prior = data_err_state.pop(symbol)
            if prior >= DATA_ERROR_ALERT_THRESHOLD:
                log.info(f"{symbol}: bar feed recovered after {prior} starved cycles")
                _notify(
                    f"✅ JARVIS PAPER | {symbol} bar feed recovered "
                    f"after {prior} starved cycles"
                )

        # ── Compute 1h signals ────────────────────────────────────────────────
        try:
            if cfg.get("strategy") == "sma_trend":
                # Route SMA trend instruments (MES) through generate_instrument_signals()
                # which dispatches to trend_signals.generate_sma_trend_signals() via
                # the TREND_INSTRUMENTS set. This also applies DO_NOT_TRADE and gate v2
                # enforcement layers automatically.
                sma_params = cfg.get("sma_params", {})
                rv_kwargs = {}
                if "min_rv_annualized" in sma_params:
                    rv_kwargs["min_rv_annualized"] = sma_params["min_rv_annualized"]
                df_signals = generate_instrument_signals(
                    df,
                    symbol=symbol,
                    fast=sma_params.get("fast", 50),
                    slow=sma_params.get("slow", 200),
                    atr_trail_mult=sma_params.get("atr_trail_mult", 2.0),
                    **rv_kwargs,
                )
            elif cfg.get("strategy") == "va_reentry":
                # Route Value-Area re-entry pseudo-symbols (MES_VA30) through
                # generate_instrument_signals() -> signals_va_reentry path.
                # verdict_symbol overrides the gate v2 lookup to the real
                # underlying instrument's verdict file (see MES_VA30_CONFIG).
                va_params = cfg.get("va_reentry_params", {})
                df_signals = generate_instrument_signals(
                    df,
                    symbol=symbol,
                    stop_atr_mult=va_params.get("stop_atr_mult", 1.0),
                    verdict_symbol=cfg.get("verdict_symbol", symbol),
                )
            else:
                params = cfg["stc_params"]
                df_signals = generate_signals(
                    df,
                    symbol=symbol,
                    stc_oversold=params["stc_os"],
                    stc_overbought=params["stc_ob"],
                    regime_filter=cfg.get("regime_filter", True),
                    adaptive_regime=cfg.get("adaptive_regime", False),
                    volume_filter=cfg.get("volume_filter", False),
                )
        except Exception as exc:
            log.error(f"{symbol}: signal generation failed: {exc}", exc_info=True)
            summary[symbol] = {"action": "signal_error"}
            continue

        # An empty signal frame (all bars filtered, or a starved feed) would make
        # the .iloc[-1] reads below raise IndexError and crash the whole poll
        # cycle for every symbol. Skip this symbol's cycle instead.
        if df_signals is None or df_signals.empty:
            log.warning(f"{symbol}: empty signal frame — skipping management/entry this cycle")
            summary[symbol] = {"action": "no_signal_data"}
            continue

        last_bar = df_signals.iloc[-1]
        current_time = str(df_signals.index[-1])

        action = "no_signal"
        closed_record = None

        if symbol in positions:
            # ── Manage open position against the latest 5m bar ────────────────
            # Entries stay on the validated 1h edge, but exits are checked at 5m
            # granularity so an intrabar stop/target fill isn't missed or mispriced
            # the way an hourly-only check would.
            try:
                mgmt_bar, mgmt_time = _latest_mgmt_bar(fetch_symbol, FUTURES_MAP, df_signals)
                updated_pos, closed_record = manage_open_position(
                    symbol, positions[symbol], mgmt_bar, mgmt_time, cfg, tracker
                )
            except Exception as exc:
                # A transient 5m feed error inside _latest_mgmt_bar, or a malformed
                # position row (e.g. a NULL stop → float(None) in manage_open_position),
                # must NOT escape the per-symbol loop. Unguarded, it would abort every
                # REMAINING symbol's management this cycle — leaving their open positions'
                # stops unevaluated (money risk). Log loudly, flag, and move on; the
                # position stays tracked and is retried next poll.
                log.error(f"{symbol}: position management failed: {exc}", exc_info=True)
                summary[symbol] = {"action": "mgmt_error", "position": positions.get(symbol)}
                continue
            if updated_pos is None:
                # Position closed
                del positions[symbol]
                action = (
                    f"closed_{closed_record.get('exit_reason', 'unknown')}"
                    if closed_record
                    else "closed"
                )
            else:
                positions[symbol] = updated_pos
                action = "holding"

        # ── Check for new entry (only if flat) ────────────────────────────────
        elif cfg.get("max_concurrent_positions", 1) > len([s for s in positions if s == symbol]):
            # Evaluate entry only on a freshly CLOSED 1h bar: drop the in-progress
            # last bar so the signal is read off a completed crossover (the validated
            # behaviour), and act on each bar at most once. Dedup matters now that we
            # poll every 5 min — without it, a position stopped out mid-hour would
            # re-enter the same crossover bar on the next poll.
            completed = df_signals.iloc[:-1]
            if len(completed) >= 2:
                completed_ts = str(completed.index[-1])
                if completed_ts != last_entry_eval.get(symbol):
                    last_entry_eval[symbol] = completed_ts
                    new_pos = check_for_entry(symbol, completed, cfg)
                    if new_pos:
                        positions[symbol] = new_pos
                        _try_sync_engine_open(new_pos)
                        action = "entered"
                else:
                    action = "entry_evaluated"

        summary[symbol] = {
            "action": action,
            "position": positions.get(symbol),
            "last_bar": {
                "time": current_time,
                "close": round(float(last_bar["close"]), 4),
                "regime": str(last_bar.get("regime", "?")),
                "entry_signal": str(last_bar.get("entry_signal", "?")),
                "bias": str(last_bar.get("bias", "?")),
                "stc": round(float(last_bar.get("stc_val", 0)), 2),
                "atr": round(float(last_bar.get("atr", 0)), 4),
            },
        }

    # ── Persist state ─────────────────────────────────────────────────────────
    save_positions(positions)
    _save_entry_eval(last_entry_eval)
    _save_data_error_state(data_err_state)

    if not quiet:
        log.info("═" * 64)
        _print_summary(summary, positions)

    return summary


# ── CLI Helpers ───────────────────────────────────────────────────────────────


def _print_summary(summary: Dict[str, Any], positions: Dict[str, Any]) -> None:
    log = logging.getLogger("paper_runner")
    log.info("SUMMARY:")
    for symbol, info in summary.items():
        action = info.get("action", "?")
        bar = info.get("last_bar", {})
        pos = positions.get(symbol)

        status_parts = [f"  {symbol:<6} [{action:<18}]"]
        if bar:
            status_parts.append(
                f"close={bar.get('close', '?'):<10} "
                f"regime={bar.get('regime', '?'):<16} "
                f"signal={bar.get('entry_signal', '?'):<20} "
                f"STC={bar.get('stc', '?')}"
            )
        if pos:
            status_parts.append(
                f"  ↳ OPEN {pos['side'].upper()} @ {pos['entry_price']} "
                f"stop={pos['stop']} targets={pos['targets']}"
            )
        log.info("".join(status_parts))


def _cmd_status() -> None:
    """Print current open positions and per-instrument trade metrics."""
    _setup_logging()
    (
        _futures_map,
        ACTIVE_INSTRUMENTS,
        PAPER_CONFIGS,
        PaperTradeTracker,
        _gen_signals,
        _gen_instrument_signals,
        _resolve_underlying,
    ) = _import_signal_deps()

    positions = load_positions()

    print("\n" + "═" * 60)
    print(f"  JARVIS Paper Trading Status — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("═" * 60)

    for symbol in ACTIVE_INSTRUMENTS:
        cfg = PAPER_CONFIGS[symbol]
        tracker = PaperTradeTracker(cfg)
        metrics = tracker.get_metrics()
        kill, kill_reason = tracker.check_kill_conditions()

        status_flag = "🔴 KILL" if kill else ("✅ ACTIVE" if cfg.get("enabled") else "⏸  DISABLED")

        print(f"\n  {symbol}  {status_flag}")
        print(f"    Trades:    {metrics.get('total_trades', 0)}")
        print(f"    Win Rate:  {metrics.get('win_rate', 0):.1%}")
        print(f"    Total PnL: ${metrics.get('total_pnl', 0):+.2f}")
        print(f"    Max DD:    ${metrics.get('max_drawdown', 0):.2f}")
        if kill:
            print(f"    ⚠️  Kill reason: {kill_reason}")

        pos = positions.get(symbol)
        if pos:
            print(
                f"    Open:      {pos['side'].upper()} {pos.get('qty', 1)} @ "
                f"{pos['entry_price']}  stop={pos['stop']}  targets={pos['targets']}"
            )


# ── One-Time Migration (JSONL → SQLite) ───────────────────────────────────────


def migrate_jsonl_to_sqlite(jsonl_path: str) -> int:
    """
    One-time migration: read existing JSONL trade log and INSERT rows into SQLite.

    Idempotent — skips rows already in DB (matched by symbol + entry_time + side).

    Parameters
    ----------
    jsonl_path : str
        Path to the JSONL file (e.g., engine/portfolio/trades.jsonl).

    Returns
    -------
    int
        Count of rows inserted.
    """
    import json
    from pathlib import Path

    from database.manager import init_db

    db = init_db()
    jsonl_file = Path(jsonl_path)

    if not jsonl_file.exists():
        logging.getLogger("paper_runner").info(f"JSONL file not found: {jsonl_path}")
        return 0

    inserted = 0
    try:
        with open(jsonl_file, "r") as f:
            for line_num, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    logging.getLogger("paper_runner").warning(
                        f"Skipped malformed JSONL line {line_num}: {exc}"
                    )
                    continue

                symbol = record.get("symbol", "").upper()
                entry_date = record.get("entry_date", "")
                side = record.get("side", "").lower()
                entry_price = float(record.get("entry_price", 0.0))

                # Construct trade_id for idempotency
                trade_id = f"{symbol}_{entry_date}_{side}_{entry_price}"

                # Check if already exists
                existing = db.get_trade_by_id(trade_id)
                if existing:
                    logging.getLogger("paper_runner").debug(
                        f"Trade {trade_id} already in DB, skipping"
                    )
                    continue

                # Insert as closed trade
                try:
                    exit_price = float(record.get("exit_price", entry_price))
                    pnl = float(record.get("pnl", 0.0))
                    exit_date = record.get("exit_date", entry_date)
                    contracts = int(record.get("contracts", 1))

                    strategy_params = {
                        "exit_reason": record.get("exit_reason", "migrated"),
                        "regime_type": record.get("regime_type", "unknown"),
                        "contracts": contracts,
                        "pnl_pct": record.get("pnl_pct", 0.0),
                    }

                    # Add optional fields if present
                    for key in [
                        "regime",
                        "structure_position",
                        "bias",
                        "composite_score",
                        "stc_contrib",
                        "orb_contrib",
                        "vwap_contrib",
                        "risk_pct_used",
                    ]:
                        if key in record and record[key] is not None:
                            strategy_params[key] = record[key]

                    # Insert and close
                    db.insert_trade(
                        trade_id=trade_id,
                        symbol=symbol,
                        side=side,
                        quantity=float(contracts),
                        entry_price=entry_price,
                        entry_time=entry_date,
                        status="closed",
                        strategy_params=strategy_params,
                        notes="(migrated from JSONL)",
                    )
                    db.close_trade(
                        trade_id=trade_id,
                        exit_price=exit_price,
                        pnl=pnl,
                        exit_time=exit_date,
                        notes=None,
                    )
                    inserted += 1
                    logging.getLogger("paper_runner").info(
                        f"Migrated trade: {symbol} {side} {entry_price:.2f}→{exit_price:.2f}"
                    )
                except Exception as exc:
                    logging.getLogger("paper_runner").error(
                        f"Failed to migrate line {line_num}: {exc}"
                    )
    except Exception as exc:
        logging.getLogger("paper_runner").error(
            f"Migration failed to read JSONL: {exc}", exc_info=True
        )

    logging.getLogger("paper_runner").info(f"Migration complete: {inserted} trades inserted")
    return inserted


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Standalone invocation (e.g. the hourly Jarvis-PaperCollect task) may run
    # under a cp1252 console; the box-drawing chars in status/summary output
    # otherwise raise UnicodeEncodeError and fail the task. Force UTF-8 with a
    # lossy fallback so output never crashes the cycle.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

    import argparse

    parser = argparse.ArgumentParser(
        prog="paper_runner.py",
        description="JARVIS Paper Trading Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m backtest.paper_runner          # single cycle\n"
            "  python -m backtest.paper_runner --watch  # continuous hourly loop\n"
            "  python -m backtest.paper_runner --status # show current positions & metrics"
        ),
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Run continuously every hour",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print positions and metrics, then exit",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        metavar="INTERVAL",
        help="Watch mode interval in minutes",
    )

    args = parser.parse_args()

    if args.status:
        _cmd_status()
        sys.exit(0)

    if args.watch:
        _setup_logging()
        log = logging.getLogger("paper_runner")
        interval_minutes = args.interval
        log.info("Watch mode: running every %dm. Ctrl-C to stop.", interval_minutes)
        while True:
            try:
                run_one_cycle()
            except KeyboardInterrupt:
                log.info("Stopped by user.")
                break
            except Exception as exc:  # noqa: BLE001
                log.exception("Cycle error: %s — retrying next interval", exc)
            next_run = datetime.now() + timedelta(minutes=interval_minutes)
            # Align to :05 past the next hour if interval is 60m
            if interval_minutes == 60:
                next_run = next_run.replace(minute=5, second=0, microsecond=0)
            wait_secs = max(0, (next_run - datetime.now()).total_seconds())
            log.info("Next run in %.1f min @ %s UTC", wait_secs / 60, next_run.strftime("%H:%M"))
            time.sleep(wait_secs)
    else:
        # Single cycle (default)
        run_one_cycle()
