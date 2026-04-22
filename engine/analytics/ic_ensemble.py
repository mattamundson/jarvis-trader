"""
JARVIS TRADER — IC-Weighted Signal Ensemble
=============================================
Combines Stage 1 analyst signals by their rolling Information Coefficient.

Information Coefficient (IC)
----------------------------
IC is the Spearman rank correlation between an analyst's signal and the
realized P&L direction of the trades that signal helped produce. A positive
IC means the analyst's signals tend to move in the same direction as the
trade outcome; a negative IC means the analyst is actively misleading the
pipeline and should be muted.

The rolling 30-day window makes the weighting adaptive — an analyst that
worked well last quarter but is currently cold gets its weight reduced,
while a recently-hot analyst gets its weight boosted. Noise is filtered by
a minimum trade count floor (below which we fall back to equal weights).

Weight formula
--------------
    w_i = max(0, IC_i) / sum_j(max(0, IC_j))

- Negative IC → weight = 0 (muted)
- Positive IC → weight proportional to IC magnitude, normalized to sum to 1.0
- Insufficient data (< MIN_TRADES_FOR_IC) → equal weights across all agents

Source
------
Based on @RohOnChain's "Math Behind Combining 50 Weak Signals Into One Winning
Trade": https://x.com/RohOnChain/status/2041180375838498950

JARVIS integration
------------------
Intended to replace simple averaging in the Stage 2 debate aggregation. The
ensemble reads from engine/data/agent_feedback.db (populated by
AgentFeedbackTracker after each closed trade) and exposes two primary methods:

    ensemble = ICWeightedEnsemble()
    weights = ensemble.get_ensemble_weights()
    consensus = ensemble.weighted_consensus(analyst_reports)
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    from scipy.stats import spearmanr  # type: ignore

    _HAS_SCIPY = True
except Exception:  # pragma: no cover — scipy optional
    _HAS_SCIPY = False
    logger.info("scipy not available; ICWeightedEnsemble will use manual Spearman.")

__all__ = ["ICWeightedEnsemble", "BrierCalibrationTracker"]


# ---------------------------------------------------------------------------
# Defaults — mirror AgentFeedbackTracker schema so this module reuses the
# existing database without forcing a separate tracking system.
# ---------------------------------------------------------------------------

_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "agent_feedback.db"

# Agents whose signal columns exist in trade_outcomes table.
DEFAULT_AGENTS: Tuple[str, ...] = (
    "technical",
    "news",
    "social",
    "fundamental",
    "corey",
)

# Minimum trades within the window before an agent's IC is trusted.
MIN_TRADES_FOR_IC = 5

# Rolling lookback window.
DEFAULT_WINDOW_DAYS = 30


class ICWeightedEnsemble:
    """
    Rolling Information Coefficient ensemble for Stage 1 analyst signals.

    Reads (signal, realized P&L) pairs from the AgentFeedbackTracker
    `trade_outcomes` table. Computes Spearman rank correlation per agent
    over a rolling window, then normalizes positive ICs into weights.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        agents: Optional[List[str]] = None,
        window_days: int = DEFAULT_WINDOW_DAYS,
        min_trades: int = MIN_TRADES_FOR_IC,
    ):
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self.agents: List[str] = list(agents) if agents else list(DEFAULT_AGENTS)
        self.window_days = window_days
        self.min_trades = min_trades

    # ------------------------------------------------------------------
    # Data fetch
    # ------------------------------------------------------------------

    def _fetch_signals_and_pnl(
        self,
        agent_name: str,
    ) -> List[Tuple[float, float]]:
        """
        Fetch (signal, pnl_usd) pairs for one agent from trade_outcomes.

        The trade_outcomes schema (see AgentFeedbackTracker._init_db) has
        one signal column per agent: technical_signal, news_signal, etc.
        Returns an empty list if the DB, table, or column is missing — the
        caller treats empty as "no data, use equal weights".
        """
        if not self.db_path.exists():
            return []

        signal_col = f"{agent_name}_signal"
        cutoff_iso = (
            datetime.now(timezone.utc) - timedelta(days=self.window_days)
        ).isoformat()

        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                # Safety check — ensure column exists before querying.
                cur = conn.execute("PRAGMA table_info(trade_outcomes)")
                columns = {row[1] for row in cur.fetchall()}
                if signal_col not in columns or "pnl_usd" not in columns:
                    return []

                cur = conn.execute(
                    f"""
                    SELECT {signal_col}, pnl_usd
                    FROM trade_outcomes
                    WHERE timestamp >= ?
                      AND {signal_col} IS NOT NULL
                      AND pnl_usd IS NOT NULL
                    """,
                    (cutoff_iso,),
                )
                pairs: List[Tuple[float, float]] = []
                for signal, pnl in cur.fetchall():
                    try:
                        pairs.append((float(signal), float(pnl)))
                    except (TypeError, ValueError):
                        continue
                return pairs
        except sqlite3.DatabaseError as e:
            logger.warning("ICWeightedEnsemble DB error for %s: %s", agent_name, e)
            return []

    # ------------------------------------------------------------------
    # Spearman — scipy preferred, manual fallback
    # ------------------------------------------------------------------

    @staticmethod
    def _manual_spearman(x: List[float], y: List[float]) -> float:
        """
        Manual Spearman rank correlation implementation.

        Used when scipy is unavailable. Returns 0.0 for degenerate inputs
        (< 2 points, constant vectors, zero-variance ranks).
        """
        n = len(x)
        if n < 2 or n != len(y):
            return 0.0

        def _rank(values: List[float]) -> List[float]:
            """Average ranks for ties — matches scipy default."""
            indexed = sorted(enumerate(values), key=lambda p: p[1])
            ranks = [0.0] * n
            i = 0
            while i < n:
                j = i
                while j + 1 < n and indexed[j + 1][1] == indexed[i][1]:
                    j += 1
                avg_rank = (i + j) / 2.0 + 1.0
                for k in range(i, j + 1):
                    ranks[indexed[k][0]] = avg_rank
                i = j + 1
            return ranks

        rx = _rank(x)
        ry = _rank(y)
        mean_x = sum(rx) / n
        mean_y = sum(ry) / n

        num = sum((rx[i] - mean_x) * (ry[i] - mean_y) for i in range(n))
        denom_x = sum((r - mean_x) ** 2 for r in rx) ** 0.5
        denom_y = sum((r - mean_y) ** 2 for r in ry) ** 0.5

        if denom_x == 0.0 or denom_y == 0.0:
            return 0.0

        return num / (denom_x * denom_y)

    def compute_ic(self, agent_name: str) -> float:
        """
        Return the Information Coefficient for one agent over the window.

        Returns 0.0 on insufficient data, scipy error, or NaN result.
        """
        pairs = self._fetch_signals_and_pnl(agent_name)
        if len(pairs) < self.min_trades:
            return 0.0

        signals = [p[0] for p in pairs]
        pnls = [p[1] for p in pairs]

        if _HAS_SCIPY:
            try:
                ic, _pvalue = spearmanr(signals, pnls)
                # scipy returns nan on zero-variance inputs
                if ic is None or ic != ic:  # NaN check
                    return 0.0
                return float(ic)
            except Exception as e:
                logger.debug("scipy spearmanr failed for %s: %s", agent_name, e)
                return self._manual_spearman(signals, pnls)

        return self._manual_spearman(signals, pnls)

    # ------------------------------------------------------------------
    # Ensemble weights + consensus
    # ------------------------------------------------------------------

    def get_ensemble_weights(
        self,
        agents: Optional[List[str]] = None,
    ) -> Dict[str, float]:
        """
        Return normalized IC-based weights summing to 1.0.

        Negative ICs are clamped to zero (muting the analyst). If the sum of
        positive ICs is zero (no signal anywhere, or insufficient data for
        every agent), returns equal weights as a safe fallback.
        """
        agent_list = list(agents) if agents else list(self.agents)
        if not agent_list:
            return {}

        ics = {agent: self.compute_ic(agent) for agent in agent_list}
        positive = {agent: max(0.0, ic) for agent, ic in ics.items()}
        total = sum(positive.values())

        if total <= 0.0:
            # Equal-weight fallback — every agent gets 1/n.
            n = len(agent_list)
            return {agent: 1.0 / n for agent in agent_list}

        return {agent: value / total for agent, value in positive.items()}

    def weighted_consensus(
        self,
        analyst_reports: Dict[str, Dict],
        signal_key: str = "signal",
    ) -> float:
        """
        Combine analyst signals into a single consensus value in [-1.0, 1.0].

        - analyst_reports: {"technical": {"signal": 0.5}, "news": {...}, ...}
        - signal_key: which key inside each report holds the numeric signal

        Agents present in analyst_reports but missing from the ensemble
        weights (e.g. a new analyst with no history) receive the equal-weight
        fallback share implicitly via get_ensemble_weights.
        """
        if not analyst_reports:
            return 0.0

        weights = self.get_ensemble_weights(list(analyst_reports.keys()))
        total = 0.0
        for agent, report in analyst_reports.items():
            if not isinstance(report, dict):
                continue
            raw = report.get(signal_key)
            if raw is None:
                continue
            try:
                signal = float(raw)
            except (TypeError, ValueError):
                continue
            total += signal * weights.get(agent, 0.0)

        # Clamp to valid signal range.
        return max(-1.0, min(1.0, total))

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def get_ic_summary(self) -> Dict[str, float]:
        """Return the current IC for each configured agent (diagnostic)."""
        return {agent: self.compute_ic(agent) for agent in self.agents}

    def describe(self) -> Dict[str, object]:
        """
        Return a full human-readable snapshot of the ensemble state.

        Useful for logging at pipeline start or surfacing in a dashboard.
        """
        ics = self.get_ic_summary()
        weights = self.get_ensemble_weights()
        muted = [a for a, ic in ics.items() if ic <= 0.0]
        return {
            "db_path": str(self.db_path),
            "db_exists": self.db_path.exists(),
            "window_days": self.window_days,
            "min_trades": self.min_trades,
            "scipy": _HAS_SCIPY,
            "ics": ics,
            "weights": weights,
            "muted_agents": muted,
        }


# ---------------------------------------------------------------------------
# Brier-score calibration — complements IC by penalizing mis-calibrated
# confidence (IC measures direction; Brier measures whether confidence is
# earned). Source: runesleo/polymarket-toolkit Brier methodology, adapted
# for signal ∈ [-1, 1] interpretation.
# ---------------------------------------------------------------------------

# Neutral sentinel returned when an agent has insufficient history.
# 0.25 corresponds to a coin-flip predictor (p=0.5, outcome∈{0,1}): the
# best a completely uninformed agent can expect. Using this (instead of 0.0
# which means "perfect") makes "no data" and "perfect calibration" distinct.
BRIER_NEUTRAL = 0.25


class BrierCalibrationTracker:
    """
    Rolling Brier-score calibration per agent.

    For each trade row in ``trade_outcomes``:

        confidence_i = |agent_signal_i|            ∈ [0, 1]
        correct_i    = 1 if sign(agent_signal_i) == sign(pnl_usd) else 0
        brier_i      = (confidence_i - correct_i)² ∈ [0, 1]

    The per-agent Brier is the mean over the rolling window. Lower = better.
    Zero-magnitude signals are excluded (the agent had no opinion).

    Weights for re-weighting the debate are derived as::

        w_i ∝ 1 / (brier_i + ε)

    normalized across agents so they sum to 1.0. Well-calibrated agents
    receive more weight; confidently-wrong agents are down-weighted.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        agents: Optional[List[str]] = None,
        window_days: int = DEFAULT_WINDOW_DAYS,
        min_trades: int = MIN_TRADES_FOR_IC,
        epsilon: float = 0.01,
    ):
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self.agents: List[str] = list(agents) if agents else list(DEFAULT_AGENTS)
        self.window_days = window_days
        self.min_trades = min_trades
        self.epsilon = epsilon

    def _fetch_pairs(self, agent_name: str) -> List[Tuple[float, float]]:
        """
        Return (signal, pnl_usd) pairs within the window, skipping zero-signals.

        Mirrors ICWeightedEnsemble._fetch_signals_and_pnl but filters out the
        agent's no-opinion trades so they don't dilute the Brier mean.
        """
        if not self.db_path.exists():
            return []

        signal_col = f"{agent_name}_signal"
        cutoff_iso = (
            datetime.now(timezone.utc) - timedelta(days=self.window_days)
        ).isoformat()

        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cur = conn.execute("PRAGMA table_info(trade_outcomes)")
                columns = {row[1] for row in cur.fetchall()}
                if signal_col not in columns or "pnl_usd" not in columns:
                    return []

                cur = conn.execute(
                    f"""
                    SELECT {signal_col}, pnl_usd
                    FROM trade_outcomes
                    WHERE timestamp >= ?
                      AND {signal_col} IS NOT NULL
                      AND {signal_col} != 0
                      AND pnl_usd IS NOT NULL
                      AND pnl_usd != 0
                    """,
                    (cutoff_iso,),
                )
                pairs: List[Tuple[float, float]] = []
                for signal, pnl in cur.fetchall():
                    try:
                        pairs.append((float(signal), float(pnl)))
                    except (TypeError, ValueError):
                        continue
                return pairs
        except sqlite3.DatabaseError as e:
            logger.warning("BrierCalibrationTracker DB error for %s: %s", agent_name, e)
            return []

    def compute_brier(self, agent_name: str) -> float:
        """
        Return the mean Brier score for one agent over the window.

        Returns BRIER_NEUTRAL (0.25) when fewer than ``min_trades`` non-zero
        signal rows exist. This sentinel is explicitly distinct from a
        perfect-calibration Brier of 0.0.
        """
        pairs = self._fetch_pairs(agent_name)
        if len(pairs) < self.min_trades:
            return BRIER_NEUTRAL

        total = 0.0
        for signal, pnl in pairs:
            confidence = min(1.0, abs(signal))
            correct = 1.0 if (signal > 0) == (pnl > 0) else 0.0
            total += (confidence - correct) ** 2

        return total / len(pairs)

    def get_calibration_weights(
        self,
        agents: Optional[List[str]] = None,
    ) -> Dict[str, float]:
        """
        Return normalized weights where ``w_i ∝ 1 / (brier_i + ε)``.

        Agents with neutral Brier (insufficient data) receive the neutral
        inverse weight — neither boosted nor penalized.
        """
        agent_list = list(agents) if agents else list(self.agents)
        if not agent_list:
            return {}

        briers = {agent: self.compute_brier(agent) for agent in agent_list}
        inverse = {a: 1.0 / (b + self.epsilon) for a, b in briers.items()}
        total = sum(inverse.values())
        if total <= 0.0:
            n = len(agent_list)
            return {a: 1.0 / n for a in agent_list}
        return {a: v / total for a, v in inverse.items()}

    def get_brier_summary(self) -> Dict[str, float]:
        """Diagnostic — per-agent Brier across the window."""
        return {agent: self.compute_brier(agent) for agent in self.agents}

    def describe(self) -> Dict[str, object]:
        """Full snapshot for logging / dashboard."""
        briers = self.get_brier_summary()
        weights = self.get_calibration_weights()
        return {
            "db_path": str(self.db_path),
            "db_exists": self.db_path.exists(),
            "window_days": self.window_days,
            "min_trades": self.min_trades,
            "epsilon": self.epsilon,
            "briers": briers,
            "weights": weights,
            "neutral_sentinel": BRIER_NEUTRAL,
        }
