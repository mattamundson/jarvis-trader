from morning_alpha.models import StrategyKey
from morning_alpha.setups.base import SetupContext, long_candidate, trigger_buffer


class PullbackContinuation:
    strategy = StrategyKey(strategy_id="pullback_continuation", version="1.0.0")

    def explain_features(self, snapshot, context: SetupContext):
        trend_ok = bool(context.sma20 and context.sma50 and snapshot.price > context.sma50 and context.sma20 > context.sma50)
        anchors = [x for x in (context.ema8, context.ema21) if x is not None]
        anchor = min(anchors) if anchors else None
        pullback_near_ema_zone = bool(anchor is not None and context.pullback_low is not None and context.atr14 and abs(context.pullback_low - anchor) <= context.atr14)
        no_50sma_break = bool(context.sma50 is not None and context.pullback_low is not None and context.pullback_low >= context.sma50)
        return {
            "trend_ok": trend_ok,
            "pullback_near_ema_zone": pullback_near_ema_zone,
            "no_50sma_break": no_50sma_break,
            "ema8": context.ema8,
            "ema21": context.ema21,
            "sma50": context.sma50,
            "pullback_low": context.pullback_low,
        }

    def evaluate(self, snapshot, context: SetupContext):
        f = self.explain_features(snapshot, context)
        if not all(f[k] for k in ("trend_ok", "pullback_near_ema_zone", "no_50sma_break")):
            return None
        if context.prior_bar_high is None or context.pullback_low is None:
            return None
        return long_candidate(
            snapshot=snapshot,
            context=context,
            strategy=self.strategy,
            setup_type="pullback_continuation",
            thesis_code="PULLBACK_V1",
            entry=context.prior_bar_high + trigger_buffer(context),
            stop=context.pullback_low,
            features=f,
        )
