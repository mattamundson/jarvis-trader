"""Cross-sectional momentum / dispersion signal engine (pure, no IO).

A NEW strategy class for the discovery factory, orthogonal to the exhausted
intraday-simple class, the pairwise relative-value spreads, and the turn-of-month
calendar anomaly. The thesis: across a basket of micro futures, the recent
*relative* winners keep outperforming the recent relative losers over a short
horizon -- a dollar-neutral long-top / short-bottom book harvests the cross-section
while hedging out broad market beta.

Everything here is pure pandas/numpy on a **price panel** (index = bar timestamps,
columns = symbols, values = close). No look-ahead: every score at row ``t`` is a
function of prices at or before ``t`` only. Sizing-to-contracts (the only place a
``ContractSpec`` is needed) is a separate step from the dollar weights, because in
return space the contract multiplier cancels -- equal *dollar* exposure is
multiplier-independent; the multiplier matters only when rounding to whole
contracts and charging per-contract cost (handled by the portfolio backtester).
"""

from __future__ import annotations

import pandas as pd


def assemble_close_panel(frames: dict) -> pd.DataFrame:
    """Inner-join per-symbol OHLCV frames into a close-price panel (NO ffill).

    Takes ``{symbol: DataFrame}`` (each with a datetime index and a ``close``
    column, the BacktestDataLoader shape) and returns a panel with one column per
    symbol and only the timestamps present in EVERY symbol. Dropping non-common
    rows (rather than forward-filling) is the no-look-ahead guarantee: a
    cross-sectional rank must compare contemporaneous bars, never a stale carry.
    Symbols whose frame is None/empty/missing ``close`` are skipped.
    """
    closes = {}
    for sym, df in frames.items():
        if df is None or len(df) == 0 or "close" not in getattr(df, "columns", []):
            continue
        closes[sym] = df["close"]
    if not closes:
        return pd.DataFrame()
    panel = pd.DataFrame(closes)  # aligns on the union of indices (NaN where absent)
    return panel.dropna(how="any")  # inner join: keep only fully-populated bars


def load_basket_panel(
    symbols: list[str],
    start: str,
    end: str,
    interval: str = "1d",
    loader=None,
) -> pd.DataFrame:
    """Load a close-price panel for ``symbols`` over ``[start, end]`` (inner-joined).

    Thin IO wrapper over ``BacktestDataLoader.load`` + ``assemble_close_panel``. A
    ``loader`` may be injected (any object exposing ``load(symbol, start, end,
    interval)``) -- the default constructs the real BacktestDataLoader lazily so
    the pure assembly path stays importable without the data layer.
    """
    if loader is None:  # pragma: no cover - exercised live, not in unit tests
        from backtest.data_loader import BacktestDataLoader

        loader = BacktestDataLoader()
    frames = {sym: loader.load(sym, start, end, interval) for sym in symbols}
    return assemble_close_panel(frames)


def compute_xs_momentum(price_panel: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """Per-symbol trailing total return over ``lookback`` bars.

    ``score[t, s] = price[t, s] / price[t - lookback, s] - 1``. The first
    ``lookback`` rows are NaN (insufficient history) -- never back-filled, so the
    score at ``t`` cannot see the future.
    """
    if lookback < 1:
        raise ValueError("lookback must be >= 1")
    return price_panel.pct_change(periods=lookback)


def compute_dispersion(price_panel: pd.DataFrame, lookback: int = 1) -> pd.Series:
    """Cross-sectional dispersion: std across symbols of each bar's return.

    A regime/conviction gauge -- cross-sectional momentum tends to pay only when
    the basket is actually spreading out (high dispersion). Returns one value per
    bar (population std, ddof=0); NaN where the lookback return is undefined.
    """
    if lookback < 1:
        raise ValueError("lookback must be >= 1")
    rets = price_panel.pct_change(periods=lookback)
    return rets.std(axis=1, ddof=0)


def rank_cross_section(score_panel: pd.DataFrame) -> pd.DataFrame:
    """Per-bar rank of each symbol's score across the cross-section.

    Rank 1 = lowest score (worst momentum), N = highest. All-NaN rows stay NaN
    (no cross-section to rank). NaN cells (a symbol with no score that bar) stay
    NaN and do not consume a rank.
    """
    return score_panel.rank(axis=1, method="first", na_option="keep")


def dollar_neutral_weights(score_panel: pd.DataFrame, top_k: int = 1) -> pd.DataFrame:
    """Dollar-neutral target weights: long the top_k, short the bottom_k each bar.

    Each long leg gets ``+0.5/top_k`` and each short leg ``-0.5/top_k`` so every
    populated row nets to ~0 (dollar-neutral) with gross exposure 1.0. A bar with
    fewer than ``2*top_k`` scored symbols cannot form a balanced book and is left
    flat (all zeros) -- never a one-sided bet. Weights are dollar fractions, not
    contracts (see module docstring on why the multiplier is irrelevant here).
    """
    if top_k < 1:
        raise ValueError("top_k must be >= 1")
    weights = pd.DataFrame(0.0, index=score_panel.index, columns=score_panel.columns)
    leg = 0.5 / top_k
    for ts, row in score_panel.iterrows():
        valid = row.dropna()
        if len(valid) < 2 * top_k:
            continue  # leave the row flat
        ordered = valid.sort_values()
        shorts = ordered.index[:top_k]
        longs = ordered.index[-top_k:]
        weights.loc[ts, list(longs)] = leg
        weights.loc[ts, list(shorts)] = -leg
    return weights


def compute_contract_positions(
    weights: pd.DataFrame,
    price_panel: pd.DataFrame,
    specs: dict,
    capital: float,
) -> pd.DataFrame:
    """Convert dollar-fraction weights to INTEGER contract counts per symbol.

    ``contracts = round(weight * capital / (price * multiplier))`` -- the only
    place ``CONTRACT_SPECS`` is load-bearing: a higher multiplier buys fewer
    contracts for the same dollar exposure, and integer rounding is what makes a
    micro book only approximately (not exactly) dollar-neutral.
    """
    positions = pd.DataFrame(0.0, index=weights.index, columns=weights.columns)
    for sym in weights.columns:
        if sym not in specs:
            raise KeyError(f"no ContractSpec for {sym}")
        mult = specs[sym].multiplier
        dollar = weights[sym] * capital
        positions[sym] = (dollar / (price_panel[sym] * mult)).round()
    return positions
