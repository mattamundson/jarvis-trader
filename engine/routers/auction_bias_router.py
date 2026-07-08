"""ES/MES auction overnight-bias endpoint (advisory).

Serves the deterministic synthesis from analysis.auction_bias as
``GET /auction/bias/{symbol}`` with an honest LIVE/STATIC provenance block.

Decision-support ONLY: no order sizing, no routing. The numbers are engine-derived
(Saty ATR + TPO + ingested Corey commentary), NOT a mirror of the ThinkOrSwim chart.

The endpoint reads its raw inputs through an injected ``AuctionDataProvider`` so the
synthesis + provenance wiring is unit-testable with a fake provider. The concrete
live provider (data_manager price + ATR + tpo_profile + Corey analyst) is wired in
main.py on the engine host — see docs/design/es-auction-overnight-bias-card.md.
"""

import logging
import time
from typing import Optional, Protocol

from fastapi import APIRouter, HTTPException

from analysis.auction_bias import synthesize_auction_bias
from data.provenance import DEFAULT_STALE_AFTER_S, derive_is_live

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["auction", "market"])

# v1 default: MES only (the primary active equity-index micro). MGC is a one-line
# add here once its TPO/Corey inputs are confirmed — see the design doc.
ALLOWED_SYMBOLS = {"MES"}


class AuctionDataProvider(Protocol):
    """Supplies the raw synthesis inputs for a symbol.

    Implementations return a dict with at least ``price``, ``prior_close`` and
    ``atr``; optionally ``day_range``, ``tpo``, ``corey``, plus provenance hints
    ``source`` (str), ``as_of`` (epoch s) and ``ibkr_connected`` (bool). Returns
    None when no usable data is available.
    """

    def get_inputs(self, symbol: str) -> Optional[dict]: ...


_provider: Optional[AuctionDataProvider] = None


def inject_dependencies(provider: AuctionDataProvider) -> None:
    """Inject the concrete data provider from main.py."""
    global _provider
    _provider = provider


def _unavailable(symbol: str, reason: str) -> dict:
    return {
        "symbol": symbol,
        "available": False,
        "is_live": False,
        "source": "unavailable",
        "as_of": None,
        "stale_after_s": DEFAULT_STALE_AFTER_S,
        "error": reason,
    }


@router.get("/auction/bias/{symbol}")
async def get_auction_bias(symbol: str) -> dict:
    """Advisory auction / overnight-bias read for an active symbol."""
    sym = symbol.strip().upper()
    if sym not in ALLOWED_SYMBOLS:
        raise HTTPException(
            status_code=400,
            detail=f"{sym} not enabled for auction bias (allowed: {sorted(ALLOWED_SYMBOLS)})",
        )
    if _provider is None:
        raise HTTPException(status_code=503, detail="auction data provider not wired")

    try:
        raw = _provider.get_inputs(sym)
    except Exception as exc:  # provider failure must not 500 the card
        logger.error("auction bias provider failed for %s: %s", sym, exc)
        return _unavailable(sym, f"provider error: {exc}")

    if not raw or raw.get("price") is None or raw.get("prior_close") is None or not raw.get("atr"):
        return _unavailable(sym, "insufficient market data (need price, prior_close, atr)")

    try:
        payload = synthesize_auction_bias(
            symbol=sym,
            price=raw["price"],
            prior_close=raw["prior_close"],
            atr=raw["atr"],
            day_range=raw.get("day_range"),
            tpo=raw.get("tpo"),
            corey=raw.get("corey"),
        )
    except Exception as exc:
        logger.error("auction bias synthesis failed for %s: %s", sym, exc)
        raise HTTPException(status_code=500, detail=f"synthesis failed: {exc}") from exc

    as_of = raw.get("as_of") or time.time()
    source = raw.get("source", "provider")
    payload["provenance"] = {
        "is_live": derive_is_live(
            source,
            as_of,
            DEFAULT_STALE_AFTER_S,
            ibkr_data_connected=bool(raw.get("ibkr_connected")),
            now=time.time(),
        ),
        "source": source,
        "as_of": as_of,
        "stale_after_s": DEFAULT_STALE_AFTER_S,
    }
    payload["available"] = True
    return payload
