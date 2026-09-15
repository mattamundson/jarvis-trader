from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from morning_alpha.models import MarketBar, OutcomeClassification, SignalOutcome, TradePlan


@dataclass(frozen=True)
class _EntryState:
    triggered: bool
    entry_index: int | None


class OutcomeAuditor:
    """Audit a trade plan against subsequent OHLC bars without favorable sequencing assumptions."""

    def audit(self, plan: TradePlan, bars: Sequence[MarketBar]) -> SignalOutcome:
        ordered = sorted(bars, key=lambda bar: bar.timestamp)
        eligible = [bar for bar in ordered if bar.timestamp >= plan.as_of]
        if not eligible:
            return SignalOutcome(
                symbol=plan.symbol,
                strategy=plan.strategy,
                signal_as_of=plan.as_of,
                evaluated_as_of=plan.as_of,
                triggered=False,
                classification=OutcomeClassification.UNVERIFIED,
            )

        state = self._find_entry(plan, eligible)
        evaluated_as_of = eligible[-1].timestamp

        if not state.triggered or state.entry_index is None:
            first_ref = eligible[0].open
            final_close = eligible[-1].close
            winner = final_close > first_ref if plan.side == "long" else final_close < first_ref
            return SignalOutcome(
                symbol=plan.symbol,
                strategy=plan.strategy,
                signal_as_of=plan.as_of,
                evaluated_as_of=evaluated_as_of,
                triggered=False,
                classification=(
                    OutcomeClassification.FILTERED_WINNER
                    if winner
                    else OutcomeClassification.FILTERED_LOSER
                ),
            )

        post = eligible[state.entry_index :]
        entry = plan.entry
        risk = plan.risk_per_share
        direction = 1.0 if plan.side == "long" else -1.0

        mfe_r = max(self._favorable_r(plan, bar) for bar in post)
        mae_r = min(self._adverse_r(plan, bar) for bar in post)

        reached = {r: False for r in (1, 2, 3, 4)}
        stop_hit = False
        ambiguous = False
        decisive_classification: OutcomeClassification | None = None

        for idx, bar in enumerate(post):
            hit_stop = self._hits_stop(plan, bar)
            hit_targets = [r for r in (1, 2, 3, 4) if self._hits_r(plan, bar, float(r))]

            if idx == 0 and hit_stop:
                ambiguous = True
                break

            new_targets = [r for r in hit_targets if not reached[r]]
            if hit_stop and new_targets:
                ambiguous = True
                break

            for r in hit_targets:
                reached[r] = True

            if hit_stop:
                stop_hit = True
                decisive_classification = OutcomeClassification.LOSS
                break

            if reached[2]:
                decisive_classification = OutcomeClassification.WIN
                break

        if ambiguous:
            classification = OutcomeClassification.UNVERIFIED
            stop_value: bool | None = None
        elif decisive_classification is not None:
            classification = decisive_classification
            stop_value = stop_hit
        else:
            classification = OutcomeClassification.OPEN
            stop_value = False

        close_r = direction * (eligible[-1].close - entry) / risk

        return SignalOutcome(
            symbol=plan.symbol,
            strategy=plan.strategy,
            signal_as_of=plan.as_of,
            evaluated_as_of=evaluated_as_of,
            triggered=True,
            classification=classification,
            entry_price=entry,
            mfe_r=mfe_r,
            mae_r=mae_r,
            close_r=close_r,
            stop_hit=stop_value,
            reached_1r=reached[1],
            reached_2r=reached[2],
            reached_3r=reached[3],
            reached_4r=reached[4],
        )

    @staticmethod
    def _find_entry(plan: TradePlan, bars: Sequence[MarketBar]) -> _EntryState:
        for idx, bar in enumerate(bars):
            if plan.side == "long" and bar.high >= plan.entry:
                return _EntryState(True, idx)
            if plan.side == "short" and bar.low <= plan.entry:
                return _EntryState(True, idx)
        return _EntryState(False, None)

    @staticmethod
    def _hits_stop(plan: TradePlan, bar: MarketBar) -> bool:
        return bar.low <= plan.stop if plan.side == "long" else bar.high >= plan.stop

    @staticmethod
    def _hits_r(plan: TradePlan, bar: MarketBar, r: float) -> bool:
        target = plan.entry + (
            r * plan.risk_per_share if plan.side == "long" else -r * plan.risk_per_share
        )
        return bar.high >= target if plan.side == "long" else bar.low <= target

    @staticmethod
    def _favorable_r(plan: TradePlan, bar: MarketBar) -> float:
        if plan.side == "long":
            return (bar.high - plan.entry) / plan.risk_per_share
        return (plan.entry - bar.low) / plan.risk_per_share

    @staticmethod
    def _adverse_r(plan: TradePlan, bar: MarketBar) -> float:
        if plan.side == "long":
            return (bar.low - plan.entry) / plan.risk_per_share
        return (plan.entry - bar.high) / plan.risk_per_share
