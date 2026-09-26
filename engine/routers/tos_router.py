"""
TOS Indicators — derived analytics from the thinkorswim RTD price stream.

Serves the indicator set that mirrors Matt's TOS /ES chart:

  * ATR(14)                  — Average True Range (volatility foundation)
  * Keltner Channels (20,3.5) — EMA(20) ± 3.5·ATR
  * Multi-timeframe S/R      — 5m / 15m / 30m rolling tops and bottoms
  * Day-range gauge          — session range as a % of ATR (compression)

SOURCE-OF-TRUTH NOTE
--------------------
ThinkOrSwim's RTD server only answers *native* quote topics
(``LAST``/``BID``/``ASK``/``CLOSE``). ThinkScript study outputs such as
``ATRTrailingStopLE``, ``KeltnerChannels`` or ``AA_CoreyTscorev2`` are **not**
queryable by name — verified empirically: 11 candidate study topics for
``/ES:XCME`` and ``SPY`` all returned ``None``.

So these indicators are **computed** in ``data/tos_indicator_engine.py`` from
the live RTD price stream rather than read from TOS. They are therefore
labelled ``derived`` in the payload and must never be presented as
TOS-computed study values.

If Matt later adds the studies as **custom quote columns** in a TOS watchlist,
TOS will expose them as RTD column topics and they can be wired in as a
separate (native) source alongside these derived values.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tos", tags=["tos", "indicators"])

# Injected from main.py alongside the other router dependency injections.
_tos_connector = None


def inject_dependencies(connector=None) -> None:
    """Wire the process-wide TOSRTDConnector into this router."""
    global _tos_connector
    _tos_connector = connector


def _snapshot_payload(snap) -> dict:
    """Serialize an IndicatorSnapshot, tagging provenance explicitly."""
    if snap is None:
        return {}
    return {
        "symbol": snap.symbol,
        "last_price": snap.last_price,
        "source": "derived",  # computed from rtd_tos prices, NOT a TOS study
        "price_source": "rtd_tos",
        "atr": {
            "value": snap.atr.value,
            "period": snap.atr.period,
            "bars_used": snap.atr.bars_used,
        },
        "keltner": {
            "upper": snap.keltner.upper,
            "mid": snap.keltner.mid,
            "lower": snap.keltner.lower,
            "ema_period": snap.keltner.ema_period,
            "atr_multiplier": snap.keltner.atr_multiplier,
        },
        "sr_levels": [
            {
                "tf_minutes": sr.tf_minutes,
                "top": sr.top,
                "bottom": sr.bottom,
            }
            for sr in snap.sr_levels
        ],
        "day_range": {
            "day_high": snap.day_range.day_high,
            "day_low": snap.day_range.day_low,
            "day_range": snap.day_range.day_range,
            "atr": snap.day_range.atr,
            "range_pct": snap.day_range.range_pct,
        },
        "as_of": snap.as_of,
    }


@router.get("/indicators/status")
async def tos_indicators_status():
    """Connection state plus per-symbol indicator warm-up progress."""
    if _tos_connector is None:
        return {
            "available": False,
            "reason": "TOS RTD connector not injected",
            "symbols": [],
        }
    try:
        status = _tos_connector.status()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"TOS status failed: {exc}") from exc
    return {
        "available": bool(status.get("connected")),
        "connected": bool(status.get("connected")),
        "port": status.get("port"),
        "watch_symbols": status.get("watch_symbols", []),
        "symbols": status.get("indicators", []),
    }


@router.get("/indicators")
async def tos_indicators(
    symbols: str = Query(
        "SPY,QQQ,VIX,MES",
        description="Comma-separated engine symbols to return indicators for.",
    ),
):
    """Derived indicator snapshots (ATR / Keltner / multi-TF S-R / day range).

    Values are computed in-process from the live thinkorswim RTD price stream.
    Every price is ``null`` when genuinely unavailable — never a silent zero.
    """
    if _tos_connector is None:
        raise HTTPException(status_code=503, detail="TOS RTD connector not injected")

    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        return {"source": "derived", "price_source": "rtd_tos", "symbols": {}}

    out: dict[str, dict] = {}
    for symbol in symbol_list:
        try:
            snap = await _tos_connector.get_indicators(symbol)
        except Exception as exc:  # noqa: BLE001 — one bad symbol must not 500 the set
            logger.debug("TOS indicators failed for %s: %s", symbol, exc)
            snap = None
        if snap is not None:
            out[symbol] = _snapshot_payload(snap)
        else:
            out[symbol] = {
                "symbol": symbol,
                "last_price": None,
                "source": "derived",
                "price_source": "rtd_tos",
                "atr": {"value": None, "period": 14, "bars_used": 0},
                "keltner": {
                    "upper": None,
                    "mid": None,
                    "lower": None,
                    "ema_period": 20,
                    "atr_multiplier": 3.5,
                },
                "sr_levels": [],
                "day_range": {
                    "day_high": None,
                    "day_low": None,
                    "day_range": None,
                    "atr": None,
                    "range_pct": None,
                },
                "as_of": None,
            }
    return {"source": "derived", "price_source": "rtd_tos", "symbols": out}
