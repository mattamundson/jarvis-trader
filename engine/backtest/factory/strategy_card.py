"""Strategy Card -- the pre-registered hypothesis unit of the discovery factory.

A card commits, BEFORE any backtest, to: what the strategy is, the instruments
and timeframes its economic rationale actually supports, its default params, the
grid to sweep, and -- mandatory -- WHY it should work. Cards with no economic
rationale are killed at Phase 1 (the anti-p-hacking gate): we do not test
"RSI<30 buy" just because it is mechanically expressible.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

VALID_FAMILIES = {
    "trend",
    "meanrev",
    "breakout",
    "relative_value",
    "calendar",
    "breadth",
}

# Minimum characters of genuine rationale. A blank or one-word "momentum" fails.
MIN_RATIONALE_CHARS = 25


@dataclass
class StrategyCard:
    name: str
    family: str
    signal_ref: str  # "backtest.meanrev_signals:generate_bollinger_rsi_signals"
    entry: str
    exit: str
    economic_rationale: str
    native_instruments: list[str]
    native_timeframes: list[str]
    default_params: dict = field(default_factory=dict)
    param_grid: dict = field(default_factory=dict)  # name -> [values]
    known_failure_modes: str = ""
    prior_verdict: str | None = None

    def problems(self) -> list[str]:
        """Return a list of validation problems; empty list == card passes the gate."""
        problems: list[str] = []
        if not self.name:
            problems.append("missing name")
        if self.family not in VALID_FAMILIES:
            problems.append(f"family '{self.family}' not in {sorted(VALID_FAMILIES)}")
        if ":" not in self.signal_ref:
            problems.append("signal_ref must be 'module.path:function'")
        if len((self.economic_rationale or "").strip()) < MIN_RATIONALE_CHARS:
            problems.append(
                f"economic_rationale too thin (< {MIN_RATIONALE_CHARS} chars) -- "
                "killed by the anti-p-hacking gate"
            )
        if not self.native_instruments:
            problems.append("native_instruments empty")
        if not self.native_timeframes:
            problems.append("native_timeframes empty")
        return problems

    def is_valid(self) -> bool:
        return not self.problems()

    def n_param_combos(self) -> int:
        n = 1
        for values in self.param_grid.values():
            n *= max(1, len(values))
        return n


def save_cards(cards: list[StrategyCard], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for c in cards:
            fh.write(json.dumps(asdict(c)) + "\n")


def load_cards(path: str | Path, *, drop_invalid: bool = True) -> list[StrategyCard]:
    """Load cards from jsonl. With drop_invalid, rationale-less cards are silently
    filtered (the Phase-1 gate); otherwise an invalid card raises."""
    cards: list[StrategyCard] = []
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            card = StrategyCard(**json.loads(line))
            problems = card.problems()
            if problems:
                if drop_invalid:
                    continue
                raise ValueError(f"invalid card '{card.name}': {problems}")
            cards.append(card)
    return cards
