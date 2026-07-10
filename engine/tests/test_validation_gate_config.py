"""
Regression coverage for engine/paper/validation_gate_config.py.

APPROVED_PAPER_SYMBOLS previously listed the two halted symbols (MCL, MNQ)
and omitted MGC, an active approved paper instrument. This is a sibling gap
to the DO_NOT_TRADE_SYMBOLS hard block added to SafetyLayer.check_order()
(T0-01) -- same bug class, one file removed from order execution: the
/paper/validation/approved-paper-gates endpoint iterates this tuple to
report per-symbol validation gate status.
"""

from backtest.signals import DO_NOT_TRADE_SYMBOLS
from paper.validation_gate_config import APPROVED_PAPER_SYMBOLS


class TestApprovedPaperSymbols:
    """Halted-symbol exclusion + active-symbol inclusion for the paper validation gate list."""

    def test_halted_symbols_excluded(self):
        """MCL and MNQ (DO_NOT_TRADE_SYMBOLS) must never appear in the approved list."""
        for symbol in DO_NOT_TRADE_SYMBOLS:
            assert symbol not in APPROVED_PAPER_SYMBOLS, (
                f"{symbol} is halted (DO_NOT_TRADE_SYMBOLS) but still listed in "
                "APPROVED_PAPER_SYMBOLS"
            )

    def test_active_symbols_included(self):
        """MES and MGC are the currently-active approved paper instruments."""
        assert "MES" in APPROVED_PAPER_SYMBOLS
        assert "MGC" in APPROVED_PAPER_SYMBOLS

    def test_no_duplicates(self):
        assert len(APPROVED_PAPER_SYMBOLS) == len(set(APPROVED_PAPER_SYMBOLS))
