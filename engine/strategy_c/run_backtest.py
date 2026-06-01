"""
Strategy C+ Full Backtest Runner
=================================
Runs the backtest, generates the dashboard PNG, and saves all outputs.

Usage:
    python engine/strategy_c/run_backtest.py
    python engine/strategy_c/run_backtest.py --grid-search
    python engine/strategy_c/run_backtest.py --is-oos-only
"""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# Add project root to path for standalone execution
REPO_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from engine.strategy_c.engine import StrategyCConfig, StrategyCEngine  # noqa: E402

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# Dark theme constants (matches jarvis-trader dashboard aesthetic)
# ─────────────────────────────────────────────────────────────────────────────
DARK_BG   = "#0e1117"
PANEL_BG  = "#161b22"
GOLD      = "#d4a843"
TEAL      = "#4ecdc4"
RED       = "#e05c5c"
GREEN     = "#4caf7d"
GRAY      = "#888888"
WHITE     = "#e8e8e8"
BLUE      = "#5b9bd5"
ORANGE    = "#f0a500"
PURPLE    = "#9b59b6"
IS_COLOR  = "#1a3a5c"
OOS_COLOR = "#1a4a2e"


def run_full_backtest_and_dashboard(config: StrategyCConfig | None = None) -> dict:
    """
    Run the full Strategy C+ backtest and generate the comprehensive dashboard.
    """
    config = config or StrategyCConfig()
    engine = StrategyCEngine(config=config)

    print("[Strategy C+] Starting full backtest...")
    results = engine.run_backtest(save_results=True)

    print("[Strategy C+] Generating dashboard...")
    fig = build_dashboard(results, engine)

    dashboard_path = OUTPUT_DIR / "strategy_c_plus_dashboard.png"
    fig.savefig(dashboard_path, dpi=150, bbox_inches="tight",
                facecolor=DARK_BG, edgecolor="none")
    plt.close(fig)
    print(f"[Strategy C+] Dashboard → {dashboard_path}")

    return results


def build_dashboard(results: dict, engine: StrategyCEngine) -> plt.Figure:
    """Build the comprehensive multi-panel dashboard."""

    equity = results["equity_curve"]
    spy = results["spy_benchmark"]
    alloc = results["allocation_log"]
    vol_df = results["vol_df"]
    vix_mult = results["vix_multiplier"]
    macro_mult = results["macro_multiplier"]
    full = results["full_metrics"]
    is_m = results["is_metrics"]
    oos_m = results["oos_metrics"]
    retention = results["oos_retention"]
    dsr = results["deflated_sharpe"]
    vol_stats = results["vol_stats"]

    # ─────────────────────────────────────────────────────────────────────────
    # Layout: 4 rows × 3 cols
    # ─────────────────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(20, 24), facecolor=DARK_BG)
    fig.patch.set_facecolor(DARK_BG)

    gs = gridspec.GridSpec(
        5, 3, figure=fig,
        hspace=0.45, wspace=0.35,
        left=0.06, right=0.97, top=0.95, bottom=0.04
    )

    # ── Title ────────────────────────────────────────────────────────────────
    fig.text(
        0.5, 0.975,
        "STRATEGY C+  |  Enhanced Regime Rotation",
        ha="center", va="center",
        fontsize=22, fontweight="bold", color=GOLD,
        fontfamily="monospace"
    )
    fig.text(
        0.5, 0.963,
        "Dual Momentum × ES/NQ Vol-Targeting × 4-Component VIX × FRED Macro × Factor Tilts",
        ha="center", va="center",
        fontsize=11, color=GRAY
    )

    # ── Panel 1 (row 0, full width): Equity Curve ────────────────────────────
    ax1 = fig.add_subplot(gs[0, :])
    _plot_equity_curve(ax1, equity, spy, results)

    # ── Panel 2 (row 1, col 0): IS/OOS Metrics Table ─────────────────────────
    ax2 = fig.add_subplot(gs[1, 0])
    _plot_metrics_table(ax2, full, is_m, oos_m, retention)

    # ── Panel 3 (row 1, col 1): Drawdown ─────────────────────────────────────
    ax3 = fig.add_subplot(gs[1, 1])
    _plot_drawdown(ax3, equity, spy)

    # ── Panel 4 (row 1, col 2): Annual Returns ───────────────────────────────
    ax4 = fig.add_subplot(gs[1, 2])
    _plot_annual_returns(ax4, equity, spy)

    # ── Panel 5 (row 2, col 0-1): Vol Scale + VIX Composite ──────────────────
    ax5 = fig.add_subplot(gs[2, :2])
    _plot_signal_layers(ax5, vol_df, vix_mult, macro_mult)

    # ── Panel 6 (row 2, col 2): Rolling Sharpe ───────────────────────────────
    ax6 = fig.add_subplot(gs[2, 2])
    _plot_rolling_sharpe(ax6, equity, spy)

    # ── Panel 7 (row 3, full width): Asset Allocation Timeline ───────────────
    ax7 = fig.add_subplot(gs[3, :])
    _plot_allocation_timeline(ax7, alloc)

    # ── Panel 8 (row 4, col 0): Vol Regime Distribution ──────────────────────
    ax8 = fig.add_subplot(gs[4, 0])
    _plot_vol_regime_dist(ax8, vol_df)

    # ── Panel 9 (row 4, col 1): Return Distribution ──────────────────────────
    ax9 = fig.add_subplot(gs[4, 1])
    _plot_return_distribution(ax9, equity, spy)

    # ── Panel 10 (row 4, col 2): DSR + Stats Card ────────────────────────────
    ax10 = fig.add_subplot(gs[4, 2])
    _plot_validation_card(ax10, dsr, vol_stats, full)

    return fig


# ─────────────────────────────────────────────────────────────────────────────
# Panel Builders
# ─────────────────────────────────────────────────────────────────────────────

def _style_ax(ax, title: str = "", xlabel: str = "", ylabel: str = "") -> None:
    ax.set_facecolor(PANEL_BG)
    ax.tick_params(colors=GRAY, labelsize=8)
    ax.spines[:].set_color("#333333")
    if title:
        ax.set_title(title, color=WHITE, fontsize=10, fontweight="bold", pad=8)
    if xlabel:
        ax.set_xlabel(xlabel, color=GRAY, fontsize=8)
    if ylabel:
        ax.set_ylabel(ylabel, color=GRAY, fontsize=8)
    ax.xaxis.label.set_color(GRAY)
    ax.yaxis.label.set_color(GRAY)


def _plot_equity_curve(ax, equity, spy, results):
    _style_ax(ax, "Equity Curve — Strategy C+ vs SPY Buy-and-Hold", ylabel="Portfolio Value ($)")

    # IS/OOS shading
    is_end = pd.Timestamp("2021-04-30")
    ax.axvspan(equity.index[0], is_end, alpha=0.08, color=BLUE, label="In-Sample")
    ax.axvspan(is_end, equity.index[-1], alpha=0.06, color=GREEN, label="Out-of-Sample")
    ax.axvline(is_end, color=BLUE, alpha=0.4, lw=1, ls="--")

    initial = equity.iloc[0]
    ax.plot(equity.index, equity / initial * 100, color=GOLD, lw=2.0,
            label=f"Strategy C+ ({results['full_metrics'].get('final_multiple_x', 0):.2f}x)", zorder=5)

    if spy is not None:
        ax.plot(spy.index, spy / spy.iloc[0] * 100, color=GRAY, lw=1.2,
                alpha=0.7, label=f"SPY B&H ({spy.iloc[-1]/spy.iloc[0]:.2f}x)", zorder=4)

    ax.set_ylabel("Growth (Base=100)", color=GRAY, fontsize=8)
    ax.legend(loc="upper left", fontsize=8, framealpha=0.15, labelcolor=WHITE)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:.0f}"))

    # Annotate key stats
    fm = results["full_metrics"]
    stats_text = (
        f"CAGR {fm.get('cagr', 0):.1f}%  |  "
        f"Sharpe {fm.get('sharpe', 0):.2f}  |  "
        f"Vol {fm.get('ann_vol', 0):.1f}%  |  "
        f"MDD {fm.get('max_dd_close_pct', 0):.1f}%  |  "
        f"Win% {fm.get('win_rate_pct', 0):.0f}%"
    )
    ax.text(0.5, 0.04, stats_text, transform=ax.transAxes,
            ha="center", va="bottom", fontsize=9, color=GOLD, fontfamily="monospace")


def _plot_metrics_table(ax, full, is_m, oos_m, retention):
    ax.set_facecolor(PANEL_BG)
    ax.axis("off")
    ax.set_title("Performance Summary", color=WHITE, fontsize=10, fontweight="bold", pad=8)

    def fmt_row(label, full_v, is_v, oos_v, fmt="{:.2f}"):
        return [label, fmt.format(full_v) if full_v is not None else "-",
                fmt.format(is_v) if is_v is not None else "-",
                fmt.format(oos_v) if oos_v is not None else "-"]

    rows = [
        ["Metric", "Full", "IS", "OOS"],
        fmt_row("CAGR %", full.get("cagr"), is_m.get("cagr"), oos_m.get("cagr")),
        fmt_row("Sharpe", full.get("sharpe"), is_m.get("sharpe"), oos_m.get("sharpe")),
        fmt_row("Sortino", full.get("sortino"), is_m.get("sortino"), oos_m.get("sortino")),
        fmt_row("Vol %", full.get("ann_vol"), is_m.get("ann_vol"), oos_m.get("ann_vol")),
        fmt_row("MDD %", full.get("max_dd_close_pct"), is_m.get("max_dd_close_pct"), oos_m.get("max_dd_close_pct")),
        fmt_row("Calmar", full.get("calmar"), is_m.get("calmar"), oos_m.get("calmar")),
        fmt_row("Win% ", full.get("win_rate_pct"), is_m.get("win_rate_pct"), oos_m.get("win_rate_pct"), "{:.0f}%"),
        fmt_row("EQ ×", full.get("final_multiple_x"), is_m.get("final_multiple_x"), oos_m.get("final_multiple_x")),
    ]

    if retention:
        rows.append(["──────────", "──────", "──────", "──────"])
        sr_ret = retention.get("sharpe_retention_pct", 0)
        cagr_ret = retention.get("cagr_retention_pct", 0)
        rows.append(["OOS Sharpe Ret", f"{sr_ret:.0f}%", "", ""])
        rows.append(["OOS CAGR Ret  ", f"{cagr_ret:.0f}%", "", ""])

    table = ax.table(
        cellText=rows[1:],
        colLabels=rows[0],
        loc="center",
        cellLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1.0, 1.4)

    for (row, _col), cell in table.get_celld().items():
        cell.set_facecolor(PANEL_BG if row % 2 == 0 else "#1c2330")
        cell.set_edgecolor("#333333")
        if row == 0:
            cell.set_text_props(color=GOLD, fontweight="bold")
        else:
            cell.set_text_props(color=WHITE)


def _plot_drawdown(ax, equity, spy):
    _style_ax(ax, "Drawdown", ylabel="Drawdown %")
    roll_max = equity.expanding().max()
    dd = (equity / roll_max - 1) * 100
    ax.fill_between(dd.index, dd, 0, color=RED, alpha=0.4)
    ax.plot(dd.index, dd, color=RED, lw=0.8)

    if spy is not None:
        spy_max = spy.expanding().max()
        spy_dd = (spy / spy_max - 1) * 100
        ax.plot(spy_dd.index, spy_dd, color=GRAY, lw=0.8, alpha=0.6, label="SPY MDD")

    ax.axhline(0, color=GRAY, lw=0.5)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:.0f}%"))


def _plot_annual_returns(ax, equity, spy):
    _style_ax(ax, "Annual Returns %", ylabel="Return %")
    annual = equity.resample("YE").last().pct_change().dropna() * 100
    colors = [GREEN if v >= 0 else RED for v in annual.values]
    ax.bar(annual.index.year, annual.values, color=colors, alpha=0.8, width=0.7)

    if spy is not None:
        spy_annual = spy.resample("YE").last().pct_change().dropna() * 100
        ax.plot(spy_annual.index.year, spy_annual.values,
                color=GRAY, marker="o", ms=4, lw=1, alpha=0.7, label="SPY")

    ax.axhline(0, color=GRAY, lw=0.5)
    ax.legend(fontsize=7, framealpha=0.1, labelcolor=WHITE)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:.0f}%"))


def _plot_signal_layers(ax, vol_df, vix_mult, macro_mult):
    _style_ax(ax, "Signal Layer Stack — Vol Scale × VIX Composite × Macro Filter",
              ylabel="Position Scale (0=cash, 1=full)")

    if vol_df is not None and "scale" in vol_df.columns:
        ax.fill_between(vol_df.index, vol_df["scale"], alpha=0.25, color=TEAL, label="Vol Scale")
        ax.plot(vol_df.index, vol_df["scale"], color=TEAL, lw=0.8)

    if vix_mult is not None:
        ax.fill_between(vix_mult.index, vix_mult.values, alpha=0.2, color=GOLD, label="VIX Composite")
        ax.plot(vix_mult.index, vix_mult.values, color=GOLD, lw=0.8)

    if macro_mult is not None:
        ax.plot(macro_mult.index, macro_mult.values, color=PURPLE, lw=0.8,
                alpha=0.7, ls="--", label="Macro Filter")

    # Combined
    if vol_df is not None and vix_mult is not None:
        vol_s = vol_df["scale"].reindex(vix_mult.index, method="ffill")
        macro_s = macro_mult.reindex(vix_mult.index, method="ffill") if macro_mult is not None else 1.0
        combined = vol_s * vix_mult * macro_s
        ax.plot(combined.index, combined.values, color=ORANGE, lw=1.5,
                label="Combined Scale", zorder=5)

    ax.axhline(1.0, color=GRAY, lw=0.5, ls="--")
    ax.axhline(0.5, color=RED, lw=0.5, ls="--", alpha=0.4)
    ax.set_ylim(-0.05, 1.15)
    ax.legend(loc="lower left", fontsize=7.5, framealpha=0.15, labelcolor=WHITE)


def _plot_rolling_sharpe(ax, equity, spy):
    _style_ax(ax, "Rolling 52-Week Sharpe", ylabel="Sharpe")
    returns = equity.pct_change()
    rolling_sharpe = returns.rolling(52).mean() / returns.rolling(52).std() * np.sqrt(52)
    ax.plot(rolling_sharpe.index, rolling_sharpe.values, color=GOLD, lw=1.2)

    if spy is not None:
        spy_ret = spy.pct_change()
        spy_roll = spy_ret.rolling(52).mean() / spy_ret.rolling(52).std() * np.sqrt(52)
        ax.plot(spy_roll.index, spy_roll.values, color=GRAY, lw=0.8, alpha=0.6, label="SPY")

    ax.axhline(0, color=GRAY, lw=0.5)
    ax.axhline(1.0, color=GREEN, lw=0.5, ls="--", alpha=0.4)
    ax.legend(fontsize=7, framealpha=0.1, labelcolor=WHITE)


def _plot_allocation_timeline(ax, alloc_df):
    _style_ax(ax, "Weekly Asset Allocation Timeline")
    if alloc_df is None or len(alloc_df) == 0:
        ax.text(0.5, 0.5, "No allocation data", ha="center", va="center",
                color=GRAY, transform=ax.transAxes)
        return

    # asset_colors palette retained inline below for the stacked-allocation
    # plot when wired (currently only the regime bands are rendered):
    # QQQ=TEAL SPY=BLUE EFA=PURPLE IEF=ORANGE SHY=GRAY USMV=GREEN MTUM=GOLD
    # XLK=#FF6B6B XLV=#45B7D1.

    # Parse holdings strings to compute stacked allocation
    risk_on_weeks = (alloc_df["risk_regime"] == "RISK_ON").sum()
    risk_off_weeks = (alloc_df["risk_regime"] == "RISK_OFF").sum()

    # Build regime color bands
    regime_colors = {"RISK_ON": "#1a3a1a", "RISK_OFF": "#3a1a1a",
                     "WARMUP": "#2a2a2a", "NO_SIGNAL": "#2a2a2a"}

    for i, (date, row) in enumerate(alloc_df.iterrows()):
        regime = row.get("risk_regime", "RISK_ON")
        color = regime_colors.get(regime, "#2a2a2a")
        if i < len(alloc_df) - 1:
            next_date = alloc_df.index[i + 1]
            ax.axvspan(date, next_date, alpha=0.3, color=color, linewidth=0)

    # Combined scale line
    if "combined_scale" in alloc_df.columns:
        ax.plot(alloc_df.index, alloc_df["combined_scale"],
                color=ORANGE, lw=1.2, label="Combined Scale", zorder=5)
    if "vol_scale" in alloc_df.columns:
        ax.plot(alloc_df.index, alloc_df["vol_scale"],
                color=TEAL, lw=0.8, alpha=0.7, label="Vol Scale")

    ax.axhline(1.0, color=GRAY, lw=0.5, ls="--")
    ax.set_ylim(-0.05, 1.2)
    ax.set_ylabel("Scale", color=GRAY, fontsize=8)

    # Legend labels
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor="#1a3a1a", alpha=0.3, label=f"RISK_ON ({risk_on_weeks}w)"),
        Patch(facecolor="#3a1a1a", alpha=0.3, label=f"RISK_OFF ({risk_off_weeks}w)"),
    ]
    ax.legend(handles=legend_elements + [
        plt.Line2D([0], [0], color=ORANGE, lw=1.2, label="Combined Scale"),
        plt.Line2D([0], [0], color=TEAL, lw=0.8, label="Vol Scale"),
    ], loc="lower left", fontsize=7.5, framealpha=0.15, labelcolor=WHITE)


def _plot_vol_regime_dist(ax, vol_df):
    _style_ax(ax, "Realized Vol Regime Distribution", ylabel="% of Weeks")
    if vol_df is None or "realized_vol" not in vol_df.columns:
        return

    rv = vol_df["realized_vol"]
    labels = ["CALM\n(<10%)", "NORMAL\n(10-18%)", "ELEVATED\n(18-30%)", "CRISIS\n(>30%)"]
    thresholds = [(0, 10), (10, 18), (18, 30), (30, 999)]
    colors = [TEAL, GREEN, ORANGE, RED]

    counts = [(rv.between(lo, hi)).mean() * 100 for lo, hi in thresholds]
    bars = ax.bar(labels, counts, color=colors, alpha=0.8)

    for bar, count in zip(bars, counts, strict=False):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                f"{count:.0f}%", ha="center", va="bottom", fontsize=7.5, color=WHITE)

    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:.0f}%"))


def _plot_return_distribution(ax, equity, spy):
    _style_ax(ax, "Weekly Return Distribution", xlabel="Weekly Return %", ylabel="Frequency")
    returns = equity.pct_change().dropna() * 100

    ax.hist(returns, bins=60, color=GOLD, alpha=0.7, density=True, label="Strategy C+")
    if spy is not None:
        spy_ret = spy.pct_change().dropna() * 100
        ax.hist(spy_ret, bins=60, color=GRAY, alpha=0.4, density=True, label="SPY")

    ax.axvline(0, color=WHITE, lw=0.5)
    ax.legend(fontsize=7.5, framealpha=0.1, labelcolor=WHITE)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:.0f}%"))


def _plot_validation_card(ax, dsr, vol_stats, full):
    ax.set_facecolor(PANEL_BG)
    ax.axis("off")
    ax.set_title("Validation Card", color=WHITE, fontsize=10, fontweight="bold", pad=8)

    dsr_pass = dsr.get("passes_at_10pct", False) if dsr else False
    dsr_val = dsr.get("dsr", 0.0) if dsr else 0.0
    raw_sr = dsr.get("raw_sharpe", 0.0) if dsr else full.get("sharpe", 0)
    n_trials = dsr.get("n_trials", 0) if dsr else 0

    lines = [
        ("── Deflated Sharpe (DSR) ──", WHITE, 9),
        (f"Raw Sharpe:      {raw_sr:.4f}", GOLD, 8.5),
        (f"Expected Max SR: {dsr.get('expected_max_sharpe', 0):.4f}", GRAY, 8.5),
        (f"N Trials:        {n_trials}", GRAY, 8.5),
        (f"DSR p-value:     {dsr_val:.4f}", GREEN if dsr_pass else RED, 9),
        (f"Result:          {'PASSES ✓' if dsr_pass else 'FAILS ✗'}", GREEN if dsr_pass else RED, 9),
        ("", WHITE, 7),
        ("── Vol Targeting ──────────", WHITE, 9),
        (f"Target:          {vol_stats.get('vol_target_pct', 0):.1f}%", GOLD, 8.5),
        (f"Mean scale:      {vol_stats.get('mean_scale', 0):.4f}", WHITE, 8.5),
        (f"Min scale:       {vol_stats.get('min_scale', 0):.4f}", WHITE, 8.5),
        (f"At max (1.0):    {vol_stats.get('pct_at_max', 0):.1f}%", WHITE, 8.5),
        (f"Mean real. vol:  {vol_stats.get('mean_realized_vol_pct', 0):.2f}%", WHITE, 8.5),
        ("", WHITE, 7),
        ("── Target vs Achieved ─────", WHITE, 9),
        (f"Sharpe (tgt 2.13): {full.get('sharpe', 0):.4f}", GOLD, 8.5),
        (f"CAGR   (tgt 17.4): {full.get('cagr', 0):.2f}%", GOLD, 8.5),
        (f"Vol    (tgt  7.7): {full.get('ann_vol', 0):.2f}%", GOLD, 8.5),
        (f"MDD    (tgt -7.7): {full.get('max_dd_close_pct', 0):.2f}%", GOLD, 8.5),
    ]

    y_pos = 0.98
    for text, color, size in lines:
        ax.text(0.05, y_pos, text, transform=ax.transAxes,
                va="top", ha="left", fontsize=size,
                color=color, fontfamily="monospace")
        y_pos -= 0.048


# ─────────────────────────────────────────────────────────────────────────────
# Grid Search (optional)
# ─────────────────────────────────────────────────────────────────────────────

def run_grid_search() -> pd.DataFrame:
    """
    Grid search over vol targeting parameters.
    Returns DataFrame of results sorted by Sharpe.
    """
    print("[Strategy C+] Running grid search...")

    grid = {
        "vol_target": [6.0, 7.0, 8.0, 9.0, 10.0],
        "vol_lookback_days": [5, 10, 15],
        "top_n": [1, 2],
    }

    records = []
    total = len(grid["vol_target"]) * len(grid["vol_lookback_days"]) * len(grid["top_n"])
    run_idx = 0

    for vt in grid["vol_target"]:
        for lb in grid["vol_lookback_days"]:
            for tn in grid["top_n"]:
                run_idx += 1
                print(f"[Grid {run_idx}/{total}] vol_target={vt}, lookback={lb}, top_n={tn}")

                try:
                    config = StrategyCConfig(vol_target=vt, vol_lookback_days=lb, top_n=tn)
                    engine = StrategyCEngine(config=config)
                    results = engine.run_backtest(save_results=False)
                    fm = results["full_metrics"]
                    oos = results["oos_metrics"]

                    records.append({
                        "vol_target": vt,
                        "vol_lookback_days": lb,
                        "top_n": tn,
                        "sharpe": fm.get("sharpe", 0),
                        "cagr": fm.get("cagr", 0),
                        "ann_vol": fm.get("ann_vol", 0),
                        "max_dd": fm.get("max_dd_close_pct", 0),
                        "calmar": fm.get("calmar", 0),
                        "sortino": fm.get("sortino", 0),
                        "oos_sharpe": oos.get("sharpe", 0),
                        "oos_cagr": oos.get("cagr", 0),
                        "dsr": results["deflated_sharpe"].get("dsr", 0),
                    })
                except Exception as e:
                    print(f"  Failed: {e}")

    df = pd.DataFrame(records).sort_values("sharpe", ascending=False)
    grid_path = OUTPUT_DIR / "grid_search_results.csv"
    df.to_csv(grid_path, index=False)
    print(f"\n[Strategy C+] Grid search complete. Top 5 by Sharpe:\n{df.head()}")
    print(f"Saved → {grid_path}")
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Strategy C+ Backtest Runner")
    parser.add_argument("--grid-search", action="store_true",
                        help="Run parameter grid search")
    parser.add_argument("--is-oos-only", action="store_true",
                        help="Print IS/OOS metrics only, skip dashboard")
    args = parser.parse_args()

    if args.grid_search:
        run_grid_search()
    else:
        run_full_backtest_and_dashboard()
