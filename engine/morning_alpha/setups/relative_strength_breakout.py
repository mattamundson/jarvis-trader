from morning_alpha.models import StrategyKey
from morning_alpha.setups.base import SetupContext, long_candidate, trigger_buffer


class RelativeStrengthBreakout:
    strategy = StrategyKey(strategy_id="relative_strength_breakout", version="1.0.0")

    def explain_features(self, snapshot, context: SetupContext):
        high = context.high_252d or snapshot.high_52w
        return {
            "near_52w_high": bool(high and snapshot.price >= 0.98 * high),
            "return_20d": context.returns_20d,
            "spy_return_20d": context.spy_return_20d,
            "sector_return_20d": context.sector_return_20d,
            "beats_spy": bool(context.returns_20d is not None and context.spy_return_20d is not None and context.returns_20d > context.spy_return_20d),
            "beats_sector": bool(context.returns_20d is not None and context.sector_return_20d is not None and context.returns_20d > context.sector_return_20d),
            "trend_ok": bool(context.sma20 and context.sma50 and snapshot.price > context.sma20 > context.sma50),
            "atr14": context.atr14,
        }

    def evaluate(self, snapshot, context: SetupContext):
        f = self.explain_features(snapshot, context)
        if not all(f[k] for k in ("near_52w_high", "beats_spy", "beats_sector", "trend_ok")):
            return None
        if context.prior_high is None or context.prior_low is None:
            return None
        return long_candidate(
            snapshot=snapshot,
            context=context,
            strategy=self.strategy,
            setup_type="relative_strength_breakout",
            thesis_code="RSB_V1",
            entry=context.prior_high + trigger_buffer(context),
            stop=context.prior_low,
            features=f,
            nearby_obstacle=context.high_252d or snapshot.high_52w,
        )
