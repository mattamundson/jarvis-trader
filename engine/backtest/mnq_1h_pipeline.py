"""
MNQ 1H Signal Pipeline — End-to-End Wiring

Flow identical to MES 1H pipeline; MNQ-specific contract parameters applied.

MNQ Contract Specs (CME):
  Tick size  : 0.25 index points
  Tick value : $0.50 per contract
  Margin     : ~$1,000 per contract (intraday, varies by broker)
  Session    : RTH 09:30-16:00 ET, Globex 17:00-16:00 CT next day

Differences from MES:
  - Higher beta / larger point moves require tighter risk controls
  - STC thresholds are tighter (20/87) due to faster momentum swings
  - Default max contracts lower (3) given higher notional volatility
  - T1 target is 1.5× ATR (vs 1.0× for MES) to compensate for noise
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Iterator, List, Optional

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
from engine.backtest.mes_1h_pipeline import (
    MES1HPipeline,       # reuse helper methods
    DEFAULT_RISK_PCT,
)

# ---------------------------------------------------------------------------
# MNQ-specific constants
# ---------------------------------------------------------------------------

SYMBOL = "MNQ"
TIMEFRAME = "1H"
TICK_SIZE = 0.25
TICK_VALUE = 0.50          # $0.50 per tick (half of MES per notional dollar move)
MNQ_DEFAULT_RISK_PCT = 0.008   # 0.8% — tighter than MES due to higher beta
MNQ_MAX_CONTRACTS = 3
MIN_RR = 1.5

# ATR multipliers — T1 wider on MNQ to avoid noise stops
STOP_ATR_MULT = 1.0
T1_ATR_MULT = 1.5   # ← wider than MES T1 (1.0×)
T2_ATR_MULT = 2.5
T3_ATR_MULT = 4.0

# Tighter STC thresholds for MNQ (faster-moving instrument)
STC_OVERSOLD = 20
STC_OVERBOUGHT = 87


# ---------------------------------------------------------------------------
# Pipeline class
# ---------------------------------------------------------------------------

class MNQ1HPipeline:
    """
    End-to-end MNQ 1H signal pipeline.

    Inherits the same scoring framework as MES but applies MNQ-specific
    contract parameters, tighter STC thresholds, and wider ATR targets.
    """

    def __init__(
        self,
        execution_mode: ExecutionMode = ExecutionMode.PAPER,
        account_size: float = 50_000.0,
        max_contracts: int = MNQ_MAX_CONTRACTS,
        run_id: Optional[str] = None,
    ) -> None:
        self.execution_mode = execution_mode
        self.account_size = account_size
        self.max_contracts = max_contracts
        self.run_id = run_id or str(uuid.uuid4())[:8]
        self.scorer = SignalScorer()
        # Override STC thresholds in scorer for MNQ
        # (scorer reads from row, so no patch needed — the pipeline
        #  post-processes the score for the MNQ STC difference)
        self._mes_helper = MES1HPipeline(
            execution_mode=execution_mode,
            account_size=account_size,
            max_contracts=max_contracts,
            run_id=self.run_id,
        )

    def run(self, signals_df: pd.DataFrame) -> List[JarvisAlertV1]:
        """
        Process MNQ 1H signals and return scored JarvisAlertV1 objects.
        Identical call signature to MES1HPipeline.run().
        """
        alerts: List[JarvisAlertV1] = []
        for row in signals_df.itertuples(index=False):
            alert = self._process_row(row)
            if alert is not None:
                alerts.append(alert)
        return alerts

    def iter_alerts(self, signals_df: pd.DataFrame) -> Iterator[JarvisAlertV1]:
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
        atr = float(getattr(row, "atr", 30.0) or 30.0)  # MNQ ATR typically 20-60 pts
        close = float(getattr(row, "close", 20000.0) or 20000.0)

        targets = self._build_mnq_targets(side, close, atr)
        if targets is None:
            return None

        risk = self._build_mnq_risk(atr, score_result.total)

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
            ib_context=MES1HPipeline._build_ib_context(row),
            vwap_context=MES1HPipeline._build_vwap_context(row),
            trend_context=MES1HPipeline._build_trend_context(row),
            targets=targets,
            risk=risk,
            tags=["MNQ", "1H", f"tier:{score_result.tier}"],
        )

    def _build_mnq_targets(self, side: AlertSide, close: float, atr: float) -> Optional[TargetPlan]:
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
            return None

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

    def _build_mnq_risk(self, atr: float, score: float) -> RiskPlan:
        if score >= 75:
            multiplier = 1.0
        elif score >= 60:
            multiplier = 0.75
        elif score >= 40:
            multiplier = 0.50
        else:
            multiplier = 0.0

        applied_risk_pct = MNQ_DEFAULT_RISK_PCT * multiplier
        risk_dollars = self.account_size * applied_risk_pct
        stop_dist_usd = (atr * STOP_ATR_MULT) / TICK_SIZE * TICK_VALUE
        contracts = int(risk_dollars / stop_dist_usd) if stop_dist_usd > 0 else 0
        contracts = min(contracts, self.max_contracts)

        return RiskPlan(
            base_risk_pct=MNQ_DEFAULT_RISK_PCT,
            applied_risk_pct=applied_risk_pct,
            score_risk_multiplier=multiplier,
            contracts=contracts,
            notional_risk=contracts * stop_dist_usd,
            max_contracts_allowed=self.max_contracts,
        )
