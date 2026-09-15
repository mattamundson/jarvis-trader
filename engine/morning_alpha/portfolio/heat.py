from __future__ import annotations

from collections import defaultdict
from enum import StrEnum
from typing import Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from morning_alpha.config import MorningAlphaConfig
from morning_alpha.models import TradePlan


class HeatRejectionReason(StrEnum):
    SINGLE_TRADE_LIMIT = "single_trade_limit"
    TOTAL_HEAT_LIMIT = "total_heat_limit"
    THEME_HEAT_LIMIT = "theme_heat_limit"
    CORRELATION_LIMIT = "correlation_limit"


class HeatViolation(BaseModel):
    model_config = ConfigDict(frozen=True)

    reason: HeatRejectionReason
    detail: str
    symbols: tuple[str, ...] = ()


class PortfolioHeatResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    accepted: bool
    total_heat: float = Field(ge=0)
    theme_heat: dict[str, float]
    violations: tuple[HeatViolation, ...] = ()


class PortfolioHeatEngine:
    """Hard portfolio-risk gate for Morning Alpha trade plans."""

    def __init__(
        self,
        config: MorningAlphaConfig | None = None,
        *,
        max_pair_correlation: float = 0.80,
    ) -> None:
        self.config = config or MorningAlphaConfig()
        self.max_pair_correlation = max_pair_correlation

    @staticmethod
    def actual_heat(plan: TradePlan) -> float:
        return plan.max_dollar_risk / plan.account_equity

    def evaluate(
        self,
        plans: Sequence[TradePlan],
        *,
        correlations: Mapping[tuple[str, str], float] | None = None,
    ) -> PortfolioHeatResult:
        if not plans:
            return PortfolioHeatResult(accepted=True, total_heat=0.0, theme_heat={})

        violations: list[HeatViolation] = []
        theme_heat: dict[str, float] = defaultdict(float)
        theme_symbols: dict[str, list[str]] = defaultdict(list)
        total_heat = 0.0

        for plan in plans:
            heat = self.actual_heat(plan)
            total_heat += heat
            if heat > self.config.max_risk_fraction + 1e-12:
                violations.append(
                    HeatViolation(
                        reason=HeatRejectionReason.SINGLE_TRADE_LIMIT,
                        detail=(
                            f"{plan.symbol} actual heat {heat:.4%} exceeds "
                            f"{self.config.max_risk_fraction:.4%}"
                        ),
                        symbols=(plan.symbol,),
                    )
                )
            if plan.theme:
                theme_heat[plan.theme] += heat
                theme_symbols[plan.theme].append(plan.symbol)

        if total_heat > self.config.max_initial_portfolio_heat + 1e-12:
            violations.append(
                HeatViolation(
                    reason=HeatRejectionReason.TOTAL_HEAT_LIMIT,
                    detail=(
                        f"portfolio heat {total_heat:.4%} exceeds "
                        f"{self.config.max_initial_portfolio_heat:.4%}"
                    ),
                    symbols=tuple(plan.symbol for plan in plans),
                )
            )

        for theme, heat in sorted(theme_heat.items()):
            if heat > self.config.max_theme_heat + 1e-12:
                violations.append(
                    HeatViolation(
                        reason=HeatRejectionReason.THEME_HEAT_LIMIT,
                        detail=(
                            f"theme {theme} heat {heat:.4%} exceeds "
                            f"{self.config.max_theme_heat:.4%}"
                        ),
                        symbols=tuple(sorted(theme_symbols[theme])),
                    )
                )

        if correlations:
            by_symbol = {plan.symbol: plan for plan in plans}
            for pair, corr in sorted(correlations.items()):
                a, b = pair
                if a not in by_symbol or b not in by_symbol:
                    continue
                if corr < self.max_pair_correlation:
                    continue
                combined = self.actual_heat(by_symbol[a]) + self.actual_heat(by_symbol[b])
                if combined > self.config.max_theme_heat + 1e-12:
                    violations.append(
                        HeatViolation(
                            reason=HeatRejectionReason.CORRELATION_LIMIT,
                            detail=(
                                f"{a}/{b} correlation {corr:.2f} with combined heat "
                                f"{combined:.4%} exceeds correlated-risk ceiling "
                                f"{self.config.max_theme_heat:.4%}"
                            ),
                            symbols=tuple(sorted((a, b))),
                        )
                    )

        return PortfolioHeatResult(
            accepted=not violations,
            total_heat=total_heat,
            theme_heat=dict(sorted(theme_heat.items())),
            violations=tuple(violations),
        )
