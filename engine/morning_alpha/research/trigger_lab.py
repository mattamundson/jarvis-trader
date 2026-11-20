from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Sequence

from morning_alpha.audit import OutcomeAuditor
from morning_alpha.models import MarketBar, Session, SetupCandidate, SignalOutcome, TradePlan
from morning_alpha.risk import TradeConstructor, TradeRejection


class TriggerKind(StrEnum):
    MARKET_OPEN = "market_open"
    PRIOR_DAY_HIGH = "prior_day_high"
    PREMARKET_HIGH = "premarket_high"
    ORB_5M = "orb_5m"
    ORB_15M = "orb_15m"
    ORB_30M = "orb_30m"
    BREAKOUT_RETEST = "breakout_retest"
    VWAP_RECLAIM = "vwap_reclaim"


@dataclass(frozen=True)
class TriggerDefinition:
    kind: TriggerKind
    version: str = "1.0.0"

    @property
    def canonical(self) -> str:
        return f"{self.kind.value}@{self.version}"


@dataclass(frozen=True)
class TriggerSignal:
    definition: TriggerDefinition
    entry: float
    active_from_index: int
    active_from_timestamp: object


DEFAULT_TRIGGERS = tuple(TriggerDefinition(kind) for kind in TriggerKind)


class TriggerLab:
    def __init__(self, constructor: TradeConstructor | None = None) -> None:
        self.constructor = constructor or TradeConstructor()
        self.auditor = OutcomeAuditor()

    def signal(
        self,
        definition: TriggerDefinition,
        bars: Sequence[MarketBar],
        *,
        prior_day_high: float | None = None,
    ) -> TriggerSignal | None:
        ordered = sorted(bars, key=lambda b: b.timestamp)
        rth = [(idx, bar) for idx, bar in enumerate(ordered) if bar.session is Session.RTH]
        premarket = [bar for bar in ordered if bar.session is Session.PREMARKET]
        if not rth:
            return None
        first_idx, first_rth = rth[0]

        if definition.kind is TriggerKind.MARKET_OPEN:
            return TriggerSignal(definition, first_rth.open, first_idx, first_rth.timestamp)
        if definition.kind is TriggerKind.PRIOR_DAY_HIGH:
            if prior_day_high is None:
                return None
            return TriggerSignal(definition, prior_day_high, first_idx, first_rth.timestamp)
        if definition.kind is TriggerKind.PREMARKET_HIGH:
            if not premarket:
                return None
            return TriggerSignal(definition, max(b.high for b in premarket), first_idx, first_rth.timestamp)
        if definition.kind in {TriggerKind.ORB_5M, TriggerKind.ORB_15M, TriggerKind.ORB_30M}:
            minutes = {TriggerKind.ORB_5M: 5, TriggerKind.ORB_15M: 15, TriggerKind.ORB_30M: 30}[definition.kind]
            cutoff = first_rth.timestamp + timedelta(minutes=minutes)
            forming = [bar for _, bar in rth if bar.timestamp < cutoff]
            active = [(idx, bar) for idx, bar in rth if bar.timestamp >= cutoff]
            if not forming or not active:
                return None
            idx, bar = active[0]
            return TriggerSignal(definition, max(b.high for b in forming), idx, bar.timestamp)
        if definition.kind is TriggerKind.BREAKOUT_RETEST:
            if prior_day_high is None:
                return None
            broke = False
            for idx, bar in rth:
                if not broke and bar.high > prior_day_high:
                    broke = True
                    continue
                if broke and bar.low <= prior_day_high <= bar.close:
                    return TriggerSignal(definition, prior_day_high, idx, bar.timestamp)
            return None
        if definition.kind is TriggerKind.VWAP_RECLAIM:
            cumulative_pv = 0.0
            cumulative_v = 0.0
            prev_close_below = False
            for idx, bar in rth:
                typical = (bar.high + bar.low + bar.close) / 3.0
                cumulative_pv += typical * bar.volume
                cumulative_v += bar.volume
                if cumulative_v <= 0:
                    continue
                vwap = cumulative_pv / cumulative_v
                if prev_close_below and bar.close >= vwap:
                    return TriggerSignal(definition, vwap, idx, bar.timestamp)
                prev_close_below = bar.close < vwap
            return None
        raise ValueError(definition.kind)

    def evaluate(
        self,
        candidate: SetupCandidate,
        bars: Sequence[MarketBar],
        definition: TriggerDefinition,
        *,
        prior_day_high: float | None = None,
        account_equity: float | None = None,
    ) -> tuple[TradePlan | TradeRejection | None, SignalOutcome | None]:
        signal = self.signal(definition, bars, prior_day_high=prior_day_high)
        if signal is None:
            return None, None
        triggered_candidate = candidate.model_copy(update={"proposed_entry": signal.entry})
        plan = self.constructor.build(triggered_candidate, account_equity=account_equity)
        if isinstance(plan, TradeRejection):
            return plan, None
        ordered = sorted(bars, key=lambda b: b.timestamp)
        outcome = self.auditor.audit(plan, ordered[signal.active_from_index :])
        return plan, outcome
