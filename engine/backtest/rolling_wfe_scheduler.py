"""
JARVIS TRADER — Rolling WFE Recalculation Scheduler
=====================================================
Automatically re-runs walk-forward validation every 4 weeks for each
approved paper-trading instrument (MCL, MNQ) and issues WhatsApp alerts
if WFE drops below the minimum thresholds.

Kill thresholds (canonical v2.7):
    MCL:  rolling_wfe_minimum = 0.40  → halt if WFE < 0.40
    MNQ:  rolling_wfe_minimum = 0.30  → halt if WFE < 0.30

Schedule:
    Run this script via PM2 cron or Windows Task Scheduler:
    .venv/Scripts/python -m backtest.rolling_wfe_scheduler

    Recalculation cadence: every 28 days (configurable via --cadence-days).
    State persisted in:  engine/backtest/results/rolling_wfe_state.json

Usage:
    cd engine
    .venv/Scripts/python -m backtest.rolling_wfe_scheduler                   # Normal run (skips if < 28 days since last run)
    .venv/Scripts/python -m backtest.rolling_wfe_scheduler --force           # Force recalculation now
    .venv/Scripts/python -m backtest.rolling_wfe_scheduler --instrument MCL  # Single instrument
    .venv/Scripts/python -m backtest.rolling_wfe_scheduler --dry-run         # Print plan without running
    .venv/Scripts/python -m backtest.rolling_wfe_scheduler --status          # Show last run status
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Path setup ────────────────────────────────────────────────────────────────
engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

RESULTS_DIR = Path(__file__).parent / "results"
STATE_FILE = RESULTS_DIR / "rolling_wfe_state.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── Instrument configurations ─────────────────────────────────────────────────

INSTRUMENT_CONFIGS: Dict[str, Dict[str, Any]] = {
    "MCL": {
        "symbol": "MCL",
        "interval": "1h",
        "start": "2024-06-01",
        "train_months": 6,
        "test_months": 3,
        "step_months": 3,
        "adaptive_regime": False,
        "volume_filter": False,
        "mtf_filter": False,
        "wfe_minimum": 0.40,  # Halt threshold — from MCL_PAPER_CONFIG kill_threshold
        "wfe_excellent": 0.70,
        "wfe_good": 0.50,
        "last_known_wfe": 0.82,  # Baseline from v2.7 (2026-03-29T23:41)
        "paper_config_key": "MCL_PAPER_CONFIG",
    },
    "MNQ": {
        "symbol": "MNQ",
        "interval": "1h",
        "start": "2024-04-26",  # Extended start that produced WFE=0.57
        "train_months": 6,
        "test_months": 3,
        "step_months": 3,
        "adaptive_regime": True,  # CRITICAL — MTF=OFF, Volume=OFF
        "volume_filter": False,  # NEVER ENABLE — degrades to -0.23
        "mtf_filter": False,  # NEVER ENABLE — degrades to 0.17
        "wfe_minimum": 0.30,  # Halt threshold — from MNQ_PAPER_CONFIG kill_threshold
        "wfe_excellent": 0.70,
        "wfe_good": 0.50,
        "last_known_wfe": 0.57,  # Baseline from v2.7 (2026-03-29T23:46)
        "paper_config_key": "MNQ_PAPER_CONFIG",
    },
}

DEFAULT_CADENCE_DAYS = 28  # 4-week rolling cadence per JARVIS_TRADER_MASTER.md §1.5


# ── State management ──────────────────────────────────────────────────────────


class RollingWFEState:
    """Persistent state for the rolling WFE scheduler."""

    def __init__(self, state_file: Path | None = None):
        # Default resolved here (call-time), not as a `= STATE_FILE` parameter
        # default -- a parameter default is bound once at module-load time, so
        # a test's patch("backtest.rolling_wfe_scheduler.STATE_FILE", tmp_path)
        # silently has no effect on RollingWFEState() call sites that rely on
        # the default. 2026-08-11: this let test_good_verdict_sets_halt_
        # required_false write its mocked WFE (0.60) straight into the real
        # production rolling_wfe_state.json via run_scheduler()'s no-arg
        # `RollingWFEState()` call, clobbering the real MCL run_count.
        self.state_file = state_file if state_file is not None else STATE_FILE
        self._state = self._load()

    def _load(self) -> Dict[str, Any]:
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text())
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Could not read state file: {e}. Starting fresh.")
        return {"instruments": {}, "last_global_run": None}

    def save(self) -> None:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(self._state, indent=2, default=str))

    def get_instrument_state(self, symbol: str) -> Dict[str, Any]:
        return self._state["instruments"].get(symbol, {})

    def update_instrument(self, symbol: str, wfe: float, run_ts: str, result_path: str) -> None:
        if "instruments" not in self._state:
            self._state["instruments"] = {}
        prev = self._state["instruments"].get(symbol, {})
        self._state["instruments"][symbol] = {
            "last_run": run_ts,
            "last_wfe": wfe,
            "prev_wfe": prev.get("last_wfe"),
            "wfe_delta": round(wfe - (prev.get("last_wfe") or 0), 4)
            if prev.get("last_wfe")
            else None,
            "result_path": result_path,
            "run_count": prev.get("run_count", 0) + 1,
        }
        self._state["last_global_run"] = run_ts

    def days_since_last_run(self, symbol: str) -> Optional[int]:
        inst = self.get_instrument_state(symbol)
        last = inst.get("last_run")
        if not last:
            return None
        try:
            last_dt = datetime.fromisoformat(last)
            return (datetime.utcnow() - last_dt).days
        except (ValueError, TypeError):
            return None

    def is_due(self, symbol: str, cadence_days: int = DEFAULT_CADENCE_DAYS) -> bool:
        """Returns True if a recalculation is due for the given instrument."""
        days = self.days_since_last_run(symbol)
        if days is None:
            return True  # Never run — always due
        return days >= cadence_days


# ── WFE runner ────────────────────────────────────────────────────────────────


def run_wfe_for_instrument(
    cfg: Dict[str, Any],
    end_date: str,
    dry_run: bool = False,
) -> Optional[float]:
    """
    Run walk-forward validation for a single instrument and return the WFE.
    Returns None if the run fails.
    """
    symbol = cfg["symbol"]
    logger.info(f"  [{symbol}] Starting WFE recalculation...")
    logger.info(
        f"  [{symbol}] Config: interval={cfg['interval']} start={cfg['start']} end={end_date}"
        f" adaptive={cfg['adaptive_regime']} mtf={cfg['mtf_filter']} vol={cfg['volume_filter']}"
    )

    if dry_run:
        logger.info(f"  [{symbol}] DRY RUN — would run WFE, returning last known WFE.")
        return cfg.get("last_known_wfe")

    try:
        from backtest.data_loader import BacktestDataLoader
        from backtest.walk_forward import WalkForwardValidator
    except ImportError as e:
        logger.error(f"  [{symbol}] Import error: {e}. Make sure you're in the engine/ directory.")
        return None

    try:
        loader = BacktestDataLoader()
        df = loader.load(symbol=symbol, start=cfg["start"], end=end_date, interval=cfg["interval"])
        if df is None or len(df) < 200:
            logger.error(
                f"  [{symbol}] Insufficient data: {len(df) if df is not None else 0} bars."
            )
            return None

        validator = WalkForwardValidator(
            train_months=cfg["train_months"],
            test_months=cfg["test_months"],
            step_months=cfg["step_months"],
        )

        results = validator.run(
            df=df,
            symbol=symbol,
            interval=cfg["interval"],
            adaptive_regime=cfg["adaptive_regime"],
            volume_filter=cfg["volume_filter"],
            mtf_filter=cfg["mtf_filter"],
        )

        wfe = results.get("wfe", results.get("walk_forward_efficiency"))
        if wfe is None:
            logger.error(f"  [{symbol}] WFE not found in results: {list(results.keys())}")
            return None

        wfe = float(wfe)
        logger.info(f"  [{symbol}] WFE = {wfe:.4f}")
        return wfe

    except Exception as e:
        logger.error(f"  [{symbol}] Run failed: {e}", exc_info=True)
        return None


def evaluate_wfe(symbol: str, wfe: float, cfg: Dict[str, Any]) -> str:
    """Return EXCELLENT / GOOD / MARGINAL / OVERFIT / HALT based on WFE."""
    minimum = cfg["wfe_minimum"]
    if wfe >= cfg["wfe_excellent"]:
        return "EXCELLENT"
    elif wfe >= cfg["wfe_good"]:
        return "GOOD"
    elif wfe >= minimum:
        return "MARGINAL"
    elif wfe >= 0.30:
        return "OVERFIT"
    else:
        return "HALT"


def send_alert(symbol: str, wfe: float, verdict: str, prev_wfe: Optional[float]) -> None:
    """Send WhatsApp alert for significant WFE changes."""
    try:
        from notifications.whatsapp import WhatsAppNotifier

        notifier = WhatsAppNotifier()

        delta_str = ""
        if prev_wfe is not None:
            delta = wfe - prev_wfe
            arrow = "↑" if delta > 0 else "↓"
            delta_str = f" ({arrow}{abs(delta):.4f} vs prev {prev_wfe:.4f})"

        if verdict == "HALT":
            msg = (
                f"🔴 [TRADE] ROLLING WFE ALERT — {symbol} BELOW HALT THRESHOLD\n"
                f"WFE = {wfe:.4f}{delta_str}\n"
                f"Threshold: {INSTRUMENT_CONFIGS[symbol]['wfe_minimum']:.2f}\n"
                f"STATUS: Paper trading should be SUSPENDED pending review.\n"
                f"Run: backtest.rolling_wfe_scheduler --force to recheck."
            )
        elif verdict == "OVERFIT":
            msg = (
                f"⚠️ [TRADE] ROLLING WFE WARN — {symbol} degraded\n"
                f"WFE = {wfe:.4f}{delta_str}\n"
                f"Below GOOD threshold. Monitor closely."
            )
        elif prev_wfe is not None and wfe > prev_wfe + 0.05:
            msg = (
                f"✅ [TRADE] ROLLING WFE UPDATE — {symbol} improved\n"
                f"WFE = {wfe:.4f}{delta_str}\n"
                f"Verdict: {verdict}"
            )
        else:
            # Stable / minor change — no alert
            return

        # WhatsAppNotifier.send is async; the scheduler is sync, so we drive
        # it through asyncio.run.  Bug history: prior to 2026-05-07 this was
        # `notifier.send(msg)` — the unawaited coroutine was silently dropped
        # and rolling-WFE HALT/OVERFIT alerts never reached the user
        # (mypy: unused-coroutine).
        import asyncio

        asyncio.run(notifier.send(msg))
        logger.info(f"  [{symbol}] WhatsApp alert sent: {verdict}")

    except Exception as e:
        logger.warning(f"  [{symbol}] Could not send WhatsApp alert: {e}")


# ── Main scheduler loop ───────────────────────────────────────────────────────


def run_scheduler(
    instruments: Optional[List[str]] = None,
    force: bool = False,
    dry_run: bool = False,
    cadence_days: int = DEFAULT_CADENCE_DAYS,
    end_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Main entry point for the rolling WFE scheduler.

    Parameters
    ----------
    instruments : list[str] | None
        Symbols to check. Defaults to all approved instruments (MCL, MNQ).
    force : bool
        Ignore cadence and always recalculate.
    dry_run : bool
        Print plan without actually running WFE.
    cadence_days : int
        Minimum days between recalculations (default 28).
    end_date : str | None
        End date for the walk-forward. Defaults to today.

    Returns
    -------
    dict
        Summary of this run: each instrument's WFE, verdict, action.
    """
    now = datetime.utcnow()
    run_ts = now.isoformat()
    if end_date is None:
        end_date = now.strftime("%Y-%m-%d")

    approved_instruments = list(INSTRUMENT_CONFIGS.keys())
    if instruments:
        instruments = [s.upper() for s in instruments]
        unknown = [s for s in instruments if s not in INSTRUMENT_CONFIGS]
        if unknown:
            logger.warning(f"Unknown instruments (not in approved list): {unknown}")
        instruments = [s for s in instruments if s in INSTRUMENT_CONFIGS]
    else:
        instruments = approved_instruments

    state = RollingWFEState()
    summary: Dict[str, Any] = {"run_ts": run_ts, "end_date": end_date, "results": {}}

    logger.info("=" * 60)
    logger.info("JARVIS TRADER — Rolling WFE Scheduler")
    logger.info(f"Run timestamp: {run_ts}")
    logger.info(f"Instruments:   {instruments}")
    logger.info(f"End date:      {end_date}")
    logger.info(f"Force:         {force}")
    logger.info(f"Dry run:       {dry_run}")
    logger.info(f"Cadence days:  {cadence_days}")
    logger.info("=" * 60)

    for symbol in instruments:
        cfg = INSTRUMENT_CONFIGS[symbol]
        inst_state = state.get_instrument_state(symbol)
        days_since = state.days_since_last_run(symbol)

        logger.info(
            f"\n[{symbol}] Last run: {inst_state.get('last_run', 'NEVER')} "
            f"({days_since if days_since is not None else 'N/A'} days ago)"
        )
        logger.info(f"[{symbol}] Last WFE: {inst_state.get('last_wfe', cfg['last_known_wfe']):.4f}")

        # Check if due
        if not force and not state.is_due(symbol, cadence_days):
            logger.info(
                f"[{symbol}] ⏭  Not due yet (need {cadence_days} days, only {days_since} elapsed). Skipping."
            )
            summary["results"][symbol] = {
                "status": "skipped",
                "reason": f"Not due ({days_since}/{cadence_days} days elapsed)",
                "last_wfe": inst_state.get("last_wfe", cfg["last_known_wfe"]),
            }
            continue

        logger.info(f"[{symbol}] ▶  Running WFE recalculation...")
        wfe = run_wfe_for_instrument(cfg, end_date=end_date, dry_run=dry_run)

        if wfe is None:
            logger.error(f"[{symbol}] ✗  WFE run failed — keeping previous state.")
            summary["results"][symbol] = {
                "status": "error",
                "reason": "WFE run returned None",
                "last_wfe": inst_state.get("last_wfe", cfg["last_known_wfe"]),
            }
            continue

        verdict = evaluate_wfe(symbol, wfe, cfg)
        prev_wfe = inst_state.get("last_wfe", cfg["last_known_wfe"])
        result_path = str(
            RESULTS_DIR / f"WF_{symbol}_{cfg['interval']}_rolling_{now.strftime('%Y%m%d')}.json"
        )

        # Determine action
        if verdict == "HALT":
            action = f"SUSPEND paper trading — WFE {wfe:.4f} below halt threshold {cfg['wfe_minimum']:.2f}"
        elif verdict in ("OVERFIT", "MARGINAL"):
            action = f"MONITOR closely — WFE {wfe:.4f} degraded from {prev_wfe:.4f}"
        else:
            action = f"Continue paper trading — WFE {wfe:.4f} {verdict}"

        logger.info(f"[{symbol}] WFE = {wfe:.4f} | Verdict: {verdict} | {action}")

        # Update state
        state.update_instrument(symbol, wfe, run_ts, result_path)
        state.save()

        # Send alert if needed
        send_alert(symbol, wfe, verdict, prev_wfe)

        summary["results"][symbol] = {
            "status": "completed",
            "wfe": round(wfe, 4),
            "verdict": verdict,
            "prev_wfe": round(prev_wfe, 4) if prev_wfe else None,
            "delta": round(wfe - prev_wfe, 4) if prev_wfe else None,
            "action": action,
            "halt_required": verdict == "HALT",
        }

    # Save run summary
    summary_path = RESULTS_DIR / f"rolling_wfe_run_{now.strftime('%Y%m%d_%H%M%S')}.json"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, default=str))
    logger.info(f"\nSummary saved: {summary_path}")

    return summary


def print_status() -> None:
    """Print current rolling WFE state for all instruments."""
    state = RollingWFEState()
    print("\n" + "=" * 60)
    print("JARVIS TRADER — Rolling WFE Status")
    print("=" * 60)
    for symbol, cfg in INSTRUMENT_CONFIGS.items():
        inst = state.get_instrument_state(symbol)
        days = state.days_since_last_run(symbol)
        due = state.is_due(symbol, DEFAULT_CADENCE_DAYS)
        last_wfe = inst.get("last_wfe", cfg["last_known_wfe"])
        verdict = evaluate_wfe(symbol, last_wfe, cfg) if last_wfe else "UNKNOWN"
        print(f"\n  {symbol}")
        print(f"    Last run:   {inst.get('last_run', 'NEVER')}")
        print(f"    Days since: {days if days is not None else 'N/A'}")
        print(f"    Due:        {'YES' if due else 'NO'}")
        print(f"    Last WFE:   {last_wfe:.4f}" if last_wfe else "    Last WFE:   (none)")
        print(f"    Verdict:    {verdict}")
        print(f"    Threshold:  {cfg['wfe_minimum']:.2f} (halt) / {cfg['wfe_good']:.2f} (good)")
        print(f"    Run count:  {inst.get('run_count', 0)}")
    print("\n" + "=" * 60)


# ── CLI entry point ───────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="JARVIS TRADER — Rolling 4-Week WFE Recalculation Scheduler",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--instrument",
        "-i",
        nargs="+",
        metavar="SYMBOL",
        help="Specific instrument(s) to check (default: all approved)",
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Force recalculation even if cadence not reached",
    )
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Print plan without running WFE",
    )
    parser.add_argument(
        "--status",
        "-s",
        action="store_true",
        help="Show current rolling WFE state and exit",
    )
    parser.add_argument(
        "--cadence-days",
        "-c",
        type=int,
        default=DEFAULT_CADENCE_DAYS,
        help="Minimum days between recalculations",
    )
    parser.add_argument(
        "--end-date",
        help="Override end date (YYYY-MM-DD). Defaults to today.",
    )
    args = parser.parse_args()

    if args.status:
        print_status()
        return

    summary = run_scheduler(
        instruments=args.instrument,
        force=args.force,
        dry_run=args.dry_run,
        cadence_days=args.cadence_days,
        end_date=args.end_date,
    )

    # Exit 1 if any instrument requires halting
    halt_required = any(r.get("halt_required", False) for r in summary.get("results", {}).values())
    if halt_required:
        logger.critical(
            "🔴 HALT REQUIRED — at least one instrument WFE below threshold. Review immediately."
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
