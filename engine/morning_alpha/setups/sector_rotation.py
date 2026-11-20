from math import ceil

from morning_alpha.models import StrategyKey
from morning_alpha.setups.base import SetupContext, long_candidate, trigger_buffer


class SectorRotation:
    strategy = StrategyKey(strategy_id="sector_rotation", version="1.0.0")

    def explain_features(self, snapshot, context: SetupContext):
        top_rank = max(1, ceil(context.sector_count * 0.25))
        return {
            "sector_rank": context.sector_rank,
            "sector_count": context.sector_count,
            "top_quartile": bool(context.sector_rank is not None and context.sector_rank <= top_rank),
            "returns_20d": context.returns_20d,
            "spy_return_20d": context.spy_return_20d,
            "sector_return_20d": context.sector_return_20d,
            "beats_spy": bool(context.returns_20d is not None and context.spy_return_20d is not None and context.returns_20d > context.spy_return_20d),
            "beats_sector": bool(context.returns_20d is not None and context.sector_return_20d is not None and context.returns_20d > context.sector_return_20d),
            "trend_ok": bool(context.sma20 and context.sma50 and snapshot.price > context.sma20 > context.sma50),
        }

    def evaluate(self, snapshot, context: SetupContext):
        f = self.explain_features(snapshot, context)
        if not all(f[k] for k in ("top_quartile", "beats_spy", "beats_sector", "trend_ok")):
            return None
        if context.prior_high is None or context.prior_low is None:
            return None
        return long_candidate(
            snapshot=snapshot,
            context=context,
            strategy=self.strategy,
            setup_type="sector_rotation",
            thesis_code="SECTOR_ROT_V1",
            entry=context.prior_high + trigger_buffer(context),
            stop=context.prior_low,
            features=f,
        )
