"""The test suite must be structurally incapable of writing the production ledger.

Root cause (2026-07-21 forensics): ``PaperTradeLogger.__init__`` documented its
``trades_file`` argument as an "Override JSON path (tests)", but nothing enforced
that tests actually pass it -- and the one caller that matters,
``IBGatewayConnector``, constructs the logger with no override at all. Handing
``tmp_path`` to ``PortfolioTracker`` redirected only the tracker book; the JSON
ledger kept resolving to ``engine/data/paper_trades.json`` under the repo.

The result: every test run that placed a paper order appended rows to production
data. The contamination is visible in the ledger itself -- MGC 2300.0 / 2310.0 and
MES 5300.0 / 7490.0 rows carrying the exact second-resolution timestamps of
test-suite invocations, interleaved with real entries. G2 readiness scores that
file, so the win rate it reported was computed over a mixture of real fills,
mock-table constants, and pytest fixtures.

Two independent defects produced the phantom track record. The mock quote table
(see ``test_paper_fill_refuses_mock_price.py``) fabricated *prices*. This one
fabricated *rows*. Fixing only the first would have left the ledger poisoned.

The contract pinned here: with ``PYTEST_CURRENT_TEST`` set, the default path must
resolve outside the repo. Tests still exercise the real write path -- they just
cannot reach production data.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from config import settings
from execution.paper_trade_logger import PaperTradeLogger

# engine/tests/ -> engine/
_ENGINE_ROOT = Path(__file__).resolve().parent.parent
_REPO_LEDGER = _ENGINE_ROOT / "data" / "paper_trades.json"


def _make_logger(**kwargs) -> PaperTradeLogger:
    # The class emits a DeprecationWarning by design (SQLite is the source of
    # truth); that is not what these tests are about.
    with pytest.warns(DeprecationWarning):
        return PaperTradeLogger(settings, **kwargs)


def test_default_path_under_pytest_is_not_the_repo_ledger() -> None:
    """The core guarantee: no override -> still never the production file."""
    logger = _make_logger()
    resolved = Path(logger._trades_file).resolve()

    assert resolved != _REPO_LEDGER, (
        "PaperTradeLogger defaulted to the production ledger while under pytest -- "
        "test runs would append rows to real paper-trade data"
    )
    assert _ENGINE_ROOT not in resolved.parents, (
        f"ledger path {resolved} resolves inside the repo at {_ENGINE_ROOT}"
    )


def test_explicit_override_is_still_honored(tmp_path) -> None:
    """The documented override keeps working -- the guard is additive."""
    target = tmp_path / "ledger.json"
    logger = _make_logger(trades_file=target)

    assert Path(logger._trades_file) == target


@pytest.mark.asyncio
async def test_connector_constructed_logger_also_avoids_the_repo(tmp_path) -> None:
    """The real production caller passes no override -- it must be safe anyway.

    This is the exact shape that contaminated the ledger: IBGatewayConnector
    builds its own PaperTradeLogger internally (lazily, inside ``connect()``), so
    no amount of tmp_path discipline at the test boundary could redirect it.
    """
    from execution.ib_gateway_connector import IBGatewayConnector
    from portfolio.tracker import PortfolioTracker
    from risk.safety_layer import SafetyLayer

    cfg = settings.model_copy(
        update={
            "LIVE_TRADING_ENABLED": False,
            "REQUIRE_HUMAN_APPROVAL": True,
            "PAPER_TRADING": True,
            "ALLOW_PAPER_SIMULATED_ORDERS": True,
        }
    )
    conn = IBGatewayConnector(
        cfg,
        SafetyLayer(cfg, pnl_monitor=None),
        portfolio_tracker=PortfolioTracker(store_path=tmp_path / "book.jsonl"),
    )
    assert await conn.connect() is True

    trade_logger = conn._paper_trade_logger
    assert trade_logger is not None, "connect() did not build the paper trade logger"

    resolved = Path(trade_logger._trades_file).resolve()
    assert resolved != _REPO_LEDGER, (
        "the connector's own logger points at the production ledger -- this is the "
        "exact path that wrote pytest fixture prices into real paper-trade data"
    )
