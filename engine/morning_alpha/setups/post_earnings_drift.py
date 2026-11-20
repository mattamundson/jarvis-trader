from morning_alpha.models import StrategyKey
from morning_alpha.setups.base import SetupContext, long_candidate, trigger_buffer


class PostEarningsDrift:
    strategy = StrategyKey(strategy_id="post_earnings_drift", version="1.0.0")

    def explain_features(self, snapshot, context: SetupContext):
        catalyst = context.catalyst
        verified_earnings = bool(
            catalyst
            and catalyst.verified
            and catalyst.catalyst_type == "earnings"
            and (catalyst.published_at is None or catalyst.published_at <= snapshot.as_of)
        )
        return {
            "verified_earnings": verified_earnings,
            "eps_surprise_pct": context.eps_surprise_pct,
            "revenue_surprise_pct": context.revenue_surprise_pct,
            "positive_surprises": bool(context.eps_surprise_pct is not None and context.eps_surprise_pct > 0 and context.revenue_surprise_pct is not None and context.revenue_surprise_pct > 0),
            "gap_pct": context.gap_pct,
            "positive_gap": bool(context.gap_pct is not None and context.gap_pct > 0),
            "gap_retention": context.gap_retention,
            "gap_held": bool(context.gap_retention is not None and context.gap_retention >= 0.5),
            "relative_volume": context.relative_volume,
            "volume_confirmed": bool(context.relative_volume is not None and context.relative_volume >= 1.5),
        }

    def evaluate(self, snapshot, context: SetupContext):
        f = self.explain_features(snapshot, context)
        if not all(f[k] for k in ("verified_earnings", "positive_surprises", "positive_gap", "gap_held", "volume_confirmed")):
            return None
        if context.prior_high is None or context.gap_low is None:
            return None
        return long_candidate(
            snapshot=snapshot,
            context=context,
            strategy=self.strategy,
            setup_type="post_earnings_drift",
            thesis_code="PEAD_V1",
            entry=context.prior_high + trigger_buffer(context),
            stop=context.gap_low,
            features=f,
        )
