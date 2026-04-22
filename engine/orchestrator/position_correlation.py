"""
Position Correlation Monitor — tracks instrument-pair exposure.
Applies sizing rules when correlated instruments have simultaneous open positions.

MNQ and MES are equity index futures with ~0.95 correlation.
When both have open positions simultaneously, max_contracts reduces to 1 each.
"""

from __future__ import annotations

import logging

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
        symbol = symbol.upper()
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

        If *symbol* is part of a high-correlation pair and BOTH symbols
        have open positions, returns correlated_max_contracts (usually 1).
        Otherwise returns default_max_contracts (usually 2).
        """
        open_symbols_upper = {s.upper() for s in self._open_positions}
        symbol_upper = symbol.upper()

        # Check all correlation pairs
        for pair_str, corr_value in self.correlation_pairs.items():
            if corr_value < self.correlation_threshold:
                continue

            parts = pair_str.split("-")
            if len(parts) != 2:
                logger.warning(f"Invalid correlation pair format: {pair_str}")
                continue

            sym1 = parts[0].strip().upper()
            sym2 = parts[1].strip().upper()

            # Both symbols must be open to trigger reduction
            if symbol_upper in (sym1, sym2):
                other = sym2 if symbol_upper == sym1 else sym1
                if symbol_upper in open_symbols_upper and other in open_symbols_upper:
                    logger.info(
                        f"Correlation reduction applied: {sym1}+{sym2} both open, "
                        f"max_contracts -> {self.correlated_max_contracts}"
                    )
                    return self.correlated_max_contracts

        return self.default_max_contracts

    def get_correlation_exposure(self) -> dict:
        """Return current correlation exposure status."""
        open_symbols_upper = {s.upper() for s in self._open_positions}
        reduction_active = False

        # Check if any high-correlation pair is open
        for pair_str, corr_value in self.correlation_pairs.items():
            if corr_value < self.correlation_threshold:
                continue

            parts = pair_str.split("-")
            if len(parts) != 2:
                continue

            sym1 = parts[0].strip().upper()
            sym2 = parts[1].strip().upper()
            if sym1 in open_symbols_upper and sym2 in open_symbols_upper:
                reduction_active = True
                break

        return {
            "open_symbols": list(open_symbols_upper),
            "open_count": len(open_symbols_upper),
            "correlation_reduction_active": reduction_active,
            "default_max_contracts": self.default_max_contracts,
            "correlated_max_contracts": self.correlated_max_contracts,
        }
