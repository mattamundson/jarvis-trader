from morning_alpha.models import StrategyKey
from morning_alpha.setups.base import SetupContext, long_candidate, trigger_buffer


class GapContinuation:
    strategy = StrategyKey(strategy_id="gap_continuation", version="1.0.0")

    def explain_features(self, snapshot, context: SetupContext):
        return {
            "gap_pct": context.gap_pct,
            "gap_size_ok": bool(context.gap_pct is not None and context.gap_pct >= 0.03),
            "gap_retention": context.gap_retention,
            "gap_held": bool(context.gap_retention is not None and context.gap_retention >= 0.5),
            "relative_volume": context.relative_volume,
            "volume_confirmed": bool(context.relative_volume is not None and context.relative_volume >= 1.5),
            "prior_close": context.prior_close,
        }

    def evaluate(self, snapshot, context: SetupContext):
        f = self.explain_features(snapshot, context)
        if not all(f[k] for k in ("gap_size_ok", "gap_held", "volume_confirmed")):
            return None
        if context.prior_high is None or context.prior_close is None:
            return None
        return long_candidate(
            snapshot=snapshot,
            context=context,
            strategy=self.strategy,
            setup_type="gap_continuation",
            thesis_code="GAP_CONT_V1",
            entry=context.prior_high + trigger_buffer(context),
            stop=context.prior_close,
            features=f,
        )
