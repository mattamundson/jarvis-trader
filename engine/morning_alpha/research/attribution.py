from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class EdgeAttribution(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy_return: float
    next_open_return: float
    sector_return: float
    market_return: float
    total_increment: float
    components: dict[str, float]
    reconciles: bool


class EdgeAttributionEngine:
    def attribute(
        self,
        strategy_return: float,
        next_open_return: float,
        sector_return: float,
        market_return: float,
        *,
        exit_adjustment: float = 0.0,
        filter_adjustment: float = 0.0,
    ) -> EdgeAttribution:
        total_increment = strategy_return - market_return
        components = {
            "sector_increment": sector_return - market_return,
            "selection_increment": next_open_return - sector_return,
            "timing_increment": strategy_return - next_open_return,
            "exit_adjustment": exit_adjustment,
            "filter_adjustment": filter_adjustment,
        }
        residual = total_increment - sum(components.values())
        components["residual"] = residual
        reconciles = abs(sum(components.values()) - total_increment) <= 1e-12
        return EdgeAttribution(
            strategy_return=strategy_return,
            next_open_return=next_open_return,
            sector_return=sector_return,
            market_return=market_return,
            total_increment=total_increment,
            components=components,
            reconciles=reconciles,
        )
