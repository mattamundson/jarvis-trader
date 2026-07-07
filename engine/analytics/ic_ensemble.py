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

try:  # dual-path import (engine.* as package vs bare under engine/ cwd)
    from engine.analytics.outcome_hygiene import sanitize_outcome_rows
except ImportError:  # pragma: no cover
    from analytics.outcome_hygiene import sanitize_outcome_rows

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

# Sample count at/above which an IC estimate is trusted to fully drive the
# ensemble weights. Below this the weights are shrunk toward equal-weight in
# proportion to the available evidence (see get_ensemble_weights).
#
# Rationale: the standard error of a rank correlation is ~1/sqrt(n-1) -- about
# 0.38 at n=8, 0.27 at n=15, 0.16 at n=40 -- so an IC estimated from a handful
# of closed trades is statistically indistinguishable from noise and must not
# be allowed to concentrate 100% of the live sizing weight on a single analyst
# (the n=8 "100% on fundamental" failure this guard fixes). At n=40 the SE has
# fallen far enough that the ranking is meaningfully resolved, so that is the
# point at which the IC weights are used undiluted.
FULL_CONFIDENCE_TRADES = 40


def _directional_return(pnl: float, direction: Optional[str]) -> float:
    """Signed realized return aligned to price direction, not trade-P&L sign.

    An analyst signal expresses a *price-direction* view (>0 bullish, <0
    bearish), but ``pnl_usd`` already folds in the executed LONG/SHORT side --
    so on a SHORT trade a correct directional call inverts relative to pnl
    (e.g. a bullish call on a SHORT that lost means price rose, which is exactly
    what the analyst predicted). Flipping the sign for SHORT recovers the
    realized price direction, so both the IC correlation and the Brier
    correctness label measure the analyst against where price actually went --
    not whether the executed trade happened to make money. LONG and
    unknown/blank directions pass through unchanged (preserving prior behavior
    for legacy rows that predate the ``direction`` column).
    """
    return -pnl if (direction or "").strip().upper() == "SHORT" else pnl


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
        full_confidence_trades: int = FULL_CONFIDENCE_TRADES,
    ):
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self.agents: List[str] = list(agents) if agents else list(DEFAULT_AGENTS)
        self.window_days = window_days
        self.min_trades = min_trades
        self.full_confidence_trades = full_confidence_trades

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
        cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=self.window_days)).isoformat()

        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                # Safety check — ensure column exists before querying.
                cur = conn.execute("PRAGMA table_info(trade_outcomes)")
                columns = {row[1] for row in cur.fetchall()}
                if signal_col not in columns or "pnl_usd" not in columns:
                    return []

                cur = conn.execute(
                    f"""
                    SELECT {signal_col}, pnl_usd, direction, timestamp
                    FROM trade_outcomes
                    WHERE timestamp >= ?
                      AND {signal_col} IS NOT NULL
                      AND pnl_usd IS NOT NULL
                    """,
                    (cutoff_iso,),
                )
                rows: List[Tuple[float, float, Optional[str], Optional[str]]] = []
                for signal, pnl, direction, ts in cur.fetchall():
                    try:
                        rows.append((float(signal), float(pnl), direction, ts))
                    except (TypeError, ValueError):
                        continue
                # Correlate signal against the realized *price* direction, not the
                # executed-side pnl (ts now at index 3; direction at index 2).
                return [
                    (sig, _directional_return(pnl, direction))
                    for sig, pnl, direction, _ in sanitize_outcome_rows(
                        rows, context=f"IC/{agent_name}", ts_idx=3
                    )
                ]
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

    def _ic_with_count(self, agent_name: str) -> Tuple[float, int]:
        """
        Return ``(IC, sample_count)`` for one agent in a single DB pass.

        ``sample_count`` is the number of (signal, realized-return) pairs that
        survived hygiene filtering within the rolling window. When the count is
        below ``min_trades`` the IC is returned as 0.0 (untrusted) but the count
        is still reported, because the sample-adequacy shrinkage in
        ``get_ensemble_weights`` needs to know how thin the evidence is even for
        agents whose IC was floored to zero.
        """
        pairs = self._fetch_signals_and_pnl(agent_name)
        n = len(pairs)
        if n < self.min_trades:
            return 0.0, n

        signals = [p[0] for p in pairs]
        pnls = [p[1] for p in pairs]

        if _HAS_SCIPY:
            try:
                ic, _pvalue = spearmanr(signals, pnls)
                # scipy returns nan on zero-variance inputs
                if ic is None or ic != ic:  # NaN check
                    return 0.0, n
                return float(ic), n
            except Exception as e:
                logger.debug("scipy spearmanr failed for %s: %s", agent_name, e)
                return self._manual_spearman(signals, pnls), n

        return self._manual_spearman(signals, pnls), n

    def compute_ic(self, agent_name: str) -> float:
        """
        Return the Information Coefficient for one agent over the window.

        Returns 0.0 on insufficient data, scipy error, or NaN result.
        """
        return self._ic_with_count(agent_name)[0]

    # ------------------------------------------------------------------
    # Ensemble weights + consensus
    # ------------------------------------------------------------------

    def _weights_and_alpha(
        self,
        agent_list: List[str],
    ) -> Tuple[Dict[str, float], float, float]:
        """
        Core weight computation. Returns ``(weights, alpha, n_eff)``.

        ``weights`` are the sample-adequacy-shrunk IC weights (summing to 1.0),
        ``alpha`` is the shrinkage blend factor in [0, 1], and ``n_eff`` is the
        IC-weighted effective sample count behind those weights. Split out so
        both ``get_ensemble_weights`` and ``describe`` share one computation.
        """
        n_agents = len(agent_list)
        equal = 1.0 / n_agents

        ic_counts = {agent: self._ic_with_count(agent) for agent in agent_list}
        positive = {agent: max(0.0, ic) for agent, (ic, _n) in ic_counts.items()}
        total = sum(positive.values())

        if total <= 0.0:
            # Equal-weight fallback — no agent has a trusted positive IC.
            return dict.fromkeys(agent_list, equal), 0.0, 0.0

        raw = {agent: value / total for agent, value in positive.items()}

        # n_eff = how much data backs the agents actually receiving weight. A
        # spuriously-positive IC from few trades yields a small n_eff and is
        # therefore heavily shrunk toward equal weight; concentration is only
        # trusted once the winning agents have accumulated real history.
        n_eff = sum(raw[agent] * ic_counts[agent][1] for agent in agent_list)
        span = self.full_confidence_trades - self.min_trades
        if span <= 0:
            alpha = 1.0
        else:
            alpha = max(0.0, min(1.0, (n_eff - self.min_trades) / span))

        weights = {
            agent: alpha * raw[agent] + (1.0 - alpha) * equal
            for agent in agent_list
        }
        return weights, alpha, n_eff

    def get_ensemble_weights(
        self,
        agents: Optional[List[str]] = None,
    ) -> Dict[str, float]:
        """
        Return sample-adequacy-shrunk, IC-based weights summing to 1.0.

        Raw weights are proportional to each agent's positive IC (negative ICs
        are muted to zero). Those raw weights are then blended toward equal
        weight by a confidence factor ``alpha`` tied to how much data backs the
        agents actually receiving weight::

            w_final = alpha * w_IC + (1 - alpha) * (1 / n)
            alpha   = clip((n_eff - min_trades) /
                           (full_confidence_trades - min_trades), 0, 1)
            n_eff   = sum_i(w_IC_i * sample_count_i)

        This prevents a spuriously-positive IC estimated from a handful of
        trades (n_eff near the floor -> alpha ~ 0) from concentrating the entire
        sizing weight on one analyst, while letting the weights converge to pure
        IC weighting as evidence accumulates (n_eff -> full_confidence_trades ->
        alpha -> 1). If no agent has a trusted positive IC, the equal-weight
        fallback is returned unchanged.
        """
        agent_list = list(agents) if agents else list(self.agents)
        if not agent_list:
            return {}
        return self._weights_and_alpha(agent_list)[0]

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
        weights, alpha, n_eff = self._weights_and_alpha(list(self.agents))
        muted = [a for a, ic in ics.items() if ic <= 0.0]
        return {
            "db_path": str(self.db_path),
            "db_exists": self.db_path.exists(),
            "window_days": self.window_days,
            "min_trades": self.min_trades,
            "full_confidence_trades": self.full_confidence_trades,
            "scipy": _HAS_SCIPY,
            "ics": ics,
            "weights": weights,
            "muted_agents": muted,
            # How much the IC weights are trusted right now (1.0 = undiluted IC,
            # 0.0 = fully shrunk to equal weight) and the effective sample
            # behind that confidence. Surfaces the sizing-trust state so a
            # thin-sample concentration is visible before it drives live sizing.
            "shrinkage_alpha": round(alpha, 4),
            "effective_sample": round(n_eff, 2),
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
        cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=self.window_days)).isoformat()

        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cur = conn.execute("PRAGMA table_info(trade_outcomes)")
                columns = {row[1] for row in cur.fetchall()}
                if signal_col not in columns or "pnl_usd" not in columns:
                    return []

                cur = conn.execute(
                    f"""
                    SELECT {signal_col}, pnl_usd, direction, timestamp
                    FROM trade_outcomes
                    WHERE timestamp >= ?
                      AND {signal_col} IS NOT NULL
                      AND {signal_col} != 0
                      AND pnl_usd IS NOT NULL
                      AND pnl_usd != 0
                    """,
                    (cutoff_iso,),
                )
                rows: List[Tuple[float, float, Optional[str], Optional[str]]] = []
                for signal, pnl, direction, ts in cur.fetchall():
                    try:
                        rows.append((float(signal), float(pnl), direction, ts))
                    except (TypeError, ValueError):
                        continue
                # Score correctness against the realized *price* direction, not
                # the executed-side pnl (ts now at index 3; direction at index 2).
                return [
                    (sig, _directional_return(pnl, direction))
                    for sig, pnl, direction, _ in sanitize_outcome_rows(
                        rows, context=f"Brier/{agent_name}", ts_idx=3
                    )
                ]
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
            return dict.fromkeys(agent_list, 1.0 / n)
        return {a: v / total for a, v in inverse.items()}

    def get_brier_summary(self) -> Dict[str, float]:
        """Diagnostic — per-agent Brier across the window."""
        return {agent: self.compute_brier(agent) for agent in self.agents}

    def compute_rolling_brier(
        self,
        agents: Optional[List[str]] = None,
    ) -> Optional[float]:
        """
        Single-number Brier surface for /health.

        Returns the **mean** Brier across all agents that have ≥ ``min_trades``
        non-zero closed signals in the rolling window. Agents with insufficient
        data (the BRIER_NEUTRAL sentinel) are excluded so a cold-start agent
        does not anchor the system score at 0.25.

        Returns ``None`` when no agent has enough data — this lets the
        /health payload distinguish "no signal closures yet" from
        "model is perfectly calibrated" (Brier=0.0).

        Range: 0.0 (perfect) → 1.0 (always confidently wrong). Lower is better.
        """
        agent_list = list(agents) if agents else list(self.agents)
        real_briers: List[float] = []
        for agent in agent_list:
            pairs = self._fetch_pairs(agent)
            if len(pairs) < self.min_trades:
                continue
            total = 0.0
            for signal, pnl in pairs:
                confidence = min(1.0, abs(signal))
                correct = 1.0 if (signal > 0) == (pnl > 0) else 0.0
                total += (confidence - correct) ** 2
            real_briers.append(total / len(pairs))

        if not real_briers:
            return None
        return sum(real_briers) / len(real_briers)

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
