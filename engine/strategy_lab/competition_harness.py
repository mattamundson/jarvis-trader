"""
JARVIS TRADER — Strategy Competition Harness (Strategy Novel #4)
================================================================
Run N candidate strategies as parallel paper-trading "agents," each with $X
virtual capital. Winner-takes-all weight allocation over a rolling 30-day
window. Optionally revive losers with fresh capital after each window to
mitigate survivorship bias.

Source: docs/digest/strategy-synthesis.md Novel #4 (@zostaff 10-bot
competition tweet). Mirrors the "AI Hedge Fund Team" multi-agent allocation
pattern but at the STRATEGY level, not the agent level.

Design intent
-------------
* Competitor = (strategy_id, capital, trades log, current weight)
* On each scoring window close (default 30 days):
    - Score each competitor by Profit Factor × √N_trades (rewards both
      quality and sample size; penalises low-trade-count winners)
    - Reallocate weights via softmax(scores / temperature)
    - If `revive_losers=True`, set each competitor's capital back to the
      original starting capital before the next window (so weight, not
      bankroll, is the dynamic)
* The harness DOES NOT execute live orders; it tracks paper-trade outcomes
  injected by the caller (or `engine/backtest/paper_runner.py` in research
  mode). Live wiring is a follow-up that touches safety-critical sizing
  logic and warrants Tier 3 review.

Wiring (deferred)
-----------------
* `engine/strategy_lab/strategy_loop.py` would call `harness.record_trade()`
  for each closed trade
* `engine/agents/trader.py` could read `harness.weights[strategy_id]` as a
  per-strategy size multiplier, but this also touches sizing logic and
  warrants Tier 3 review
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

__all__ = [
    "TradeOutcome",
    "Competitor",
    "CompetitionHarness",
    "compute_profit_factor",
    "compute_sharpe",
]


@dataclass
class TradeOutcome:
    """One closed trade for one competitor."""

    timestamp: datetime
    pnl_usd: float
    symbol: str = ""
    bars_held: int = 0
    notes: str = ""


@dataclass
class Competitor:
    """One candidate strategy participating in the competition."""

    strategy_id: str
    starting_capital: float
    capital: float = 0.0
    weight: float = 0.0           # current allocation weight (sum across all = 1.0)
    trades: list[TradeOutcome] = field(default_factory=list)

    def __post_init__(self):
        if self.capital == 0.0:
            self.capital = self.starting_capital

    # ── Window-scoped metrics ────────────────────────────────────────────────

    def trades_in_window(self, window_start: datetime, window_end: datetime) -> list[TradeOutcome]:
        return [t for t in self.trades if window_start <= t.timestamp < window_end]

    def n_trades(self, window_start: datetime, window_end: datetime) -> int:
        return len(self.trades_in_window(window_start, window_end))

    def realized_pnl(self, window_start: datetime, window_end: datetime) -> float:
        return sum(t.pnl_usd for t in self.trades_in_window(window_start, window_end))


# ── Pure scoring helpers ────────────────────────────────────────────────────

def compute_profit_factor(trades: list[TradeOutcome]) -> float:
    """gross_wins / gross_losses. Returns inf when no losses, 0.0 when no trades."""
    if not trades:
        return 0.0
    gross_wins = sum(t.pnl_usd for t in trades if t.pnl_usd > 0)
    gross_losses = -sum(t.pnl_usd for t in trades if t.pnl_usd < 0)
    if gross_losses == 0:
        return float("inf") if gross_wins > 0 else 0.0
    return gross_wins / gross_losses


def compute_sharpe(trades: list[TradeOutcome], periods_per_year: int = 252) -> float:
    """Annualised Sharpe of per-trade pnl. Zero-variance returns 0.0."""
    if len(trades) < 2:
        return 0.0
    pnls = [t.pnl_usd for t in trades]
    mean_pnl = sum(pnls) / len(pnls)
    var = sum((p - mean_pnl) ** 2 for p in pnls) / (len(pnls) - 1)
    if var <= 0:
        return 0.0
    std = math.sqrt(var)
    return (mean_pnl / std) * math.sqrt(periods_per_year)


def _softmax(scores: list[float], temperature: float = 1.0) -> list[float]:
    """Numerically-stable softmax. Empty input → empty output."""
    if not scores:
        return []
    if temperature <= 0:
        # Argmax fallback
        best_idx = max(range(len(scores)), key=lambda i: scores[i])
        return [1.0 if i == best_idx else 0.0 for i in range(len(scores))]
    max_s = max(scores)
    exps = [math.exp((s - max_s) / temperature) for s in scores]
    total = sum(exps)
    return [e / total for e in exps]


# ── Harness ──────────────────────────────────────────────────────────────────

class CompetitionHarness:
    """
    Tracks N competitors, awards rolling-window allocation weights based on
    realised PnL behaviour. Caller is responsible for invoking
    `record_trade()` and `score_window()` at the appropriate cadence.
    """

    def __init__(
        self,
        strategy_ids: list[str],
        starting_capital: float = 1000.0,
        window_days: int = 30,
        scoring_metric: str = "pf_sqrt_n",   # or "sharpe", "pf", "pnl"
        softmax_temperature: float = 1.0,
        revive_losers: bool = True,
        min_trades_for_scoring: int = 5,
    ):
        if not strategy_ids:
            raise ValueError("strategy_ids must be non-empty")
        if starting_capital <= 0:
            raise ValueError("starting_capital must be positive")
        if window_days <= 0:
            raise ValueError("window_days must be positive")

        self.window = timedelta(days=window_days)
        self.scoring_metric = scoring_metric
        self.softmax_temperature = softmax_temperature
        self.revive_losers = revive_losers
        self.min_trades_for_scoring = min_trades_for_scoring

        equal_weight = 1.0 / len(strategy_ids)
        self.competitors: dict[str, Competitor] = {
            sid: Competitor(
                strategy_id=sid,
                starting_capital=starting_capital,
                weight=equal_weight,
            )
            for sid in strategy_ids
        }
        self.window_history: list[dict] = []  # historical scoring snapshots

    # ── Trade ingestion ──────────────────────────────────────────────────────

    def record_trade(self, strategy_id: str, outcome: TradeOutcome) -> None:
        """Caller injects each closed trade for the named competitor."""
        if strategy_id not in self.competitors:
            raise KeyError(f"Unknown strategy_id: {strategy_id}")
        c = self.competitors[strategy_id]
        c.trades.append(outcome)
        c.capital += outcome.pnl_usd

    # ── Scoring + reallocation ───────────────────────────────────────────────

    def _score_competitor(self, c: Competitor, window_start: datetime, window_end: datetime) -> float:
        trades = c.trades_in_window(window_start, window_end)
        n = len(trades)
        if n < self.min_trades_for_scoring:
            return 0.0
        if self.scoring_metric == "pnl":
            return c.realized_pnl(window_start, window_end)
        if self.scoring_metric == "sharpe":
            return compute_sharpe(trades)
        if self.scoring_metric == "pf":
            pf = compute_profit_factor(trades)
            return min(pf, 100.0)  # clamp inf/huge values
        if self.scoring_metric == "pf_sqrt_n":
            pf = min(compute_profit_factor(trades), 100.0)
            return pf * math.sqrt(n)
        raise ValueError(f"Unknown scoring_metric: {self.scoring_metric}")

    def score_window(self, window_end: Optional[datetime] = None) -> dict[str, float]:
        """
        Score all competitors over [window_end - window, window_end), reallocate
        weights via softmax, optionally revive losers' capital. Returns the
        new weight map and appends a snapshot to `window_history`.
        """
        end = window_end or datetime.now()
        start = end - self.window

        scores = {sid: self._score_competitor(c, start, end) for sid, c in self.competitors.items()}
        score_list = [scores[sid] for sid in self.competitors]
        new_weights = _softmax(score_list, self.softmax_temperature)
        weight_map = dict(zip(self.competitors, new_weights, strict=False))

        for sid, c in self.competitors.items():
            c.weight = weight_map[sid]
            if self.revive_losers:
                c.capital = c.starting_capital

        snapshot = {
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "scoring_metric": self.scoring_metric,
            "scores": dict(scores),
            "weights": dict(weight_map),
            "n_trades": {sid: c.n_trades(start, end) for sid, c in self.competitors.items()},
        }
        self.window_history.append(snapshot)
        return weight_map

    # ── Inspection ───────────────────────────────────────────────────────────

    @property
    def weights(self) -> dict[str, float]:
        return {sid: c.weight for sid, c in self.competitors.items()}

    def best_competitor(self) -> str:
        return max(self.competitors, key=lambda sid: self.competitors[sid].weight)

    def to_dict(self) -> dict:
        return {
            "scoring_metric": self.scoring_metric,
            "window_days": int(self.window.total_seconds() // 86400),
            "softmax_temperature": self.softmax_temperature,
            "revive_losers": self.revive_losers,
            "min_trades_for_scoring": self.min_trades_for_scoring,
            "competitors": {
                sid: {
                    "weight": round(c.weight, 6),
                    "capital": round(c.capital, 2),
                    "n_trades": len(c.trades),
                }
                for sid, c in self.competitors.items()
            },
            "windows_scored": len(self.window_history),
        }
