"""
JARVIS TRADER — Screener-gated Adaptive Volatility Trend entry rule
==================================================================
Composes the two TradingView ports into a single entry signal:

  1. The GreenStar2 screener (``analytics.screener_filters``) reduces a universe
     to near-low-of-day focus names (RVOL up, not a runaway, up on the day).
  2. The Adaptive Volatility Trend (``analytics.adaptive_volatility_trend``)
     must additionally confirm a **long** with a minimum signal score.

A symbol is a qualified entry only when it passes the screener *and* the AVT
prints a long whose 0-100 score clears ``min_avt_score``. The screener answers
"is this worth looking at right now"; the AVT answers "is the trend clean enough
to act". The backtest measures whether that second gate improves the screener's
forward returns (combined vs screener-only).

Point-in-time
-------------
Both inputs read only bars ``<= t``: the screener treats the last row as the
current bar, and the AVT series are backward-only / non-repainting. The backtest
generates the AVT once per symbol (valid because each bar's AVT value depends
only on bars ``<= t``) and recomputes the screener per decision bar. Forward
returns are evaluation labels only — never fed back (``.claude/rules/testing.md``).

This is a research diagnostic, not a tradable strategy: no sizing, costs, or
stops, and it never routes an order. Promote a configuration only after the
usual gate-v2 / MCPT discipline.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional

import pandas as pd

from analytics.adaptive_volatility_trend import AVTParams, generate_avt_signals
from analytics.screener_filters import ScreenerFilters, compute_metrics, passes
from backtest.screener_backtest import (
    DEFAULT_HORIZON,
    DEFAULT_MIN_HISTORY,
    DEFAULT_STEP,
    BucketStats,
    forward_return,
)

logger = logging.getLogger(__name__)

# Default minimum AVT score for a qualified entry (0 = accept any long).
DEFAULT_MIN_AVT_SCORE = 0.0


@dataclass
class EntryDecision:
    """Whether a single symbol is a qualified long entry at its latest bar."""

    symbol: Optional[str]
    qualified: bool
    screener_passed: bool
    avt_long: bool
    avt_score: float
    avt_signal: int
    last_price: float
    screener_reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def evaluate_entry(
    df: pd.DataFrame,
    screener_filters: Optional[ScreenerFilters] = None,
    avt_params: Optional[AVTParams] = None,
    *,
    min_avt_score: float = DEFAULT_MIN_AVT_SCORE,
) -> EntryDecision:
    """Decide whether ``df``'s latest bar is a screener-gated AVT long entry."""
    screener_filters = screener_filters or ScreenerFilters()
    avt_params = avt_params or AVTParams()

    metrics = compute_metrics(df, symbol=None)
    screen = passes(metrics, screener_filters)

    avt = generate_avt_signals(df, avt_params)
    last_signal = int(avt["avt_signal"].iloc[-1]) if len(avt) else 0
    last_score = float(avt["avt_score"].iloc[-1]) if len(avt) else 0.0
    avt_long = last_signal == 1 and last_score >= min_avt_score

    return EntryDecision(
        symbol=metrics.symbol,
        qualified=bool(screen.passed and avt_long),
        screener_passed=screen.passed,
        avt_long=avt_long,
        avt_score=last_score,
        avt_signal=last_signal,
        last_price=metrics.last_price,
        screener_reasons=screen.reasons,
    )


BarProvider = Callable[[str], Optional[pd.DataFrame]]


def qualified_entries(
    symbols: list[str],
    bar_provider: BarProvider,
    screener_filters: Optional[ScreenerFilters] = None,
    avt_params: Optional[AVTParams] = None,
    *,
    min_avt_score: float = DEFAULT_MIN_AVT_SCORE,
) -> list[EntryDecision]:
    """Evaluate a universe; return decisions sorted qualified-first by AVT score."""
    decisions: list[EntryDecision] = []
    for symbol in symbols:
        try:
            df = bar_provider(symbol)
        except Exception as exc:  # noqa: BLE001 — one bad symbol must not abort the run
            logger.debug("[ScreenerAVT] bar provider failed for %s: %s", symbol, exc)
            continue
        if df is None or len(df) == 0:
            continue
        decision = evaluate_entry(
            df, screener_filters, avt_params, min_avt_score=min_avt_score
        )
        decision.symbol = symbol
        decisions.append(decision)

    decisions.sort(key=lambda d: (0 if d.qualified else 1, -d.avt_score))
    return decisions


# ---------------------------------------------------------------------------
# Backtest: does the AVT gate improve the screener's forward returns?
# ---------------------------------------------------------------------------


@dataclass
class CombinedBacktestResult:
    """Forward-return comparison of combined entries vs screener-only passes."""

    horizon: int
    step: int
    min_avt_score: float
    symbols: list[str] = field(default_factory=list)
    n_screener_pass: int = 0
    combined: BucketStats = field(default_factory=BucketStats)
    screener_only: BucketStats = field(default_factory=BucketStats)

    @property
    def edge(self) -> float:
        """Combined entries' mean forward-return advantage over screener-only."""
        if pd.isna(self.combined.mean_fwd_return) or pd.isna(
            self.screener_only.mean_fwd_return
        ):
            return float("nan")
        return self.combined.mean_fwd_return - self.screener_only.mean_fwd_return

    def as_dict(self) -> dict:
        d = asdict(self)
        d["edge"] = self.edge
        return d


def run_combined_backtest(
    bars_by_symbol: dict[str, pd.DataFrame],
    screener_filters: Optional[ScreenerFilters] = None,
    avt_params: Optional[AVTParams] = None,
    *,
    min_avt_score: float = DEFAULT_MIN_AVT_SCORE,
    horizon: int = DEFAULT_HORIZON,
    step: int = DEFAULT_STEP,
    min_history: int = DEFAULT_MIN_HISTORY,
) -> CombinedBacktestResult:
    """Compare combined (screener + AVT-long) entries against screener-only passes.

    For every spaced decision bar that passes the screener, the bar is bucketed
    into ``combined`` if the AVT also prints a qualifying long, else
    ``screener_only``. A positive ``edge`` means the AVT gate preferentially kept
    the screener passes that went on to outperform.
    """
    if horizon < 1:
        raise ValueError("horizon must be >= 1")
    if step < 1:
        raise ValueError("step must be >= 1")

    screener_filters = screener_filters or ScreenerFilters()
    avt_params = avt_params or AVTParams()

    combined_returns: list[float] = []
    screener_only_returns: list[float] = []
    n_screener_pass = 0
    used_symbols: list[str] = []

    for symbol, df in bars_by_symbol.items():
        if df is None or len(df) <= min_history + horizon:
            continue
        used_symbols.append(symbol)
        close = df["close"]
        # AVT is point-in-time, so a single pass over the full frame is valid.
        avt = generate_avt_signals(df, avt_params)
        avt_signal = avt["avt_signal"].to_numpy()
        avt_score = avt["avt_score"].to_numpy()
        last_decision = len(df) - horizon - 1
        for i in range(min_history, last_decision + 1, step):
            metrics = compute_metrics(df.iloc[: i + 1], symbol=symbol)
            if not passes(metrics, screener_filters).passed:
                continue
            fwd = forward_return(close, i, horizon)
            if pd.isna(fwd):
                continue
            n_screener_pass += 1
            avt_long = avt_signal[i] == 1 and avt_score[i] >= min_avt_score
            (combined_returns if avt_long else screener_only_returns).append(fwd)

    return CombinedBacktestResult(
        horizon=horizon,
        step=step,
        min_avt_score=min_avt_score,
        symbols=used_symbols,
        n_screener_pass=n_screener_pass,
        combined=BucketStats.from_returns(combined_returns),
        screener_only=BucketStats.from_returns(screener_only_returns),
    )
