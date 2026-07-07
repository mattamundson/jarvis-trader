"""
Vol-targeting uplift experiment (B1 study).

Measures whether volatility-targeted position sizing improves risk-adjusted
returns for the SMA-trend strategy on MGC, ZN, and ZB.

Methodology
-----------
1. Load the deepest available 1h cache CSV for each symbol from the main
   checkout cache directory (worktrees share the main cache).
2. Generate SMA-trend signals with champion params from contract_specs /
   trend_signals defaults.
3. Run Backtester with fixed sizing (1 contract) to get per-trade PnL.
4. Compute 20-bar annualized realized vol at each bar.
5. For each trade, look up rv at entry bar, compute weight
   w = clip(target_vol / rv_at_entry, 0.0, 3.0)  where target_vol = median
   of all entry-bar rv values.
6. Scale each trade PnL: vol_targeted_pnl = original_pnl * w
7. Compare Profit Factor, Sharpe, Max Drawdown, and trade count
   for fixed vs vol-targeted series.

Output
------
- Printed comparison table (stdout)
- Markdown report at engine/backtest/reports/vol_target_experiment.md

Rules
-----
- Read-only for backtester.py, trend_signals.py, run_trend_diversifier.py,
  contract_specs.py, and all risk/ files. This script is new; it imports
  them but never edits them.
- Do NOT commit or push anything.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import NamedTuple

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Path bootstrap — resolve engine root so imports work from any cwd
# ---------------------------------------------------------------------------
_ENGINE_ROOT = Path(__file__).parent.parent
_MAIN_CACHE = (
    _ENGINE_ROOT.parent.parent.parent.parent
    / "engine"
    / "backtest"
    / "cache"
)
# Fallback: local cache (worktree case where local cache is populated)
_LOCAL_CACHE = _ENGINE_ROOT / "backtest" / "cache"

if str(_ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_ENGINE_ROOT))

from backtest.contract_specs import get_spec  # noqa: E402
from backtest.trend_signals import SMA_TREND_PARAMS, generate_sma_trend_signals  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SYMBOLS = ["MGC", "ZN", "ZB"]

# Vol-targeting parameters
_RV_WINDOW = 20          # bars for realized vol calculation
_RV_ANNUAL_FACTOR = 252 * 24  # 1h bars per year
_MAX_LEVERAGE = 3.0      # clip weight ceiling

# Backtester params (matches run_trend_diversifier defaults)
_CAPITAL = 50_000.0
_RISK_PER_TRADE = 0.01
_MAX_DAILY_LOSS = 0.02
_MAX_DRAWDOWN = 0.05
_T1_EXIT_PCT = 0.50
_T2_EXIT_PCT = 0.30


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------

def _find_cache_file(symbol: str) -> Path | None:
    """Return the deepest (latest end-date) 1h cache file for symbol."""
    pattern = f"{symbol.upper()}_*_1h.csv"
    candidates: list[Path] = []
    for cache_dir in (_MAIN_CACHE, _LOCAL_CACHE):
        if cache_dir.exists():
            candidates.extend(cache_dir.glob(pattern))
    if not candidates:
        return None
    # Sort by the end-date segment (parts[2] of stem), pick max
    def _end_date_key(p: Path) -> str:
        parts = p.stem.split("_")
        # stem: SYMBOL_YYYY-MM-DD_YYYY-MM-DD_1h => parts[2] is end-date
        return parts[2] if len(parts) >= 3 else ""

    return max(candidates, key=_end_date_key)


def _load_df(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    ts_col = "timestamp" if "timestamp" in df.columns else "datetime"
    df[ts_col] = pd.to_datetime(df[ts_col])
    df = df.set_index(ts_col).sort_index()
    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns in {path.name}: {missing}")
    return df


# ---------------------------------------------------------------------------
# Signal generation
# ---------------------------------------------------------------------------

def _get_params(symbol: str) -> dict:
    """Champion params from SMA_TREND_PARAMS, else safe defaults."""
    sym = symbol.upper()
    if sym in SMA_TREND_PARAMS:
        return SMA_TREND_PARAMS[sym]
    # B1 diversifiers (ZN/ZB) use the proven MGC default grid center
    return {"fast": 50, "slow": 120, "atr_trail_mult": 2.0}


# ---------------------------------------------------------------------------
# Backtester runner
# ---------------------------------------------------------------------------

def _run_backtest(df_sig: pd.DataFrame, symbol: str) -> object:
    """Run Backtester with fixed_contracts=1 to isolate signal PnL."""
    from backtest.backtester import Backtester  # noqa: PLC0415

    spec = get_spec(symbol)
    bt = Backtester(
        initial_capital=_CAPITAL,
        risk_per_trade=_RISK_PER_TRADE,
        max_daily_loss=_MAX_DAILY_LOSS,
        max_drawdown=_MAX_DRAWDOWN,
        t1_exit_pct=_T1_EXIT_PCT,
        t2_exit_pct=_T2_EXIT_PCT,
        commission_per_contract=spec.commission,
        slippage_ticks=float(spec.slippage_ticks),
        fixed_contracts=1,  # equal-weight basis; vol-targeting applied in post
    )
    return bt.run(df_sig, symbol=symbol, multiplier=spec.multiplier)


# ---------------------------------------------------------------------------
# Vol-targeting core logic
# ---------------------------------------------------------------------------

def compute_rv_series(df: pd.DataFrame) -> pd.Series:
    """20-bar annualized realized vol (%) at each bar — matches trend_signals."""
    log_ret = np.log(df["close"] / df["close"].shift(1))
    rv = log_ret.rolling(_RV_WINDOW).std() * np.sqrt(_RV_ANNUAL_FACTOR) * 100.0
    return rv


def apply_vol_targeting(
    trades: list,
    df: pd.DataFrame,
    rv_series: pd.Series,
    max_leverage: float = _MAX_LEVERAGE,
) -> tuple[list[float], list[float], float]:
    """Compute fixed and vol-targeted PnL series and target_vol.

    Returns (fixed_pnl, vt_pnl, target_vol).
    """
    entry_dates = [t.entry_date for t in trades]
    rv_at_entries = []
    for ed in entry_dates:
        # Find nearest rv value at or before entry timestamp
        valid = rv_series[rv_series.index <= ed].dropna()
        if valid.empty:
            rv_at_entries.append(np.nan)
        else:
            rv_at_entries.append(float(valid.iloc[-1]))

    rv_arr = np.array(rv_at_entries, dtype=float)
    valid_mask = np.isfinite(rv_arr) & (rv_arr > 0)

    # target_vol = median of rv values at all entry bars (finite only)
    target_vol = float(np.median(rv_arr[valid_mask])) if valid_mask.any() else 1.0

    fixed_pnl = [float(t.pnl) for t in trades]
    vt_pnl = []
    for trade, rv_i in zip(trades, rv_arr, strict=True):
        if np.isfinite(rv_i) and rv_i > 0:
            w = float(np.clip(target_vol / rv_i, 0.0, max_leverage))
        else:
            w = 1.0  # no vol info → passthrough
        vt_pnl.append(float(trade.pnl) * w)

    return fixed_pnl, vt_pnl, target_vol


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

class SeriesMetrics(NamedTuple):
    n_trades: int
    profit_factor: float
    sharpe: float
    max_dd: float  # in dollars


def _profit_factor(pnl: list[float]) -> float:
    gross_profit = sum(p for p in pnl if p > 0)
    gross_loss = abs(sum(p for p in pnl if p < 0))
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def _annualized_sharpe(pnl: list[float], date_range_days: float) -> float:
    """Annualized Sharpe via per-trade series."""
    arr = np.array(pnl)
    n = len(arr)
    if n < 2:
        return 0.0
    std = float(np.std(arr, ddof=1))
    if std == 0:
        return 0.0
    trades_per_year = n / max(date_range_days / 365.25, 1e-6)
    return float(np.mean(arr) / std * np.sqrt(trades_per_year))


def _max_drawdown(pnl: list[float]) -> float:
    """Peak-to-trough in cumulative PnL (dollars, positive number = loss)."""
    cum = np.cumsum(pnl)
    peak = np.maximum.accumulate(cum)
    drawdowns = peak - cum
    return float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0


def compute_metrics(pnl: list[float], date_range_days: float) -> SeriesMetrics:
    return SeriesMetrics(
        n_trades=len(pnl),
        profit_factor=_profit_factor(pnl),
        sharpe=_annualized_sharpe(pnl, date_range_days),
        max_dd=_max_drawdown(pnl),
    )


# ---------------------------------------------------------------------------
# Per-symbol experiment
# ---------------------------------------------------------------------------

class SymbolResult(NamedTuple):
    symbol: str
    cache_file: str
    date_range_days: float
    target_vol: float
    fixed: SeriesMetrics
    vt: SeriesMetrics


def run_symbol(symbol: str) -> SymbolResult | None:
    cache_path = _find_cache_file(symbol)
    if cache_path is None:
        print(f"[{symbol}] AWAITING DATA -- no 1h cache found. Skipping.")
        return None

    print(f"[{symbol}] Loading {cache_path.name} ...")
    df = _load_df(cache_path)
    print(f"[{symbol}] {len(df)} bars | {df.index.min().date()} -> {df.index.max().date()}")

    params = _get_params(symbol)
    print(f"[{symbol}] Signals: fast={params['fast']}, slow={params['slow']}, atr_trail_mult={params['atr_trail_mult']}")

    df_sig = generate_sma_trend_signals(
        df,
        fast=params["fast"],
        slow=params["slow"],
        atr_trail_mult=params["atr_trail_mult"],
        min_rv_annualized=0.0,
    )

    result = _run_backtest(df_sig, symbol)
    trades = result.trades
    print(f"[{symbol}] {len(trades)} completed trades")

    if not trades:
        print(f"[{symbol}] No trades -- skipping.")
        return None

    rv_series = compute_rv_series(df)
    fixed_pnl, vt_pnl, target_vol = apply_vol_targeting(trades, df, rv_series)

    date_range_days = (df.index.max() - df.index.min()).days

    return SymbolResult(
        symbol=symbol,
        cache_file=cache_path.name,
        date_range_days=float(date_range_days),
        target_vol=target_vol,
        fixed=compute_metrics(fixed_pnl, date_range_days),
        vt=compute_metrics(vt_pnl, date_range_days),
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

_HDR = (
    f"{'Symbol':<6} {'Mode':<10} {'Trades':>7} {'PF':>6} {'Sharpe':>7} "
    f"{'MaxDD $':>9}"
)
_SEP = "-" * len(_HDR)


def _row(sym: str, label: str, m: SeriesMetrics) -> str:
    pf_str = f"{m.profit_factor:.3f}" if m.profit_factor != float("inf") else "  inf"
    return (
        f"{sym:<6} {label:<10} {m.n_trades:>7} {pf_str:>6} "
        f"{m.sharpe:>7.3f} {m.max_dd:>9,.0f}"
    )


def print_table(results: list[SymbolResult]) -> None:
    print()
    print("=" * len(_HDR))
    print("VOL-TARGETING UPLIFT EXPERIMENT — SMA TREND STRATEGY")
    print("=" * len(_HDR))
    print(_HDR)
    print(_SEP)
    for r in results:
        print(_row(r.symbol, "fixed", r.fixed))
        print(_row(r.symbol, "vol-target", r.vt))
        print(_SEP)


def _pf_delta(r: SymbolResult) -> str:
    f = r.fixed.profit_factor
    v = r.vt.profit_factor
    if f in (float("inf"), float("-inf")) or v in (float("inf"), float("-inf")):
        return "n/a"
    return f"{(v - f):+.3f}"


def write_markdown_report(results: list[SymbolResult], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Vol-Targeting Uplift Experiment — SMA Trend Strategy",
        "",
        "Compares fixed-size (1 contract) vs vol-targeted position sizing on the",
        "SMA-trend strategy. Weight = clip(target_vol / rv_at_entry, 0, 3); target_vol",
        "= median realized-vol at all entry bars for the symbol.",
        "",
        "## Results",
        "",
        f"| {'Symbol'} | {'Mode'} | {'Trades'} | {'PF'} | {'Sharpe'} | {'MaxDD $'} |",
        "|--------|----------|--------|-------|--------|---------|",
    ]
    for r in results:
        for label, m in [("fixed", r.fixed), ("vol-target", r.vt)]:
            pf = f"{m.profit_factor:.3f}" if m.profit_factor != float("inf") else "inf"
            lines.append(
                f"| {r.symbol} | {label} | {m.n_trades} | {pf} | "
                f"{m.sharpe:.3f} | {m.max_dd:,.0f} |"
            )

    lines += [
        "",
        "## Symbol metadata",
        "",
    ]
    for r in results:
        spec = get_spec(r.symbol)
        lines += [
            f"**{r.symbol}**: `{r.cache_file}` | {r.date_range_days:.0f} days | "
            f"multiplier={spec.multiplier} | target_vol={r.target_vol:.2f}%  ",
        ]
        pf_d = _pf_delta(r)
        sh_d = r.vt.sharpe - r.fixed.sharpe
        dd_d = r.vt.max_dd - r.fixed.max_dd
        lines.append(
            f"  Delta: PF {pf_d}, Sharpe {sh_d:+.3f}, MaxDD ${dd_d:+,.0f}"
        )
        lines.append("")

    # Verdict
    pf_improves = sum(
        1 for r in results
        if r.vt.profit_factor != float("inf")
        and r.fixed.profit_factor != float("inf")
        and r.vt.profit_factor > r.fixed.profit_factor
    )
    sh_improves = sum(1 for r in results if r.vt.sharpe > r.fixed.sharpe)
    dd_improves = sum(1 for r in results if r.vt.max_dd < r.fixed.max_dd)
    n = len(results)

    lines += [
        "## Verdict",
        "",
        f"Vol-targeting improved Profit Factor in {pf_improves}/{n} symbols, "
        f"Sharpe in {sh_improves}/{n}, and reduced MaxDD in {dd_improves}/{n}.",
        f"Consistent improvement across all three metrics requires {n}/{n} in each row.",
        (
            "**Recommendation: PURSUE further development**"
            if (pf_improves + sh_improves + dd_improves) >= n * 2
            else "**Recommendation: MIXED signal -- do not promote to production without deeper WFO study**"
        ),
        "",
    ]

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport written -> {out_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    results: list[SymbolResult] = []
    for sym in SYMBOLS:
        r = run_symbol(sym)
        if r is not None:
            results.append(r)

    if not results:
        print("No results to report -- all symbols missing data.")
        return

    print_table(results)

    report_path = _ENGINE_ROOT / "backtest" / "reports" / "vol_target_experiment.md"
    write_markdown_report(results, report_path)

    # Print final 3-line verdict to stdout
    pf_improves = sum(
        1 for r in results
        if r.vt.profit_factor != float("inf")
        and r.fixed.profit_factor != float("inf")
        and r.vt.profit_factor > r.fixed.profit_factor
    )
    sh_improves = sum(1 for r in results if r.vt.sharpe > r.fixed.sharpe)
    dd_improves = sum(1 for r in results if r.vt.max_dd < r.fixed.max_dd)
    n = len(results)
    print()
    print("=== 3-LINE VERDICT ===")
    print(f"  PF improved: {pf_improves}/{n}  |  Sharpe improved: {sh_improves}/{n}  |  MaxDD reduced: {dd_improves}/{n}")
    total_score = pf_improves + sh_improves + dd_improves
    if total_score >= n * 2:
        print("  Vol-targeting shows consistent uplift -- worth pursuing in WFO gating study.")
    elif total_score >= n:
        print("  Vol-targeting shows mixed uplift -- promising but needs deeper WFO validation.")
    else:
        print("  Vol-targeting shows weak or negative uplift -- do not promote to production.")


if __name__ == "__main__":
    main()
