"""Phase-4 combinations for the calendar/seasonality track.

The single-effect screener (`daily_calendar_discovery`) surfaces per-(symbol,effect)
seasonal passers. This asks the portfolio question: the passers fire on largely
DISJOINT day-sets across DIFFERENT asset classes (pre_holiday ~9 holidays/yr;
santa_claus late-Dec/early-Jan; last_day_of_month month-end), so stacking them is a
near-uncorrelated seasonal book -- more good days, lower concentration -- which
should beat any single seasonal on risk-adjusted return.

These are long-on-days BETA-harvest sleeves (not market-neutral like the relval
spreads), so the diversification is across WHICH days / WHICH asset, not across a
hedged edge. Everything here is IN-SAMPLE over the sleeves' shared window and is a
portfolio-construction read, NOT a validation upgrade -- the forward shadow stays the
gate. Sharpe/DD use the screener's own conventions (held-day distribution, annualized
by sqrt(252)) so the numbers are directly comparable to the leaderboard.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from backtest.daily_calendar_discovery import (
    CACHE_DIR,
    COST_BPS,
    EFFECTS,
    _latest_cache,
    _max_dd_pct,
    _sharpe,
)

# name -> (idx -> boolean mask), from the canonical screened family.
EFFECT_FNS = dict(EFFECTS)

# Sleeves with return correlation below this are "uncorrelated enough" to stack.
CORR_THRESHOLD = 0.30


@dataclass(frozen=True)
class Sleeve:
    """One (symbol, effect) seasonal passer -- a long-on-selected-days sleeve."""

    symbol: str
    effect: str

    @property
    def name(self) -> str:
        return f"{self.symbol}:{self.effect}"


def sleeve_returns(sleeve: Sleeve, *, cache_dir=CACHE_DIR, cost_bps: float = COST_BPS) -> pd.Series:
    """Full-calendar daily return stream: the close-to-close return (net of a flat
    per-held-day cost) on days the effect holds the instrument, 0.0 on flat days.
    Indexed by date so sleeves can be aligned and summed into a book."""
    path = _latest_cache(sleeve.symbol, cache_dir)
    if path is None:
        raise FileNotFoundError(f"no _1d cache for {sleeve.symbol} under {cache_dir}")
    df = pd.read_csv(path)
    closes = pd.Series(
        pd.to_numeric(df["close"]).to_numpy(), index=pd.to_datetime(df["timestamp"])
    ).sort_index()
    r = closes.pct_change()
    mask = np.asarray(EFFECT_FNS[sleeve.effect](closes.index), dtype=bool)
    held = mask & r.notna().to_numpy()
    out = np.where(held, r.to_numpy() - cost_bps / 1e4, 0.0)
    return pd.Series(out, index=closes.index, name=sleeve.name)


def align(streams: list[pd.Series]) -> pd.DataFrame:
    """Outer-join sleeve streams on the union of dates within the SHARED window
    [max start, min end]; flat/idle days are 0.0."""
    lo = max(s.index[0] for s in streams)
    hi = min(s.index[-1] for s in streams)
    idx = streams[0].index
    for s in streams[1:]:
        idx = idx.union(s.index)
    idx = idx[(idx >= lo) & (idx <= hi)]
    return pd.concat([s.reindex(idx).fillna(0.0) for s in streams], axis=1)


def correlation_matrix(book: pd.DataFrame) -> pd.DataFrame:
    """Pairwise correlation over days where AT LEAST ONE sleeve is live (both-flat
    days are uninformative and bias correlation toward 0)."""
    cols = list(book.columns)
    m = pd.DataFrame(np.eye(len(cols)), index=cols, columns=cols)
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            a, b = book[cols[i]], book[cols[j]]
            live = (a != 0.0) | (b != 0.0)
            rho = (
                float(np.corrcoef(a[live], b[live])[0, 1]) if int(live.sum()) > 2 else float("nan")
            )
            m.iloc[i, j] = m.iloc[j, i] = rho
    return m


def _active_metrics(stream: pd.Series) -> tuple[float, float]:
    """Screener-comparable (Sharpe, maxDD%) over the days the stream is active."""
    active = stream[stream != 0.0]
    return _sharpe(active), _max_dd_pct(active)


@dataclass
class BookResult:
    sleeves: list[str]
    n_days: int
    window: tuple[str, str]
    per_sleeve: dict[str, tuple[float, float]]  # name -> (sharpe, dd%)
    mean_abs_corr: float
    book_sharpe: float
    book_dd_pct: float
    best_sleeve_sharpe: float
    best_sleeve_dd_pct: float  # the SMALLEST single-sleeve drawdown
    worst_sleeve_dd_pct: float
    # Two honest diversification modes. A single sleeve with an exceptional Sharpe
    # makes a strict Sharpe-lift impossible, but the book can still dominate it on
    # RISK -- DD below every single sleeve. Report both, don't collapse to one bool.
    sharpe_diversifies: bool  # book Sharpe > best single sleeve Sharpe
    dd_diversifies: bool  # book maxDD < the smallest single-sleeve maxDD
    book_ret_per_dd: float  # book Sharpe / book DD% -- risk-adjusted lens
    best_sharpe_sleeve_ret_per_dd: float  # same lens for the best-Sharpe sleeve

    @property
    def verdict(self) -> str:
        if self.sharpe_diversifies and self.dd_diversifies:
            return "DIVERSIFIES (Sharpe + DD)"
        if self.dd_diversifies and self.book_ret_per_dd > self.best_sharpe_sleeve_ret_per_dd:
            return "DIVERSIFIES (risk -- DD below every sleeve)"
        if self.dd_diversifies:
            return "DD below every sleeve (Sharpe diluted)"
        return "no diversification gain"


def build_book(
    sleeves: list[Sleeve], *, cache_dir=CACHE_DIR, cost_bps: float = COST_BPS
) -> BookResult:
    """Equal-weight the sleeves into one seasonal book; compare to the components."""
    streams = [sleeve_returns(s, cache_dir=cache_dir, cost_bps=cost_bps) for s in sleeves]
    book_df = align(streams)
    w = 1.0 / len(sleeves)
    book = book_df.mul(w).sum(axis=1)

    per = {c: _active_metrics(book_df[c]) for c in book_df.columns}
    corr = correlation_matrix(book_df)
    off = corr.where(~np.eye(len(corr), dtype=bool))
    mean_abs_corr = float(np.nanmean(np.abs(off.to_numpy())))
    b_sharpe, b_dd = _active_metrics(book)
    best_sharpe = max(v[0] for v in per.values())
    best_dd = min(v[1] for v in per.values())
    worst_dd = max(v[1] for v in per.values())
    # ret-per-DD on the sleeve that owns the best standalone Sharpe (the bar the
    # book must beat on a risk-adjusted basis to justify diluting that Sharpe).
    best_sharpe_dd = next(dd for sh, dd in per.values() if sh == best_sharpe)
    return BookResult(
        sleeves=[s.name for s in sleeves],
        n_days=len(book_df),
        window=(str(book_df.index[0].date()), str(book_df.index[-1].date())),
        per_sleeve=per,
        mean_abs_corr=mean_abs_corr,
        book_sharpe=b_sharpe,
        book_dd_pct=b_dd,
        best_sleeve_sharpe=best_sharpe,
        best_sleeve_dd_pct=best_dd,
        worst_sleeve_dd_pct=worst_dd,
        sharpe_diversifies=bool(b_sharpe > best_sharpe),
        dd_diversifies=bool(b_dd < best_dd),
        book_ret_per_dd=float(b_sharpe / b_dd) if b_dd > 0 else float("inf"),
        best_sharpe_sleeve_ret_per_dd=(
            float(best_sharpe / best_sharpe_dd) if best_sharpe_dd > 0 else float("inf")
        ),
    )


def render_report(result: BookResult, corr: pd.DataFrame) -> str:
    lines = [
        "# Strategy-Factory Report -- Calendar Combinations (Phase 4)",
        "",
        f"- Sleeves: **{len(result.sleeves)}**  window {result.window[0]}->{result.window[1]} "
        f"({result.n_days} aligned days)",
        f"- Mean |off-diagonal correlation|: **{result.mean_abs_corr:.3f}** "
        f"(threshold {CORR_THRESHOLD})",
        "- IN-SAMPLE, long-on-days beta sleeves. Portfolio-construction read, NOT a",
        "  validation upgrade -- the forward shadow stays the gate.",
        "",
        "## Per-sleeve vs equal-weight book (screener-comparable Sharpe / maxDD%)",
        "",
        "| sleeve | Sharpe | maxDD% |",
        "|---|---|---|",
    ]
    for name, (sh, dd) in result.per_sleeve.items():
        lines.append(f"| {name} | {sh:.2f} | {dd:.1f}% |")
    lines.append(
        f"| **BOOK (equal-wt)** | **{result.book_sharpe:.2f}** | **{result.book_dd_pct:.1f}%** |"
    )
    lines += [
        "",
        f"Best single Sharpe {result.best_sleeve_sharpe:.2f} -> book {result.book_sharpe:.2f}; "
        f"smallest single maxDD {result.best_sleeve_dd_pct:.1f}% -> book {result.book_dd_pct:.1f}%.  "
        f"Risk-adjusted (Sharpe/DD): best-Sharpe sleeve "
        f"{result.best_sharpe_sleeve_ret_per_dd:.2f} -> book {result.book_ret_per_dd:.2f}.",
        "",
        f"=> **{result.verdict}**",
        "",
        "## Correlation matrix (>=1 sleeve live)",
        "",
        "```",
        corr.round(3).to_string(),
        "```",
    ]
    return "\n".join(lines) + "\n"
