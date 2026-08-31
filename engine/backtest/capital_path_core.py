"""Capital Path V1 deterministic equity-path accounting.

This module is the accounting core underneath future Monte Carlo/bootstrap
simulation. Inputs are realized/net R-multiples; position size is recomputed from
current equity on every trade, so compounding and drawdown-governor behavior are
pathwise rather than fixed-dollar.

Research only: no broker/execution authority and no claim that default risk
parameters are optimal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal


TerminalState = Literal["SUCCESS", "RUIN", "HALTED", "EXHAUSTED"]


class CapitalPathError(ValueError):
    """Raised when a capital-path configuration or return path is invalid."""


@dataclass(frozen=True)
class DrawdownBand:
    threshold: float
    risk_multiplier: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.threshold < 1.0:
            raise CapitalPathError("drawdown threshold must be in [0,1)")
        if not 0.0 <= self.risk_multiplier <= 1.0:
            raise CapitalPathError("risk multiplier must be in [0,1]")


@dataclass(frozen=True)
class RiskPolicy:
    base_risk_fraction: float = 0.005
    drawdown_bands: tuple[DrawdownBand, ...] = (
        DrawdownBand(0.05, 0.75),
        DrawdownBand(0.10, 0.50),
    )
    halt_drawdown: float | None = 0.15

    def __post_init__(self) -> None:
        if not 0.0 < self.base_risk_fraction < 1.0:
            raise CapitalPathError("base_risk_fraction must be in (0,1)")
        thresholds = [band.threshold for band in self.drawdown_bands]
        if thresholds != sorted(thresholds) or len(set(thresholds)) != len(thresholds):
            raise CapitalPathError("drawdown bands must have unique ascending thresholds")
        if self.halt_drawdown is not None:
            if not 0.0 < self.halt_drawdown < 1.0:
                raise CapitalPathError("halt_drawdown must be in (0,1)")
            if thresholds and self.halt_drawdown <= thresholds[-1]:
                raise CapitalPathError("halt_drawdown must exceed the highest drawdown band")

    def risk_fraction(self, drawdown: float) -> float:
        if drawdown < 0.0:
            raise CapitalPathError("drawdown cannot be negative")
        if self.halt_drawdown is not None and drawdown >= self.halt_drawdown:
            return 0.0
        multiplier = 1.0
        for band in self.drawdown_bands:
            if drawdown >= band.threshold:
                multiplier = band.risk_multiplier
        return self.base_risk_fraction * multiplier


@dataclass(frozen=True)
class CapitalPathConfig:
    start_equity: float = 3_000.0
    target_equity: float = 300_000.0
    milestones: tuple[float, ...] = (10_000.0, 25_000.0, 100_000.0, 300_000.0)
    ruin_equity_floor: float | None = None
    ruin_drawdown: float | None = 0.30

    def __post_init__(self) -> None:
        if self.start_equity <= 0.0:
            raise CapitalPathError("start_equity must be positive")
        if self.target_equity <= self.start_equity:
            raise CapitalPathError("target_equity must exceed start_equity")
        if any(value <= 0.0 for value in self.milestones):
            raise CapitalPathError("milestones must be positive")
        if tuple(sorted(set(self.milestones))) != self.milestones:
            raise CapitalPathError("milestones must be unique and ascending")
        if self.ruin_equity_floor is not None:
            if not 0.0 <= self.ruin_equity_floor < self.start_equity:
                raise CapitalPathError("ruin_equity_floor must be in [0,start_equity)")
        if self.ruin_drawdown is not None and not 0.0 < self.ruin_drawdown <= 1.0:
            raise CapitalPathError("ruin_drawdown must be in (0,1]")


@dataclass(frozen=True)
class CapitalPathResult:
    terminal_state: TerminalState
    terminal_trade: int
    terminal_equity: float
    target_first_passage_trade: int | None
    ruin_trade: int | None
    halt_trade: int | None
    milestone_first_passage: dict[float, int | None]
    equity_path: tuple[float, ...]
    risk_fraction_path: tuple[float, ...]
    drawdown_path: tuple[float, ...]
    max_drawdown: float
    minimum_equity: float
    longest_underwater_trades: int

    @property
    def success(self) -> bool:
        return self.terminal_state == "SUCCESS"


def simulate_r_path(
    r_multiples: Iterable[float],
    *,
    config: CapitalPathConfig | None = None,
    risk_policy: RiskPolicy | None = None,
) -> CapitalPathResult:
    """Apply a chronological sequence of net R outcomes to dynamic account equity."""
    cfg = config or CapitalPathConfig()
    policy = risk_policy or RiskPolicy()
    r_values = [float(value) for value in r_multiples]
    if any(value != value or value in (float("inf"), float("-inf")) for value in r_values):
        raise CapitalPathError("R-multiples must be finite")

    equity = cfg.start_equity
    peak = equity
    minimum_equity = equity
    equity_path = [equity]
    drawdown_path = [0.0]
    risk_path: list[float] = []
    milestones = tuple(sorted(set(cfg.milestones + (cfg.target_equity,))))
    first_passage: dict[float, int | None] = {
        milestone: (0 if equity >= milestone else None) for milestone in milestones
    }
    target_trade = first_passage[cfg.target_equity]
    ruin_trade: int | None = None
    halt_trade: int | None = None
    underwater_run = 0
    longest_underwater = 0
    terminal_state: TerminalState = "EXHAUSTED"
    terminal_trade = 0

    for trade_number, realized_r in enumerate(r_values, start=1):
        current_drawdown = 1.0 - equity / peak
        risk_fraction = policy.risk_fraction(current_drawdown)
        if risk_fraction == 0.0:
            terminal_state = "HALTED"
            halt_trade = trade_number - 1
            terminal_trade = trade_number - 1
            break

        risk_path.append(risk_fraction)
        growth_factor = 1.0 + risk_fraction * realized_r
        equity = max(0.0, equity * growth_factor)
        equity_path.append(equity)
        minimum_equity = min(minimum_equity, equity)
        peak = max(peak, equity)
        drawdown = 0.0 if peak <= 0.0 else 1.0 - equity / peak
        drawdown_path.append(drawdown)

        if equity < peak:
            underwater_run += 1
            longest_underwater = max(longest_underwater, underwater_run)
        else:
            underwater_run = 0

        for milestone in milestones:
            if first_passage[milestone] is None and equity >= milestone:
                first_passage[milestone] = trade_number
        if target_trade is None and first_passage[cfg.target_equity] is not None:
            target_trade = first_passage[cfg.target_equity]

        equity_ruin = (
            cfg.ruin_equity_floor is not None and equity <= cfg.ruin_equity_floor
        )
        drawdown_ruin = cfg.ruin_drawdown is not None and drawdown >= cfg.ruin_drawdown
        total_ruin = equity <= 0.0
        if equity_ruin or drawdown_ruin or total_ruin:
            terminal_state = "RUIN"
            ruin_trade = trade_number
            terminal_trade = trade_number
            break
        if equity >= cfg.target_equity:
            terminal_state = "SUCCESS"
            terminal_trade = trade_number
            break

        terminal_trade = trade_number
    else:
        terminal_state = "SUCCESS" if equity >= cfg.target_equity else "EXHAUSTED"
        if terminal_state == "SUCCESS" and target_trade is None:
            target_trade = terminal_trade

    return CapitalPathResult(
        terminal_state=terminal_state,
        terminal_trade=terminal_trade,
        terminal_equity=equity,
        target_first_passage_trade=target_trade,
        ruin_trade=ruin_trade,
        halt_trade=halt_trade,
        milestone_first_passage=first_passage,
        equity_path=tuple(equity_path),
        risk_fraction_path=tuple(risk_path),
        drawdown_path=tuple(drawdown_path),
        max_drawdown=max(drawdown_path),
        minimum_equity=minimum_equity,
        longest_underwater_trades=longest_underwater,
    )
