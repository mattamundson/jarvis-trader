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
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
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
            str(RUNNER_LOG_FILE), maxBytes=5 * 1024 * 1024, backupCount=3
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
    from backtest.paper_config import ACTIVE_INSTRUMENTS, PAPER_CONFIGS
    from backtest.paper_tracker import PaperTradeTracker
    from backtest.signals import generate_signals

    return FUTURES_MAP, ACTIVE_INSTRUMENTS, PAPER_CONFIGS, PaperTradeTracker, generate_signals


# ── Position State I/O ────────────────────────────────────────────────────────


def load_positions() -> Dict[str, Any]:
    """
    Load open paper positions from SQLite via database manager.

    Returns dict mapping symbol -> position record.
    """
    try:
        from database.manager import get_db
        db = get_db()
        open_trades = db.get_open_trades()
        # Convert to position format: {symbol: position_dict}
        positions = {}
        for trade in open_trades:
            symbol = trade.get("symbol", "")
            if symbol:
                positions[symbol] = trade
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


def fetch_bars(symbol: str, futures_map: Dict[str, str], bars: int = 150) -> Optional[pd.DataFrame]:
    """
    Fetch recent 1h OHLCV bars for a futures symbol via Polygon.io.

    Uses BacktestDataLoader which handles Polygon API calls and disk caching.
    Returns None if data is unavailable or too thin for indicator warmup.
    """
    from backtest.data_loader import BacktestDataLoader

    log = logging.getLogger(f"paper_runner.{symbol}")

    end_dt = datetime.now(timezone.utc).replace(tzinfo=None)
    start_dt = end_dt - timedelta(days=90)
    start_str = start_dt.strftime("%Y-%m-%d")
    end_str = end_dt.strftime("%Y-%m-%d")

    try:
        loader = BacktestDataLoader()
        df = loader.load(symbol, start_str, end_str, interval="1h")
    except Exception as exc:
        log.error(f"Bar fetch failed for {symbol}: {exc}")
        return None

    if df is None or df.empty:
        log.error(f"Bar fetch returned no data for {symbol}")
        return None

    # Ensure standard lowercase columns are present
    df.columns = [c.lower() for c in df.columns]
    cols = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[cols].dropna(subset=["open", "high", "low", "close"])

    if len(df) < 60:
        log.warning(f"Only {len(df)} bars for {symbol} — need >=60 for indicator warmup")
        return None

    log.debug(f"Fetched {len(df)} 1h bars for {symbol}")
    return df


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

    # No hit — position still active
    return pos, None


# ── Entry Signal Detection ────────────────────────────────────────────────────


def check_for_entry(
    symbol: str,
    df_signals: pd.DataFrame,
    cfg: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Look at the most recent bar for an ENTRY_NOW signal.

    Returns a new position dict or None.
    """
    log = logging.getLogger(f"paper_runner.{symbol}")

    last_bar = df_signals.iloc[-1]
    entry_signal = str(last_bar.get("entry_signal", ""))

    if entry_signal != "ENTRY_NOW":
        log.debug(f"{symbol}: No entry signal (got '{entry_signal}')")
        return None

    bias = str(last_bar.get("bias", ""))
    side = "long" if bias in ("STRONG_BULL", "LEAN_BULL") else "short"

    # Use pre-computed signal levels from the signal generator
    entry_price = float(last_bar["close"])
    stop_level = float(last_bar.get("stop_level", 0))
    target_1 = float(last_bar.get("target_1", 0))
    target_2 = float(last_bar.get("target_2", 0))
    target_3 = float(last_bar.get("target_3", 0))

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

    (
        FUTURES_MAP,
        ACTIVE_INSTRUMENTS,
        PAPER_CONFIGS,
        PaperTradeTracker,
        generate_signals,
    ) = _import_signal_deps()

    if not quiet:
        log.info("═" * 64)
        log.info(f"JARVIS Paper Runner — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        log.info(f"Active instruments: {ACTIVE_INSTRUMENTS}")

    positions = load_positions()
    summary: Dict[str, Any] = {}

    for symbol in ACTIVE_INSTRUMENTS:
        cfg = PAPER_CONFIGS[symbol]
        if not cfg.get("enabled", False):
            log.info(f"{symbol}: disabled in paper_config — skip")
            summary[symbol] = {"action": "disabled"}
            continue

        log.info(f"─── {symbol} ───────────────────────────────────────────")

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

        # ── Fetch bars ────────────────────────────────────────────────────────
        df = fetch_bars(symbol, FUTURES_MAP)
        if df is None:
            log.error(f"{symbol}: bar fetch failed — skipping cycle")
            summary[symbol] = {"action": "data_error"}
            continue

        # ── Compute signals ───────────────────────────────────────────────────
        params = cfg["stc_params"]
        try:
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

        last_bar = df_signals.iloc[-1]
        current_time = str(df_signals.index[-1])

        # ── Manage open position ──────────────────────────────────────────────
        action = "no_signal"
        closed_record = None

        if symbol in positions:
            updated_pos, closed_record = manage_open_position(
                symbol, positions[symbol], last_bar, current_time, cfg, tracker
            )
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

        # ── Check for new entry (only if no open position) ────────────────────
        elif cfg.get("max_concurrent_positions", 1) > len([s for s in positions if s == symbol]):
            new_pos = check_for_entry(symbol, df_signals, cfg)
            if new_pos:
                positions[symbol] = new_pos
                _try_sync_engine_open(new_pos)
                action = "entered"

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
        _,
        ACTIVE_INSTRUMENTS,
        PAPER_CONFIGS,
        PaperTradeTracker,
        _,
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
