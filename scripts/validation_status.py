#!/usr/bin/env python3
"""
Paper Trading Validation Status — JARVIS TRADER v2 (QuantStats Edition)
========================================================================
30-day progress tracker with regime-conditional Sharpe/Sortino slicing.

NEW in v2:
  • --regime-analysis flag: slices return series by RISK_ON / RISK_OFF / NORMAL
    and computes qs.stats.sharpe(), .sortino(), .max_drawdown() on each slice
  • Live qs.stats gate cross-check against engine-reported values
  • Full 10-gate display (momentum gate spec)

Usage:
    python scripts/validation_status.py
    python scripts/validation_status.py --regime-analysis
    python scripts/validation_status.py --host localhost --port 8010 --instrument MCL
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from typing import Any

import pandas as pd

try:
    import requests
except ImportError:
    print("Error: requests not installed. Install with: pip install requests")
    sys.exit(1)

try:
    import quantstats as qs
    qs.extend_pandas()
    QS_AVAILABLE = True
except ImportError:
    QS_AVAILABLE = False

# ── Terminal colours ──────────────────────────────────────────────────────
GREEN, RED, YELLOW, CYAN, RESET, BOLD = (
    "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[0m", "\033[1m"
)

# ── Original 6 gates (engine-reported) ───────────────────────────────────
THRESHOLDS = {
    "profit_factor":  2.0,
    "sharpe_ratio":   1.5,
    "win_rate_pct":   55.0,
    "min_trades":     60,
    "min_days":       30,
    "max_drawdown_pct": 15.0,
}

# ── QuantStats 10-gate spec (Run-12 momentum profile) ─────────────────────
QS_GATES: dict[str, tuple[float, str]] = {
    "sharpe":             (1.5,  ">="),
    "sortino":            (1.0,  ">="),
    "calmar":             (0.5,  ">="),
    "tail_ratio":         (1.0,  ">="),
    "common_sense_ratio": (1.5,  ">="),
    "ulcer_perf_index":   (0.5,  ">="),
    "skew":               (-1.5, ">="),
    "max_drawdown":       (0.15, "<="),
}

REGIME_LABELS = ("RISK_ON", "RISK_OFF", "NORMAL")
TARGET_DAYS   = 30


def progress_bar(current: int, target: int, width: int = 20) -> str:
    pct    = min(100, max(0, int(current * 100 / target)))
    filled = int(pct * width / 100)
    return "█" * filled + "░" * (width - filled)


def check_gate(name: str, thresh: float, current: float, is_max: bool = False) -> tuple[str, bool]:
    passed = current <= thresh if is_max else current >= thresh
    status = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
    suffix = "%" if "Rate" in name or "Drawdown" in name else ""
    fmt    = f"{name:20} ≥ {thresh:.1f}{suffix:3s}   Current: {current:.1f}{suffix:3s}   {status}"
    return fmt, passed


# ── API helpers ───────────────────────────────────────────────────────────

def _get_safe(url: str) -> dict | list | None:
    try:
        return requests.get(url, timeout=5).json()
    except Exception as e:
        print(f"{RED}API error [{url}]: {e}{RESET}", file=sys.stderr)
        return None


# ── Return-series builder ─────────────────────────────────────────────────

def build_returns(host: str, port: int, starting_capital: float = 10_000.0) -> pd.Series | None:
    """Build trade return series from /paper/trades/log."""
    raw = _get_safe(f"http://{host}:{port}/paper/trades/log")
    if raw is None:
        return None

    trades = raw if isinstance(raw, list) else raw.get("trades") or []
    rows   = []
    for t in trades:
        pnl = t.get("pnl") or t.get("profit") or t.get("net_pnl")
        ts  = t.get("exit_date") or t.get("date") or t.get("timestamp")
        if pnl is not None and ts is not None:
            try:
                rows.append({"date": pd.to_datetime(ts), "pnl": float(pnl)})
            except Exception:
                continue

    if len(rows) < 5:
        return None

    df      = pd.DataFrame(rows).sort_values("date").set_index("date")
    equity  = starting_capital + df["pnl"].cumsum()
    returns = equity.pct_change().dropna()
    returns.index = returns.index.tz_localize(None)
    return returns


# ── Regime label fetcher ──────────────────────────────────────────────────

def fetch_regime_labels(host: str, port: int, instrument: str) -> pd.Series | None:
    """
    Fetch per-day regime labels from /paper/validation/progress.
    Returns Series indexed by date with values: RISK_ON / RISK_OFF / NORMAL.
    """
    raw = _get_safe(
        f"http://{host}:{port}/paper/validation/progress?instrument={instrument}"
    )
    if raw is None:
        return None

    data = raw.get("data", {})
    log  = data.get("daily_regime_log") or raw.get("daily_regime_log") or []
    if not log:
        return None

    rows = []
    for entry in log:
        d      = entry.get("date") or entry.get("timestamp")
        regime = entry.get("regime") or entry.get("risk_regime") or "NORMAL"
        if d:
            rows.append({"date": pd.to_datetime(d), "regime": str(regime).upper()})

    if not rows:
        return None

    df = pd.DataFrame(rows).sort_values("date").set_index("date")
    return df["regime"]


# ── QuantStats cross-check ────────────────────────────────────────────────

def compute_qs_gates(returns: pd.Series) -> dict[str, float | None]:
    """Compute all QS gates on the return series."""
    if not QS_AVAILABLE or returns is None or len(returns) < 5:
        return {}
    out: dict[str, float | None] = {}
    try:
        out["sharpe"]             = float(qs.stats.sharpe(returns))
        out["sortino"]            = float(qs.stats.sortino(returns))
        out["calmar"]             = float(qs.stats.calmar(returns))
        out["tail_ratio"]         = float(qs.stats.tail_ratio(returns))
        out["common_sense_ratio"] = float(qs.stats.common_sense_ratio(returns))
        out["ulcer_perf_index"]   = float(qs.stats.ulcer_performance_index(returns))
        out["skew"]               = float(qs.stats.skew(returns))
        out["max_drawdown"]       = abs(float(qs.stats.max_drawdown(returns)))
    except Exception as e:
        print(f"{YELLOW}QS computation partial failure: {e}{RESET}")
    return out


def print_qs_gate_table(qs_vals: dict[str, float | None]) -> None:
    if not qs_vals:
        print(f"  {YELLOW}(quantstats not available — install with: pip install quantstats){RESET}")
        return

    print(f"\n{BOLD}QUANTSTATS 10-GATE CHECK (from return series){RESET}")
    print(f"{BOLD}{'─'*57}{RESET}")
    qs_pass = 0
    for metric, (threshold, op) in QS_GATES.items():
        val    = qs_vals.get(metric)
        if val is None:
            label_s = f"{metric:<24}  N/A"
            status  = f"{YELLOW}N/A{RESET}"
        else:
            ok      = (val >= threshold) if op == ">=" else (val <= threshold)
            status  = f"{GREEN}PASS{RESET}" if ok else f"{RED}FAIL{RESET}"
            label_s = f"{metric:<24}  {val:>10.4f}   ({op} {threshold})"
            if ok:
                qs_pass += 1
        print(f"  {label_s}   {status}")

    total = len(QS_GATES)
    colour = GREEN if qs_pass == total else (YELLOW if qs_pass >= total // 2 else RED)
    print(f"\n  {colour}{qs_pass}/{total} qs gates passing{RESET}")


# ── Regime-conditional analysis ───────────────────────────────────────────

def regime_conditional_analysis(
    returns:       pd.Series,
    regime_labels: pd.Series,
) -> None:
    """
    Slice returns by RISK_ON / RISK_OFF / NORMAL and print
    qs.stats.sharpe, sortino, max_drawdown for each regime.
    """
    if not QS_AVAILABLE:
        print(f"\n  {YELLOW}quantstats required for regime analysis. pip install quantstats{RESET}")
        return

    print(f"\n{BOLD}REGIME-CONDITIONAL ANALYSIS{RESET}")
    print(f"{BOLD}{'─'*57}{RESET}")
    print(f"  {'Regime':<12}  {'N':>5}  {'Sharpe':>8}  {'Sortino':>8}  {'MaxDD':>7}  {'Skew':>7}")
    print(f"  {'─'*12}  {'─'*5}  {'─'*8}  {'─'*8}  {'─'*7}  {'─'*7}")

    for regime in REGIME_LABELS:
        regime_dates = regime_labels[regime_labels == regime].index
        slice_ret    = returns[returns.index.isin(regime_dates)]
        n            = len(slice_ret)

        if n < 3:
            print(f"  {regime:<12}  {n:>5}  {'—':>8}  {'—':>8}  {'—':>7}  {'—':>7}  (insufficient)")
            continue

        try:
            sh  = qs.stats.sharpe(slice_ret)
            so  = qs.stats.sortino(slice_ret)
            dd  = abs(qs.stats.max_drawdown(slice_ret))
            sk  = qs.stats.skew(slice_ret)

            colour = GREEN if float(sh) >= 1.0 else (YELLOW if float(sh) >= 0 else RED)
            print(
                f"  {regime:<12}  {n:>5}  "
                f"{colour}{float(sh):>8.3f}{RESET}  "
                f"{float(so):>8.3f}  "
                f"{float(dd)*100:>6.1f}%  "
                f"{float(sk):>7.3f}"
            )
        except Exception as e:
            print(f"  {regime:<12}  {n:>5}  ERROR: {e}")

    print()

    # Summary: which regime is most profitable?
    best = None
    best_sh = float("-inf")
    for regime in REGIME_LABELS:
        regime_dates = regime_labels[regime_labels == regime].index
        slice_ret    = returns[returns.index.isin(regime_dates)]
        if len(slice_ret) >= 3:
            try:
                sh = float(qs.stats.sharpe(slice_ret))
                if sh > best_sh:
                    best_sh = sh
                    best    = regime
            except Exception:
                pass

    if best:
        print(f"  → Best performing regime: {CYAN}{best}{RESET}  (Sharpe {best_sh:.3f})")


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Paper validation + regime analysis — JARVIS TRADER")
    parser.add_argument("--host",            default="localhost")
    parser.add_argument("--port",            type=int, default=8010)
    parser.add_argument("--instrument",      default="MCL")
    parser.add_argument("--regime-analysis", action="store_true",
                        help="Add regime-conditional Sharpe/Sortino breakdown")
    parser.add_argument("--qs-gates",        action="store_true",
                        help="Show full QuantStats 10-gate cross-check")
    parser.add_argument("--capital",         type=float, default=10_000.0)
    args = parser.parse_args()

    base = f"http://{args.host}:{args.port}"

    # Fetch engine data
    p = _get_safe(f"{base}/paper/validation/progress?instrument={args.instrument}")
    if p is None:
        print(f"{RED}Error: cannot reach engine at {base}{RESET}", file=sys.stderr)
        sys.exit(1)
    progress = p.get("data", {})

    port_data = _get_safe(f"{base}/portfolio/stats/paper-phase-summary") or {}

    # Extract metrics
    total_trades    = progress.get("total_trades",    0)
    days_active     = progress.get("days_active",     0)
    profit_factor   = progress.get("profit_factor",   0.0)
    sharpe_ratio    = progress.get("sharpe_ratio",    0.0)
    win_rate_pct    = progress.get("win_rate_pct",    0.0)
    max_drawdown_pct= progress.get("max_drawdown_pct",0.0)
    balance         = port_data.get("current_balance", 0.0)
    total_pnl       = port_data.get("total_pnl",       0.0)
    start_date      = port_data.get("start_date",      "")
    trading_days_p  = port_data.get("trading_days",    1)
    daily_pnl       = total_pnl / max(1, trading_days_p)

    days_remaining = max(0, TARGET_DAYS - days_active)
    trades_needed  = max(0, THRESHOLDS["min_trades"] - total_trades)
    pct            = int(days_active * 100 / TARGET_DAYS)

    # Gate checks
    gates = [
        check_gate("Profit Factor",  THRESHOLDS["profit_factor"],   profit_factor),
        check_gate("Sharpe Ratio",   THRESHOLDS["sharpe_ratio"],    sharpe_ratio),
        check_gate("Win Rate",       THRESHOLDS["win_rate_pct"],    win_rate_pct),
        (
            f"Trade Count      ≥ {int(THRESHOLDS['min_trades']):2d}      "
            f"Current: {total_trades:2d}      "
            + (f"{GREEN}PASS{RESET}" if total_trades >= THRESHOLDS["min_trades"]
               else f"{RED}FAIL{RESET} (need {trades_needed} more)"),
            total_trades >= THRESHOLDS["min_trades"],
        ),
        check_gate("Max Drawdown",   THRESHOLDS["max_drawdown_pct"], max_drawdown_pct, is_max=True),
        (
            f"Trading Days     ≥ {int(THRESHOLDS['min_days']):2d}      "
            f"Current: {days_active:2d}      "
            + (f"{GREEN}PASS{RESET}" if days_active >= THRESHOLDS["min_days"]
               else f"{RED}FAIL{RESET} (need {days_remaining} more)"),
            days_active >= THRESHOLDS["min_days"],
        ),
    ]
    gates_passing = sum(1 for _, passed in gates if passed)

    # ── Print header ──────────────────────────────────────────────────────
    print(f"\n{BOLD}═══════════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}JARVIS TRADER — 30-Day Paper Validation Status{RESET}")
    print(f"{BOLD}═══════════════════════════════════════════════════════{RESET}\n")
    print(
        f"Day {days_active} of {TARGET_DAYS}  "
        f"{progress_bar(days_active, TARGET_DAYS)}  "
        f"{pct:3d}%  ({days_remaining} days remaining)\n"
    )

    # ── Original 6 gates ──────────────────────────────────────────────────
    print(f"{BOLD}VALIDATION GATES (engine-reported){RESET}")
    print(f"{BOLD}{'─'*53}{RESET}")
    for line, _ in gates:
        print(line)

    # ── Portfolio ─────────────────────────────────────────────────────────
    print(f"\n{BOLD}PORTFOLIO{RESET}")
    print(f"{BOLD}{'─'*53}{RESET}")
    print(
        f"Balance: ${balance:,.2f}    "
        f"Daily P&L: {GREEN if daily_pnl >= 0 else RED}{daily_pnl:+.2f}{RESET}    "
        f"Total P&L: {GREEN if total_pnl >= 0 else RED}{total_pnl:+,.2f}{RESET}"
    )
    if start_date:
        print(f"Started: {start_date}")

    # ── Summary ───────────────────────────────────────────────────────────
    print(f"\n{BOLD}SUMMARY{RESET}")
    summary_col = GREEN if gates_passing == 6 else YELLOW
    print(
        f"{gates_passing}/6 gates passing — "
        + (f"{GREEN}ALL GATES PASSED{RESET}" if gates_passing == 6 else f"{YELLOW}In Progress{RESET}")
    )

    # ── Optional QuantStats cross-check ───────────────────────────────────
    if args.qs_gates or args.regime_analysis:
        returns = build_returns(args.host, args.port, starting_capital=args.capital)
        if returns is not None:
            if args.qs_gates:
                qs_vals = compute_qs_gates(returns)
                print_qs_gate_table(qs_vals)
        else:
            if not QS_AVAILABLE:
                print(f"\n  {YELLOW}quantstats not installed. Run: pip install quantstats{RESET}")
            else:
                print(f"\n  {YELLOW}Not enough trade data for qs.stats cross-check.{RESET}")
            returns = None

    # ── Regime-conditional analysis ───────────────────────────────────────
    if args.regime_analysis:
        regime_labels = fetch_regime_labels(args.host, args.port, args.instrument)
        if regime_labels is not None and returns is not None:
            regime_conditional_analysis(returns, regime_labels)
        elif regime_labels is None:
            print(
                f"\n  {YELLOW}No regime labels from engine "
                f"(/paper/validation/progress daily_regime_log missing).{RESET}"
            )
            # Fallback: try to fetch from /api/signal
            sig = _get_safe(f"http://{args.host}:{args.port}/api/signal")
            if sig:
                regime = sig.get("layers", {}).get("momentum_signal", {}).get("risk_regime", "UNKNOWN")
                print(f"  Current live regime: {CYAN}{regime}{RESET}")
        print()


if __name__ == "__main__":
    main()
