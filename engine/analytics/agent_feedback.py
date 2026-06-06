"""
Post-trade agent accuracy feedback system.

Tracks which Stage 1 analysts correctly predicted trade direction,
and computes rolling accuracy scores for debate weight adjustment.

Usage:
    tracker = AgentFeedbackTracker()
    # After each closed trade:
    tracker.record_outcome(trade_id, direction, pnl_usd, analyst_signals)

    # Get current weights for debate:
    weights = tracker.get_agent_weights()
    # Returns: {"technical": 1.15, "news": 0.90, "social": 0.85, ...}
"""

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional

try:  # dual-path import (engine.* as package vs bare under engine/ cwd)
    from engine.analytics.outcome_hygiene import (
        MAX_PLAUSIBLE_ABS_PNL_USD,
        is_plausible_pnl,
        sanitize_outcome_rows,
    )
except ImportError:  # pragma: no cover
    from analytics.outcome_hygiene import (
        MAX_PLAUSIBLE_ABS_PNL_USD,
        is_plausible_pnl,
        sanitize_outcome_rows,
    )

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "agent_feedback.db"
WEIGHTS_FILE = Path(__file__).parent.parent / "data" / "agent_weights.json"

# Weight adjustment bounds
MIN_WEIGHT = 0.70
MAX_WEIGHT = 1.30
DEFAULT_WEIGHT = 1.00

AGENT_NAMES = ["technical", "news", "social", "fundamental", "corey", "breakout", "harmonic"]


def build_analyst_signals_map(analyst_reports) -> Dict[str, float]:
    """Extract {agent_name: signal} from Stage-1 analyst_reports for the 7
    calibration agents.

    Persisted into strategy_params['analyst_signals'] at trade open so
    _record_agent_feedback can write a trade_outcomes row when the trade
    closes. Returns {} for missing/empty reports (caller treats as a
    legacy no-op). Single source of truth for the open-path extraction
    shared by the scanner and pipeline router.
    """
    if not isinstance(analyst_reports, dict):
        return {}
    out: Dict[str, float] = {}
    for name, rep in analyst_reports.items():
        if name in AGENT_NAMES and isinstance(rep, dict):
            try:
                out[name] = float(rep.get("signal", 0.0))
            except (TypeError, ValueError):
                out[name] = 0.0
    return out


class AgentFeedbackTracker:
    """Track Stage 1 analyst accuracy and compute debate weight adjustments."""

    def __init__(self):
        self._init_db()

    def _init_db(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trade_outcomes (
                    trade_id TEXT PRIMARY KEY,
                    timestamp TEXT,
                    symbol TEXT,
                    direction TEXT,  -- LONG or SHORT
                    pnl_usd REAL,
                    pnl_pct REAL,
                    outcome TEXT,    -- WIN or LOSS
                    technical_signal REAL,
                    news_signal REAL,
                    social_signal REAL,
                    fundamental_signal REAL,
                    corey_signal REAL,
                    breakout_signal REAL,
                    harmonic_signal REAL,
                    regime TEXT
                )
            """)
            # Idempotent migration: pre-2026-04-25 DBs lack breakout_signal,
            # harmonic_signal, regime. ADD COLUMN raises if column exists; swallow.
            existing = {r[1] for r in conn.execute("PRAGMA table_info(trade_outcomes)")}
            for col, decl in (
                ("breakout_signal", "REAL"),
                ("harmonic_signal", "REAL"),
                ("regime", "TEXT"),
            ):
                if col not in existing:
                    conn.execute(f"ALTER TABLE trade_outcomes ADD COLUMN {col} {decl}")

    def record_outcome(
        self,
        trade_id: str,
        symbol: str,
        direction: str,
        pnl_usd: float,
        analyst_signals: Dict[str, float],
        regime: Optional[str] = None,
        timestamp: Optional[str] = None,
    ):
        """
        Record a closed trade outcome with analyst signals.

        Args:
            trade_id: Unique trade identifier
            symbol: Futures symbol
            direction: "LONG" or "SHORT"
            pnl_usd: Realized P&L in USD (positive = win)
            analyst_signals: Dict of {agent_name: signal_value}
                            Signal: positive = bullish, negative = bearish
        """
        outcome = "WIN" if pnl_usd > 0 else "LOSS"
        ts = timestamp or datetime.now(timezone.utc).isoformat()

        # Ingestion guards (analytics/outcome_hygiene): corrupt or logically
        # duplicate rows must never enter trade_outcomes - they skew both the
        # live directional-accuracy weights and the Brier/IC surface.
        if not is_plausible_pnl(pnl_usd):
            logger.warning(
                "[Feedback] Rejecting implausible P&L for %s %s: pnl=%.2f "
                "(>$%d) - not recorded",
                trade_id, symbol, pnl_usd, int(MAX_PLAUSIBLE_ABS_PNL_USD),
            )
            return
        if self._is_logical_duplicate(trade_id, symbol, ts, pnl_usd):
            logger.warning(
                "[Feedback] Skipping logical-duplicate outcome for %s %s @ %s "
                "pnl=%.2f (same symbol+second+pnl under a different trade_id)",
                trade_id, symbol, ts[:19], pnl_usd,
            )
            return

        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO trade_outcomes
                (trade_id, timestamp, symbol, direction, pnl_usd, pnl_pct, outcome,
                 technical_signal, news_signal, social_signal, fundamental_signal, corey_signal,
                 breakout_signal, harmonic_signal, regime)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade_id, ts, symbol, direction, pnl_usd, 0.0, outcome,
                analyst_signals.get("technical", 0.0),
                analyst_signals.get("news", 0.0),
                analyst_signals.get("social", 0.0),
                analyst_signals.get("fundamental", 0.0),
                analyst_signals.get("corey", 0.0),
                analyst_signals.get("breakout", 0.0),
                analyst_signals.get("harmonic", 0.0),
                regime
            ))

        logger.debug("Recorded trade outcome: %s %s PnL=%.2f", trade_id, outcome, pnl_usd)

    def _is_logical_duplicate(
        self, trade_id: str, symbol: str, ts: str, pnl_usd: float
    ) -> bool:
        """True if a DIFFERENT trade_id already recorded the same logical
        outcome (same symbol + wall-clock second + pnl_usd). Catches the
        N-times-logged triplicate artifact at write time."""
        try:
            with sqlite3.connect(DB_PATH) as conn:
                row = conn.execute(
                    "SELECT trade_id FROM trade_outcomes "
                    "WHERE symbol = ? AND substr(timestamp, 1, 19) = ? "
                    "AND ABS(pnl_usd - ?) < 0.005 AND trade_id != ? LIMIT 1",
                    (symbol, ts[:19], pnl_usd, trade_id),
                ).fetchone()
            return row is not None
        except sqlite3.DatabaseError:
            return False

    def get_weights(
        self, window_days_short: int = 30, window_days_long: int = 90
    ) -> Dict[str, float]:
        """
        Compute analyst weights across all regimes.

        Returns: dict of {agent_name: weight_multiplier}
        """
        return self._compute_weights(None, window_days_short, window_days_long)

    def get_weights_by_regime(
        self, regime: str, window_days_short: int = 30, window_days_long: int = 90
    ) -> Dict[str, float]:
        """
        Compute weights filtered by a specific market regime.
        """
        return self._compute_weights(regime, window_days_short, window_days_long)

    def _compute_weights(
        self,
        regime: Optional[str],
        window_days_short: int = 30,
        window_days_long: int = 90
    ) -> Dict[str, float]:
        weights = {}
        for agent in AGENT_NAMES:
            acc_short = self._compute_accuracy_internal(agent, window_days_short, regime)
            acc_long = self._compute_accuracy_internal(agent, window_days_long, regime)

            # Blend short and long window
            blended = 0.7 * acc_short + 0.3 * acc_long

            # Convert accuracy to weight: 0.5 accuracy = 1.0 weight
            weight = DEFAULT_WEIGHT + (blended - 0.5) * 2 * (MAX_WEIGHT - DEFAULT_WEIGHT)
            weight = max(MIN_WEIGHT, min(MAX_WEIGHT, weight))

            weights[agent] = round(weight, 3)

        return weights

    def compute_accuracy(self, agent_name: str, window_days: int = 30) -> float:
        return self._compute_accuracy_internal(agent_name, window_days, None)

    def _compute_accuracy_internal(self, agent_name: str, window_days: int, regime: Optional[str]) -> float:
        """
        Compute directional accuracy for an agent over a rolling window,
        optionally filtered by regime.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
        signal_col = f"{agent_name}_signal"

        query = (
            f"SELECT direction, outcome, {signal_col}, timestamp, pnl_usd "
            f"FROM trade_outcomes WHERE timestamp > ? AND {signal_col} != 0"
        )
        params = [cutoff]

        if regime:
            query += " AND regime = ?"
            params.append(regime)

        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(query, tuple(params)).fetchall()

        # Strip corrupt / logically-duplicate rows before scoring so a single
        # bad or N-times-logged outcome cannot skew an agent's accuracy.
        rows = sanitize_outcome_rows(
            rows, context=f"accuracy/{agent_name}", signal_idx=2, pnl_idx=4, ts_idx=3
        )

        if len(rows) < 5:  # Need at least 5 trades for meaningful accuracy
            return 0.5  # Default to neutral if insufficient data

        correct = 0
        total = 0
        for direction, outcome, signal, _ts, _pnl in rows:
            if signal is None:
                continue
            # Check if agent predicted correctly
            agent_direction = "LONG" if signal > 0 else "SHORT"
            if outcome == "WIN":
                if agent_direction == direction:
                    correct += 1
            total += 1

        return correct / total if total > 0 else 0.5

    def get_agent_weights(self, window_days_short: int = 30, window_days_long: int = 90) -> Dict[str, float]:
        """
        Compute debate weight multipliers for each Stage 1 agent.

        Weight = 0.7 * accuracy_30d + 0.3 * accuracy_90d
        Clamped to [MIN_WEIGHT, MAX_WEIGHT]

        Returns: dict of {agent_name: weight_multiplier}
        """
        weights = {}
        for agent in AGENT_NAMES:
            acc_short = self.compute_accuracy(agent, window_days_short)
            acc_long = self.compute_accuracy(agent, window_days_long)

            # Blend short and long window
            blended = 0.7 * acc_short + 0.3 * acc_long

            # Convert accuracy to weight: 0.5 accuracy = 1.0 weight, 0.7 = 1.3, 0.3 = 0.7
            weight = DEFAULT_WEIGHT + (blended - 0.5) * 2 * (MAX_WEIGHT - DEFAULT_WEIGHT)
            weight = max(MIN_WEIGHT, min(MAX_WEIGHT, weight))

            weights[agent] = round(weight, 3)

        return weights

    def save_weights(self):
        """Save current weights to JSON file for pipeline consumption."""
        weights = self.get_agent_weights()
        weights["updated_at"] = datetime.now(timezone.utc).isoformat()

        WEIGHTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(WEIGHTS_FILE, "w") as f:
            json.dump(weights, f, indent=2)

        logger.info("Agent weights saved: %s", weights)
        return weights

    def load_weights(self) -> Dict[str, float]:
        """Load saved weights from JSON file."""
        if not WEIGHTS_FILE.exists():
            return dict.fromkeys(AGENT_NAMES, DEFAULT_WEIGHT)

        with open(WEIGHTS_FILE) as f:
            data = json.load(f)

        return {k: v for k, v in data.items() if k in AGENT_NAMES}
