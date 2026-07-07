"""
Walk-forward vol-targeting validation (MGC / MES trend PASSes).

Closes the in-sample lookahead in ``vol_target_experiment.py``. That experiment
estimated a single GLOBAL ``target_vol`` (median realized-vol over *every* entry
bar in the whole sample) and applied it to every trade — so the reported uplift
silently used future information to set the sizing scale.

This module instead estimates ``target_vol`` on each train window and applies it
ONLY to the immediately-following, disjoint out-of-sample test window. OOS trades
are pooled across windows for an honest risk-adjusted comparison, and the same
fixed-vs-vol-targeted contrast is reported in-sample alongside OOS so the size of
the lookahead is visible.

Design notes
------------
- Vol-targeting is a *sizing overlay*: it never changes which trades the signal
  takes, only how much each trade's PnL is weighted. So the trade list is
  generated once over the full series (via the experiment's helpers) and trades
  are partitioned into train/test windows by ``entry_date``. The only quantity
  estimated per window is the scalar ``target_vol`` — which cleanly isolates the
  lookahead this study removes.
- Test windows are DISJOINT (step == test_months), so each post-warmup trade is
  scored out-of-sample exactly once; no double counting when pooling.
- Trades inside the very first train-only period are never out-of-sample and are
  excluded from the OOS metrics (correct — they have no prior window to set a
  target_vol from).

Rules
-----
- Read-only for backtester.py, trend_signals.py, contract_specs.py, risk/. This
  module is new; it imports them and the sibling ``vol_target_experiment`` but
  never edits them.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import NamedTuple, Sequence

import numpy as np
import pandas as pd

_ENGINE_ROOT = Path(__file__).parent.parent
if str(_ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_ENGINE_ROOT))

from backtest.trend_signals import generate_sma_trend_signals  # noqa: E402
from backtest.vol_target_experiment import (  # noqa: E402
    _MAX_LEVERAGE,
    SeriesMetrics,
    _find_cache_file,
    _get_params,
    _load_df,
    _run_backtest,
    compute_metrics,
    compute_rv_series,
)

# ---------------------------------------------------------------------------
# Walk-forward configuration (matches run_trend_diversifier window cadence)
# ---------------------------------------------------------------------------
TRAIN_MONTHS = 6
TEST_MONTHS = 2          # step == test_months => disjoint OOS tiling
MIN_TRAIN_TRADES = 3     # need a few trades to estimate a stable median target_vol

SYMBOLS = ["MGC", "MES"]  # the two live trend PASSes (deepest caches, enough trades)


# ---------------------------------------------------------------------------
# Per-trade realized-vol lookup
# ---------------------------------------------------------------------------

def rv_at_entries(trades: Sequence, rv_series: pd.Series) -> np.ndarray:
    """Realized vol (%) at or before each trade's entry timestamp.

    Mirrors ``vol_target_experiment.apply_vol_targeting`` but returns the raw
    per-trade rv array so the walk-forward layer can partition by window.
    """
    out: list[float] = []
    for t in trades:
        valid = rv_series[rv_series.index <= t.entry_date].dropna()
        out.append(float(valid.iloc[-1]) if not valid.empty else np.nan)
    return np.asarray(out, dtype=float)


# ---------------------------------------------------------------------------
# Window generation
# ---------------------------------------------------------------------------

class Window(NamedTuple):
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp


def generate_windows(
    t_start: pd.Timestamp,
    t_end: pd.Timestamp,
    train_months: int = TRAIN_MONTHS,
    test_months: int = TEST_MONTHS,
) -> list[Window]:
    """Disjoint walk-forward windows tiling [t_start, t_end].

    Each window: train = [cursor, cursor+train), test = [cursor+train,
    cursor+train+test). Cursor advances by ``test_months`` so consecutive test
    periods are contiguous and non-overlapping. A window is emitted only while
    its test period actually starts before ``t_end``.
    """
    windows: list[Window] = []
    cursor = t_start
    while True:
        train_start = cursor
        train_end = train_start + pd.DateOffset(months=train_months)
        test_start = train_end
        test_end = test_start + pd.DateOffset(months=test_months)
        if test_start >= t_end:
            break
        windows.append(Window(train_start, train_end, test_start, test_end))
        cursor = cursor + pd.DateOffset(months=test_months)
    return windows


# ---------------------------------------------------------------------------
# Walk-forward vol-targeting
# ---------------------------------------------------------------------------

class WindowRecord(NamedTuple):
    idx: int
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    n_test_trades: int
    target_vol: float
    fixed_sharpe: float
    vt_sharpe: float


class WFOResult(NamedTuple):
    pooled_fixed_pnl: list[float]
    pooled_vt_pnl: list[float]
    oos_span_days: float
    windows: list[WindowRecord]
    n_windows_used: int


def _weight(target_vol: float, rv: float, max_leverage: float) -> float:
    if np.isfinite(rv) and rv > 0 and np.isfinite(target_vol) and target_vol > 0:
        return float(np.clip(target_vol / rv, 0.0, max_leverage))
    return 1.0  # no vol info => passthrough


def walk_forward_vol_target(
    trades: Sequence,
    rv_entries: np.ndarray,
    train_months: int = TRAIN_MONTHS,
    test_months: int = TEST_MONTHS,
    min_train_trades: int = MIN_TRAIN_TRADES,
    max_leverage: float = _MAX_LEVERAGE,
) -> WFOResult:
    """Estimate target_vol per train window; weight OOS trades; pool OOS.

    target_vol for a window = median rv over trades whose entry falls in the
    window's TRAIN period (in-sample only). Each OOS trade is weighted
    w = clip(target_vol / rv_at_entry, 0, max_leverage). OOS trades are pooled
    across all windows (disjoint test periods => no double counting).
    """
    if len(trades) != len(rv_entries):
        raise ValueError("trades and rv_entries length mismatch")

    entry_dates = np.array([t.entry_date for t in trades])
    pnls = np.array([float(t.pnl) for t in trades])
    if len(entry_dates) == 0:
        return WFOResult([], [], 0.0, [], 0)

    t_start = pd.Timestamp(min(entry_dates))
    t_end = pd.Timestamp(max(entry_dates))
    windows = generate_windows(t_start, t_end, train_months, test_months)

    pooled_fixed: list[float] = []
    pooled_vt: list[float] = []
    records: list[WindowRecord] = []
    n_used = 0

    for i, w in enumerate(windows):
        train_mask = np.array(
            [w.train_start <= pd.Timestamp(d) < w.train_end for d in entry_dates]
        )
        test_mask = np.array(
            [w.test_start <= pd.Timestamp(d) < w.test_end for d in entry_dates]
        )

        train_rv = rv_entries[train_mask]
        train_rv = train_rv[np.isfinite(train_rv) & (train_rv > 0)]
        if train_rv.size < min_train_trades:
            # not enough in-sample trades to set a stable target_vol; skip OOS
            continue
        target_vol = float(np.median(train_rv))

        test_idx = np.flatnonzero(test_mask)
        if test_idx.size == 0:
            continue

        win_fixed: list[float] = []
        win_vt: list[float] = []
        for j in test_idx:
            w_j = _weight(target_vol, rv_entries[j], max_leverage)
            win_fixed.append(float(pnls[j]))
            win_vt.append(float(pnls[j]) * w_j)

        pooled_fixed.extend(win_fixed)
        pooled_vt.extend(win_vt)
        n_used += 1

        # per-window Sharpe (small-sample, secondary robustness signal only)
        win_days = max((w.test_end - w.test_start).days, 1)
        records.append(
            WindowRecord(
                idx=i,
                test_start=w.test_start,
                test_end=w.test_end,
                n_test_trades=test_idx.size,
                target_vol=target_vol,
                fixed_sharpe=compute_metrics(win_fixed, win_days).sharpe,
                vt_sharpe=compute_metrics(win_vt, win_days).sharpe,
            )
        )

    if records:
        oos_span = (records[-1].test_end - records[0].test_start).days
    else:
        oos_span = 0
    return WFOResult(pooled_fixed, pooled_vt, float(oos_span), records, n_used)


# ---------------------------------------------------------------------------
# Per-symbol driver
# ---------------------------------------------------------------------------

class SymbolWFO(NamedTuple):
    symbol: str
    cache_file: str
    n_trades_total: int
    # In-sample (global target_vol) — the vol_target_experiment lookahead baseline
    is_fixed: SeriesMetrics
    is_vt: SeriesMetrics
    is_target_vol: float
    # Out-of-sample (walk-forward) — the honest result
    oos_fixed: SeriesMetrics
    oos_vt: SeriesMetrics
    n_windows_used: int
    windows: list[WindowRecord]


def _global_target_vol(rv_entries: np.ndarray) -> float:
    valid = rv_entries[np.isfinite(rv_entries) & (rv_entries > 0)]
    return float(np.median(valid)) if valid.size else 1.0


def run_symbol_wfo(symbol: str) -> SymbolWFO | None:
    cache_path = _find_cache_file(symbol)
    if cache_path is None:
        print(f"[{symbol}] AWAITING DATA -- no 1h cache found. Skipping.")
        return None

    df = _load_df(cache_path)
    params = _get_params(symbol)
    print(
        f"[{symbol}] {len(df)} bars | {df.index.min().date()} -> {df.index.max().date()} "
        f"| fast={params['fast']} slow={params['slow']} atr={params['atr_trail_mult']}"
    )

    df_sig = generate_sma_trend_signals(
        df,
        fast=params["fast"],
        slow=params["slow"],
        atr_trail_mult=params["atr_trail_mult"],
        min_rv_annualized=0.0,
    )
    result = _run_backtest(df_sig, symbol)
    trades = result.trades
    if not trades:
        print(f"[{symbol}] No trades -- skipping.")
        return None

    rv_series = compute_rv_series(df)
    rv_entries = rv_at_entries(trades, rv_series)
    full_days = max((df.index.max() - df.index.min()).days, 1)

    # In-sample (global target_vol) — reproduce the experiment's lookahead figure
    g_target = _global_target_vol(rv_entries)
    is_fixed_pnl = [float(t.pnl) for t in trades]
    is_vt_pnl = [
        float(t.pnl) * _weight(g_target, rv, _MAX_LEVERAGE)
        for t, rv in zip(trades, rv_entries, strict=True)
    ]

    # Out-of-sample (walk-forward)
    wfo = walk_forward_vol_target(trades, rv_entries)

    if wfo.n_windows_used == 0:
        print(f"[{symbol}] Not enough data to form OOS windows -- skipping.")
        return None

    return SymbolWFO(
        symbol=symbol,
        cache_file=cache_path.name,
        n_trades_total=len(trades),
        is_fixed=compute_metrics(is_fixed_pnl, full_days),
        is_vt=compute_metrics(is_vt_pnl, full_days),
        is_target_vol=g_target,
        oos_fixed=compute_metrics(wfo.pooled_fixed_pnl, wfo.oos_span_days),
        oos_vt=compute_metrics(wfo.pooled_vt_pnl, wfo.oos_span_days),
        n_windows_used=wfo.n_windows_used,
        windows=wfo.windows,
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _pf(m: SeriesMetrics) -> str:
    return f"{m.profit_factor:.3f}" if m.profit_factor != float("inf") else "inf"


def _verdict_for(r: SymbolWFO) -> str:
    """OOS uplift verdict.

    - ROBUST_OOS  : pooled Sharpe up AND MaxDD down AND vol-target beats fixed in
                    a MAJORITY of individual windows (the Sharpe edge is not an
                    artifact of pooling).
    - DAMPENS_DD  : MaxDD down but the Sharpe edge is weak/pool-driven (window
                    majority not met) — vol-targeting de-risks without a reliable
                    risk-adjusted-return gain (typical of a negative-expectancy
                    base strategy).
    - PARTIAL_OOS : exactly one of {pooled Sharpe up, MaxDD down} holds.
    - NOT_ROBUST_OOS : neither holds.
    """
    sharpe_up = r.oos_vt.sharpe > r.oos_fixed.sharpe
    dd_down = r.oos_vt.max_dd < r.oos_fixed.max_dd
    n_win = len(r.windows)
    win_majority = (
        n_win > 0 and sum(1 for w in r.windows if w.vt_sharpe > w.fixed_sharpe) * 2 >= n_win
    )
    if sharpe_up and dd_down and win_majority:
        return "ROBUST_OOS"
    if dd_down and not (sharpe_up and win_majority):
        return "DAMPENS_DD"
    if sharpe_up or dd_down:
        return "PARTIAL_OOS"
    return "NOT_ROBUST_OOS"


def write_report(results: list[SymbolWFO], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Walk-Forward Vol-Targeting Validation — MGC / MES Trend",
        "",
        "Closes the in-sample lookahead in `vol_target_experiment.py` (which set a",
        "single global `target_vol` over the whole sample). Here `target_vol` is",
        f"estimated on each {TRAIN_MONTHS}-month train window and applied only to the",
        f"following disjoint {TEST_MONTHS}-month out-of-sample window; OOS trades are",
        "pooled. The in-sample row reproduces the experiment's (lookahead) figure so",
        "the size of the inflation is visible.",
        "",
        "## Results (fixed vs vol-targeted)",
        "",
        "| Symbol | Basis | Trades | PF | Sharpe | MaxDD $ |",
        "|--------|-------|--------|----|--------|---------|",
    ]
    for r in results:
        lines.append(
            f"| {r.symbol} | in-sample fixed | {r.is_fixed.n_trades} | {_pf(r.is_fixed)} "
            f"| {r.is_fixed.sharpe:.3f} | {r.is_fixed.max_dd:,.0f} |"
        )
        lines.append(
            f"| {r.symbol} | in-sample vol-target | {r.is_vt.n_trades} | {_pf(r.is_vt)} "
            f"| {r.is_vt.sharpe:.3f} | {r.is_vt.max_dd:,.0f} |"
        )
        lines.append(
            f"| {r.symbol} | **OOS fixed** | {r.oos_fixed.n_trades} | {_pf(r.oos_fixed)} "
            f"| {r.oos_fixed.sharpe:.3f} | {r.oos_fixed.max_dd:,.0f} |"
        )
        lines.append(
            f"| {r.symbol} | **OOS vol-target** | {r.oos_vt.n_trades} | {_pf(r.oos_vt)} "
            f"| {r.oos_vt.sharpe:.3f} | {r.oos_vt.max_dd:,.0f} |"
        )

    lines += ["", "## Per-symbol detail", ""]
    for r in results:
        is_sh_d = r.is_vt.sharpe - r.is_fixed.sharpe
        oos_sh_d = r.oos_vt.sharpe - r.oos_fixed.sharpe
        oos_dd_d = r.oos_vt.max_dd - r.oos_fixed.max_dd
        win_better = sum(1 for w in r.windows if w.vt_sharpe > w.fixed_sharpe)
        lines += [
            f"**{r.symbol}** — `{r.cache_file}` | {r.n_trades_total} total trades | "
            f"{r.n_windows_used} OOS windows | global target_vol={r.is_target_vol:.2f}%  ",
            f"  In-sample Sharpe uplift: {is_sh_d:+.3f} (lookahead baseline)  ",
            f"  **OOS Sharpe uplift: {oos_sh_d:+.3f} | OOS MaxDD delta: ${oos_dd_d:+,.0f}**  ",
            f"  Per-window: vol-target Sharpe beat fixed in {win_better}/{len(r.windows)} windows  ",
            f"  Verdict: **{_verdict_for(r)}**",
            "",
        ]

    robust = [r.symbol for r in results if _verdict_for(r) == "ROBUST_OOS"]
    dampens = [r.symbol for r in results if _verdict_for(r) == "DAMPENS_DD"]
    lines += [
        "## Verdict",
        "",
        (
            f"Robust OOS risk-adjusted uplift (Sharpe up + MaxDD down + window "
            f"majority): {', '.join(robust) if robust else 'NONE'}."
        ),
        "",
        (
            f"Drawdown-dampening only (MaxDD down but no reliable Sharpe edge — "
            f"de-risks a weak/negative base strategy): {', '.join(dampens) if dampens else 'NONE'}."
        ),
        "",
        "Interpretation: if the OOS Sharpe uplift is close to (or above) the in-sample",
        "uplift, the vol_target_experiment finding was not a lookahead artifact and",
        "supports a formal live-sizer decision (owner-gated, safety-review). A large gap",
        "between in-sample and OOS uplift would indicate the global-target_vol figure was",
        "inflated.",
        "",
        "## Caveats",
        "",
        "- **Sizing overlay only.** Vol-targeting reweights the per-trade PnL of the",
        "  existing fixed-1-contract Backtester run; it does NOT change entry/exit signals",
        "  and touches no `risk/` or Backtester code. It cannot manufacture edge — it only",
        "  rescales an existing return stream.",
        "- **MES row uses UNFILTERED trend** (`min_rv_annualized=0`), which is",
        "  negative-expectancy on this 2yr sample. The live MES trend PASS uses the",
        "  realized-vol filter (`MES_MIN_RV_ANNUALIZED=9.0`). MES here is therefore a",
        "  control showing vol-targeting dampens losses without creating edge — NOT the",
        "  live MES configuration.",
        "- **MGC uses its champion params** (fast=50, slow=120, atr=2.0) — the figures",
        "  apply directly to the live MGC trend edge.",
        "- Next step is a formal gate-v2 study + a live-sizer wiring decision; both are",
        "  owner-gated (safety-review). This module is offline measurement only.",
        "",
    ]
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport written -> {out_path}")


def print_table(results: list[SymbolWFO]) -> None:
    print()
    print("=" * 62)
    print("WALK-FORWARD VOL-TARGETING — IN-SAMPLE vs OUT-OF-SAMPLE")
    print("=" * 62)
    hdr = f"{'Symbol':<6} {'Basis':<20} {'N':>4} {'PF':>6} {'Sharpe':>7} {'MaxDD$':>9}"
    print(hdr)
    print("-" * len(hdr))
    for r in results:
        for label, m in [
            ("in-sample fixed", r.is_fixed),
            ("in-sample vol-target", r.is_vt),
            ("OOS fixed", r.oos_fixed),
            ("OOS vol-target", r.oos_vt),
        ]:
            print(
                f"{r.symbol:<6} {label:<20} {m.n_trades:>4} {_pf(m):>6} "
                f"{m.sharpe:>7.3f} {m.max_dd:>9,.0f}"
            )
        print("-" * len(hdr))
        print(f"       OOS verdict: {_verdict_for(r)}  ({r.n_windows_used} windows)")
        print("-" * len(hdr))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    results: list[SymbolWFO] = []
    for sym in SYMBOLS:
        r = run_symbol_wfo(sym)
        if r is not None:
            results.append(r)

    if not results:
        print("No results -- all symbols missing data or too few trades.")
        return

    print_table(results)
    report_path = _ENGINE_ROOT / "backtest" / "reports" / "vol_target_wfo.md"
    write_report(results, report_path)

    print("\n=== OOS VERDICT ===")
    for r in results:
        oos_sh_d = r.oos_vt.sharpe - r.oos_fixed.sharpe
        oos_dd_d = r.oos_vt.max_dd - r.oos_fixed.max_dd
        print(
            f"  {r.symbol}: {_verdict_for(r)} | OOS Sharpe {oos_sh_d:+.3f} | "
            f"OOS MaxDD ${oos_dd_d:+,.0f} | {r.n_windows_used} windows"
        )


if __name__ == "__main__":
    main()
