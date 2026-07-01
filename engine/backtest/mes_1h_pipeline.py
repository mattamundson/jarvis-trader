"""
MES 1H Signal Pipeline — End-to-End Wiring

Flow:
  1. Load/receive 1H OHLCV bars for MES (Micro E-mini S&P 500)
  2. Compute IB, VWAP, EMA ribbon, ADX, STC, ROC, ATR
  3. Generate raw entry signals via existing signals.py engine
  4. Score each signal with SignalScorer
  5. Build a JarvisAlertV1 for every scored signal
  6. (Optional) route A_PLUS / A / B alerts to IBAdapter for paper orders

MES Contract Specs (CME):
  Tick size  : 0.25 index points
  Tick value : $1.25 per contract
  Margin     : ~$1,400 per contract (intraday, varies by broker)
  Session    : RTH 09:30-16:00 ET, Globex 17:00-16:00 CT next day
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

import pandas as pd

from engine.backtest.alert_schema import (
    AlertSide,
    AlertTier,
    BiasState,
    ExecutionMode,
    IBContext,
    JarvisAlertV1,
    RegimeState,
    RiskPlan,
    ScoreBreakdown,
    StructurePosition,
    TargetPlan,
    TrendContext,
    VWAPContext,
)
from engine.backtest.scoring import SignalScorer

# ---------------------------------------------------------------------------
# MES-specific constants
# ---------------------------------------------------------------------------

SYMBOL = "MES"
TIMEFRAME = "1H"
TICK_SIZE = 0.25          # index points
TICK_VALUE = 1.25         # USD per contract per tick
DEFAULT_RISK_PCT = 0.01   # 1% account risk per trade (default)
MIN_RR = 1.5              # minimum reward-to-risk for T1 to qualify

# ATR multipliers for stop and targets (validated against IB research)
STOP_ATR_MULT = 1.0
T1_ATR_MULT = 1.0
T2_ATR_MULT = 2.0
T3_ATR_MULT = 3.0


# ---------------------------------------------------------------------------
# Pipeline class
# ---------------------------------------------------------------------------

class MES1HPipeline:
    """
    End-to-end MES 1H signal pipeline.

    Parameters
    ----------
    execution_mode : ExecutionMode
        BACKTEST, PAPER, or LIVE.  Defaults to PAPER.
    account_size   : float
        Notional account size for position sizing.
    max_contracts  : int
        Hard cap on contracts per signal.
    run_id         : str | None
        Unique identifier for this pipeline run (auto-generated if None).
    """

    def __init__(
        self,
        execution_mode: ExecutionMode = ExecutionMode.PAPER,
        account_size: float = 50_000.0,
        max_contracts: int = 4,
        run_id: Optional[str] = None,
    ) -> None:
        self.execution_mode = execution_mode
        self.account_size = account_size
        self.max_contracts = max_contracts
        self.run_id = run_id or str(uuid.uuid4())[:8]
        self.scorer = SignalScorer()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, signals_df: pd.DataFrame) -> List[JarvisAlertV1]:
        """
        Process a DataFrame of pre-computed signals and return scored alerts.

        The ``signals_df`` must contain at minimum the columns consumed by
        SignalScorer plus: ``side``, ``atr``, ``close``, ``regime``, ``bias``,
        ``structure_position``, ``entry_signal``, ``session_date``.

        Returns a list of JarvisAlertV1 objects (all tiers, including BLOCKED).
        Callers should filter on ``alert.tier != AlertTier.BLOCKED`` before
        routing to execution.
        """
        alerts: List[JarvisAlertV1] = []
        for row in signals_df.itertuples(index=False):
            alert = self._process_row(row)
            if alert is not None:
                alerts.append(alert)
        return alerts

    def iter_alerts(self, signals_df: pd.DataFrame) -> Iterator[JarvisAlertV1]:
        """Generator version of ``run`` — memory-efficient for large DataFrames."""
        for row in signals_df.itertuples(index=False):
            alert = self._process_row(row)
            if alert is not None:
                yield alert

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _process_row(self, row) -> Optional[JarvisAlertV1]:
        score_result = self.scorer.score_row(row)
        side = AlertSide(getattr(row, "side", "LONG"))
        atr = float(getattr(row, "atr", 5.0) or 5.0)
        close = float(getattr(row, "close", 5000.0) or 5000.0)

        targets = self._build_targets(side, close, atr)
        if targets is None:
            return None  # R:R filter failed

        risk = self._build_risk(atr, close, score_result.total)

        return JarvisAlertV1(
            alert_id=str(uuid.uuid4()),
            created_at=datetime.now(timezone.utc),
            run_id=self.run_id,
            execution_mode=self.execution_mode,
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
            session_date=str(getattr(row, "session_date", "")[:10]),
            side=side,
            tier=AlertTier(score_result.tier),
            regime=RegimeState(getattr(row, "regime", "RANGE_BOUND")),
            bias=BiasState(getattr(row, "bias", "NEUTRAL")),
            structure_position=StructurePosition(
                getattr(row, "structure_position", "NEUTRAL_STRUCTURE")
            ),
            raw_entry_signal=str(getattr(row, "entry_signal", "")),
            score=ScoreBreakdown(
                total=score_result.total,
                structure=score_result.structure,
                trend=score_result.trend,
                momentum=score_result.momentum,
                volatility=score_result.volatility,
                risk_penalty=score_result.risk_penalty,
                blocked_reason=score_result.blocked_reason,
            ),
            ib_context=self._build_ib_context(row),
            vwap_context=self._build_vwap_context(row),
            trend_context=self._build_trend_context(row),
            targets=targets,
            risk=risk,
            tags=["MES", "1H", f"tier:{score_result.tier}"],
        )

    def _build_targets(self, side: AlertSide, close: float, atr: float) -> Optional[TargetPlan]:
        stop_dist = atr * STOP_ATR_MULT
        t1_dist = atr * T1_ATR_MULT
        t2_dist = atr * T2_ATR_MULT
        t3_dist = atr * T3_ATR_MULT

        if side == AlertSide.LONG:
            entry = close
            stop = round(entry - stop_dist, 2)
            t1 = round(entry + t1_dist, 2)
            t2 = round(entry + t2_dist, 2)
            t3 = round(entry + t3_dist, 2)
        else:
            entry = close
            stop = round(entry + stop_dist, 2)
            t1 = round(entry - t1_dist, 2)
            t2 = round(entry - t2_dist, 2)
            t3 = round(entry - t3_dist, 2)

        rr_t1 = t1_dist / stop_dist if stop_dist > 0 else 0.0
        if rr_t1 < MIN_RR:
            return None  # reject sub-MIN_RR setups

        return TargetPlan(
            entry_price=entry,
            stop_price=stop,
            target_1=t1,
            target_2=t2,
            target_3=t3,
            stop_distance=stop_dist,
            reward_to_risk_t1=round(rr_t1, 2),
            reward_to_risk_t2=round(t2_dist / stop_dist, 2),
            reward_to_risk_t3=round(t3_dist / stop_dist, 2),
        )

    def _build_risk(
        self, atr: float, close: float, score: float
    ) -> RiskPlan:
        # Score-based risk multiplier: A_PLUS=1.0, A=0.75, B=0.5, C/BLOCKED=0
        if score >= 75:
            multiplier = 1.0
        elif score >= 60:
            multiplier = 0.75
        elif score >= 40:
            multiplier = 0.50
        else:
            multiplier = 0.0

        applied_risk_pct = DEFAULT_RISK_PCT * multiplier
        risk_dollars = self.account_size * applied_risk_pct
        stop_dist_usd = (atr * STOP_ATR_MULT) / TICK_SIZE * TICK_VALUE
        contracts = int(risk_dollars / stop_dist_usd) if stop_dist_usd > 0 else 0
        contracts = min(contracts, self.max_contracts)

        return RiskPlan(
            base_risk_pct=DEFAULT_RISK_PCT,
            applied_risk_pct=applied_risk_pct,
            score_risk_multiplier=multiplier,
            contracts=contracts,
            notional_risk=contracts * stop_dist_usd,
            max_contracts_allowed=self.max_contracts,
        )

    @staticmethod
    def _build_ib_context(row) -> IBContext:
        return IBContext(
            ib_high=getattr(row, "ib_high", None),
            ib_low=getattr(row, "ib_low", None),
            ib_mid=getattr(row, "ib_mid", None),
            ib_range=getattr(row, "ib_range", None),
            ib_range_pct=getattr(row, "ib_range_pct", None),
            ib_tier=getattr(row, "ib_tier", None),
            broke_ib_high=bool(getattr(row, "broke_ib_high", False)),
            broke_ib_low=bool(getattr(row, "broke_ib_low", False)),
            c_period_confirmed=bool(getattr(row, "c_period_confirmed", False)),
            extension_prob_50=getattr(row, "extension_prob_50", None),
            extension_prob_100=getattr(row, "extension_prob_100", None),
        )

    @staticmethod
    def _build_vwap_context(row) -> VWAPContext:
        return VWAPContext(
            vwap=getattr(row, "vwap", None),
            distance_pct=getattr(row, "vwap_distance_pct", None),
            zscore=getattr(row, "vwap_zscore", None),
            above_vwap=bool(getattr(row, "above_vwap", False)),
            below_vwap=bool(getattr(row, "below_vwap", False)),
        )

    @staticmethod
    def _build_trend_context(row) -> TrendContext:
        return TrendContext(
            ema_8=getattr(row, "ema_8", None),
            ema_21=getattr(row, "ema_21", None),
            ema_34=getattr(row, "ema_34", None),
            adx=getattr(row, "adx", None),
            roc_10=getattr(row, "roc_10", None),
            stc_value=getattr(row, "stc_value", None),
            kama_value=getattr(row, "kama_value", None),
            trend_state=getattr(row, "trend_state", None),
            momentum_state=getattr(row, "momentum_state", None),
        )
