from __future__ import annotations

from enum import StrEnum
from math import floor
from typing import Sequence

from pydantic import BaseModel, ConfigDict

from morning_alpha.config import MorningAlphaConfig
from morning_alpha.models import SetupCandidate, TradePlan


class TradeRejectionReason(StrEnum):
    INVALID_LEVELS = "invalid_levels"
    ZERO_SHARES = "zero_shares"
    INSUFFICIENT_REWARD = "insufficient_reward"


class TradeRejection(BaseModel):
    model_config = ConfigDict(frozen=True)
    symbol: str
    reason: TradeRejectionReason
    detail: str


class TradeConstructor:
    def __init__(self, config: MorningAlphaConfig | None = None) -> None:
        self.config = config or MorningAlphaConfig()

    def build(
        self,
        candidate: SetupCandidate,
        *,
        account_equity: float | None = None,
        requested_risk_fraction: float | None = None,
        obstacles: Sequence[float] = (),
    ) -> TradePlan | TradeRejection:
        equity = account_equity if account_equity is not None else self.config.account_equity
        requested = (
            requested_risk_fraction
            if requested_risk_fraction is not None
            else self.config.default_risk_fraction
        )
        risk_fraction = min(requested, self.config.max_risk_fraction)
        entry = candidate.proposed_entry
        stop = candidate.proposed_stop
        if equity <= 0 or risk_fraction <= 0:
            return TradeRejection(
                symbol=candidate.symbol,
                reason=TradeRejectionReason.INVALID_LEVELS,
                detail="equity and risk fraction must be positive",
            )
        if candidate.side == "long" and stop >= entry:
            return TradeRejection(
                symbol=candidate.symbol,
                reason=TradeRejectionReason.INVALID_LEVELS,
                detail="long stop must be below entry",
            )
        if candidate.side == "short" and stop <= entry:
            return TradeRejection(
                symbol=candidate.symbol,
                reason=TradeRejectionReason.INVALID_LEVELS,
                detail="short stop must be above entry",
            )

        risk_per_share = abs(entry - stop)
        if risk_per_share <= 0:
            return TradeRejection(
                symbol=candidate.symbol,
                reason=TradeRejectionReason.INVALID_LEVELS,
                detail="entry-stop risk must be positive",
            )

        risk_budget = equity * risk_fraction
        risk_limited_shares = floor(risk_budget / risk_per_share)
        capital_limited_shares = floor(equity / entry)
        shares = min(risk_limited_shares, capital_limited_shares)
        if shares < 1:
            return TradeRejection(
                symbol=candidate.symbol,
                reason=TradeRejectionReason.ZERO_SHARES,
                detail="risk/capital constraints size position below one share",
            )

        credible_r = self._credible_reward_r(candidate, obstacles, risk_per_share)
        if credible_r < self.config.min_expected_r:
            return TradeRejection(
                symbol=candidate.symbol,
                reason=TradeRejectionReason.INSUFFICIENT_REWARD,
                detail=(
                    f"credible reward {credible_r:.2f}R is below "
                    f"{self.config.min_expected_r:.2f}R"
                ),
            )

        target_rs = (1.0, 2.0, 3.0, 4.0)
        direction = 1.0 if candidate.side == "long" else -1.0
        targets = tuple(entry + direction * r * risk_per_share for r in target_rs)
        return TradePlan(
            symbol=candidate.symbol,
            strategy=candidate.strategy,
            as_of=candidate.as_of,
            side=candidate.side,
            entry=entry,
            stop=stop,
            targets=targets,
            risk_per_share=risk_per_share,
            account_equity=equity,
            risk_fraction=risk_fraction,
            shares=shares,
            max_dollar_risk=shares * risk_per_share,
            expected_r=credible_r,
            sector=candidate.sector,
            theme=candidate.theme,
        )

    @staticmethod
    def _credible_reward_r(
        candidate: SetupCandidate,
        obstacles: Sequence[float],
        risk_per_share: float,
    ) -> float:
        all_obstacles = list(obstacles)
        if candidate.nearby_obstacle is not None:
            all_obstacles.append(candidate.nearby_obstacle)
        if candidate.side == "long":
            favorable = [x for x in all_obstacles if x > candidate.proposed_entry]
            if not favorable:
                return 4.0
            nearest = min(favorable)
            return min(4.0, (nearest - candidate.proposed_entry) / risk_per_share)
        favorable = [x for x in all_obstacles if x < candidate.proposed_entry]
        if not favorable:
            return 4.0
        nearest = max(favorable)
        return min(4.0, (candidate.proposed_entry - nearest) / risk_per_share)
