"""
Position Correlation Monitor — tracks instrument-pair exposure.
Applies sizing rules when correlated instruments have simultaneous open positions.

MNQ and MES are equity index futures with ~0.95 correlation.
When both have open positions simultaneously, max_contracts reduces to 1 each.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("jarvis_trader.orchestrator.position_correlation")


class PositionCorrelationMonitor:
    """
    Monitors open positions across instruments and applies correlation-aware
    sizing constraints when multiple high-correlation instruments have positions.
    """

    def __init__(
        self,
        correlation_pairs: dict[str, float],
        correlation_threshold: float = 0.80,
        default_max_contracts: int = 2,
        correlated_max_contracts: int = 1,
    ):
        """
        Args:
            correlation_pairs: dict of "SYMBOL1-SYMBOL2": correlation_value
            correlation_threshold: Correlation >= this triggers sizing rule
            default_max_contracts: Normal max contracts per instrument
            correlated_max_contracts: Reduced max when both in pair are open
        """
        self.correlation_pairs = correlation_pairs
        self.correlation_threshold = correlation_threshold
        self.default_max_contracts = default_max_contracts
        self.correlated_max_contracts = correlated_max_contracts
        self._open_positions: dict[str, int] = {}  # symbol -> qty

    def update_position(self, symbol: str, qty: int) -> None:
        """Update the open quantity for a symbol (0 = closed position)."""
        if qty > 0:
            self._open_positions[symbol] = qty
        else:
            self._open_positions.pop(symbol, None)

    def get_open_symbols(self) -> set[str]:
        """Return set of symbols with open positions."""
        return set(self._open_positions.keys())

    def get_max_contracts(self, symbol: str) -> int:
        """
        Get the max contracts allowed for *symbol* given current open positions.

        If *symbol* is part of a high-correlation pair and the other symbol
        also has an open position, returns correlated_max_contracts (usually 1).
        Otherwise returns default_max_contracts (usually 2).
        """
        open_symbols = self.get_open_symbols()

        # Check all correlation pairs
        for pair_str, corr_value in self.correlation_pairs.items():
            if corr_value < self.correlation_threshold:
                continue

            parts = pair_str.split("-")
            if len(parts) != 2:
                logger.warning(f"Invalid correlation pair format: {pair_str}")
                continue

            sym1, sym2 = parts[0].strip(), parts[1].strip()

            # Check if symbol is in this pair and other symbol is open
            if symbol.upper() == sym1.upper() and sym2.upper() in open_symbols:
                logger.info(
                    f"Correlation reduction applied: {sym1}+{sym2} both open, "
                    f"max_contracts → {self.correlated_max_contracts}"
                )
                return self.correlated_max_contracts

            if symbol.upper() == sym2.upper() and sym1.upper() in open_symbols:
                logger.info(
                    f"Correlation reduction applied: {sym1}+{sym2} both open, "
                    f"max_contracts → {self.correlated_max_contracts}"
                )
                return self.correlated_max_contracts

        return self.default_max_contracts

    def get_correlation_exposure(self) -> dict:
        """Return current correlation exposure status."""
        open_symbols = self.get_open_symbols()
        reduction_active = False

        # Check if any high-correlation pair is open
        for pair_str, corr_value in self.correlation_pairs.items():
            if corr_value < self.correlation_threshold:
                continue

            parts = pair_str.split("-")
            if len(parts) != 2:
                continue

            sym1, sym2 = parts[0].strip(), parts[1].strip()
            if sym1.upper() in open_symbols and sym2.upper() in open_symbols:
                reduction_active = True
                break

        return {
            "open_symbols": list(open_symbols),
            "open_count": len(open_symbols),
            "correlation_reduction_active": reduction_active,
            "default_max_contracts": self.default_max_contracts,
            "correlated_max_contracts": self.correlated_max_contracts,
        }
