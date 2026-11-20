from morning_alpha.models import StrategyKey
from morning_alpha.setups.base import SetupContext, long_candidate, trigger_buffer


class MomentumBreakout:
    strategy = StrategyKey(strategy_id="momentum_breakout", version="1.0.0")

    def explain_features(self, snapshot, context: SetupContext):
        relative_volume_ok = context.relative_volume is None or context.relative_volume >= 1.5
        return {
            "return_percentile_20d": context.return_percentile_20d,
            "momentum_rank_ok": bool(context.return_percentile_20d is not None and context.return_percentile_20d >= 80),
            "trend_ok": bool(context.sma20 and context.sma50 and snapshot.price > context.sma20 > context.sma50),
            "relative_volume": context.relative_volume,
            "relative_volume_ok": relative_volume_ok,
            "high_20d": context.high_20d,
        }

    def evaluate(self, snapshot, context: SetupContext):
        f = self.explain_features(snapshot, context)
        if not (f["momentum_rank_ok"] and f["trend_ok"] and f["relative_volume_ok"]):
            return None
        if context.high_20d is None or context.prior_low is None:
            return None
        return long_candidate(
            snapshot=snapshot,
            context=context,
            strategy=self.strategy,
            setup_type="momentum_breakout",
            thesis_code="MOM_V1",
            entry=context.high_20d + trigger_buffer(context),
            stop=context.prior_low,
            features=f,
        )
