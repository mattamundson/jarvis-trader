"""
JARVIS Trader Options Engine — FastAPI Router
Exposes the options module (chain fetcher, Greeks monitor, strategy executor,
position manager) via 5 REST endpoints.
"""

import dataclasses
import logging
from datetime import date, datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()

# Global references (injected from main.py)
_data_manager = None


def set_data_manager(dm) -> None:
    """Wire in the app's MarketDataManager singleton (called from main.py)."""
    global _data_manager
    _data_manager = dm


def inject_dependencies():
    """Inject dependencies from main.py"""
    pass


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _serialize(obj: Any) -> Any:
    """Recursively convert dataclass / date / datetime to JSON-safe types."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return _serialize(dataclasses.asdict(obj))
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize(i) for i in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if hasattr(obj, "value"):  # Enum
        return obj.value
    return obj


def _position_to_dict(pos) -> dict:
    """Serialize an OptionsPosition including computed properties."""
    d = _serialize(pos)
    # Attach computed properties (not captured by dataclasses.asdict)
    d["unrealised_pnl"] = pos.unrealised_pnl
    d["dte"] = pos.dte
    d["realised_pnl"] = pos.realised_pnl
    return d


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class StrategyRecommendRequest(BaseModel):
    symbol: str
    vix: float
    underlying_price: float
    dte: int = 30


# ---------------------------------------------------------------------------
# GET /options/chain/{symbol}
# ---------------------------------------------------------------------------


@router.get("/chain/{symbol}", tags=["options"])
async def get_options_chain(symbol: str, expiry_index: int = 0):
    """Fetch the live options chain for a symbol via MarketDataManager.

    Query param ``expiry_index`` selects which expiry (0 = nearest).
    Returns calls, puts, Greeks, IV rank, and underlying price.
    """
    logger.info("[options_router] GET /options/chain/%s expiry_index=%d", symbol, expiry_index)

    try:
        from options.chain_fetcher import fetch_chain_async  # noqa: F401
    except ImportError as exc:
        logger.error("[options_router] chain_fetcher import failed: %s", exc)
        raise HTTPException(status_code=503, detail="Options chain module unavailable.") from exc

    try:
        # Resolve available expiries via the injected data_manager singleton.
        if _data_manager is None:
            raise HTTPException(
                status_code=503,
                detail="Options data manager not initialized.",
            )

        data_manager = _data_manager
        expirations = await data_manager.get_options_expirations(symbol.upper())
        if not expirations:
            raise HTTPException(
                status_code=404,
                detail=f"No options data available for symbol '{symbol}'.",
            )

        if expiry_index >= len(expirations):
            expiry_index = 0  # fall back to nearest

        expiry_dates = [expirations[expiry_index]]
        chain = await fetch_chain_async(
            symbol.upper(), expiry_dates=expiry_dates, data_manager=data_manager
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[options_router] chain fetch error for %s: %s", symbol, exc)
        raise HTTPException(status_code=502, detail=f"Failed to fetch chain: {exc}") from exc

    if chain is None:
        raise HTTPException(
            status_code=404,
            detail=f"Could not retrieve options chain for '{symbol}'. "
            "Symbol may not have options or market may be closed.",
        )

    result = _serialize(chain)
    if not chain.calls and not chain.puts:
        result["_warning"] = (
            "Chain metadata resolved (expiry, spot, IVR) but no option "
            "contracts returned. OPRA quotes may not be live yet; retry "
            "during market hours or verify IBKR market-data entitlements."
        )
    return result


# ---------------------------------------------------------------------------
# GET /options/greeks
# ---------------------------------------------------------------------------


@router.get("/greeks", tags=["options"])
async def get_portfolio_greeks():
    """Return aggregated portfolio Greeks across all open options positions.

    If there are no open positions the response contains all-zero Greeks.
    """
    logger.info("[options_router] GET /options/greeks")

    try:
        from options.position_manager import OptionsPositionManager
    except ImportError as exc:
        logger.error("[options_router] position_manager import failed: %s", exc)
        raise HTTPException(
            status_code=503, detail="Options position manager unavailable."
        ) from exc

    try:
        mgr = OptionsPositionManager()
        pg = mgr.get_portfolio_greeks()
    except Exception as exc:
        logger.exception("[options_router] get_portfolio_greeks error: %s", exc)
        raise HTTPException(
            status_code=500, detail=f"Error retrieving portfolio Greeks: {exc}"
        ) from exc

    return _serialize(pg)


# ---------------------------------------------------------------------------
# GET /options/iv-rank/{symbol}
# ---------------------------------------------------------------------------


@router.get("/iv-rank/{symbol}", tags=["options"])
async def get_iv_rank(symbol: str):
    """Calculate and return the IV Rank for a symbol (0–100 scale).

    Uses 252 trading days of historical price data as a proxy for IV history.
    Returns 50.0 (neutral) when insufficient data exists.
    """
    logger.info("[options_router] GET /options/iv-rank/%s", symbol)

    try:
        from options.chain_fetcher import get_iv_rank_async as _get_iv_rank_async
    except ImportError as exc:
        logger.error("[options_router] chain_fetcher import failed: %s", exc)
        raise HTTPException(status_code=503, detail="Options chain module unavailable.") from exc

    try:
        if _data_manager is None:
            raise HTTPException(
                status_code=503,
                detail="Options data manager not initialized.",
            )
        iv_rank = await _get_iv_rank_async(symbol.upper(), days=252, data_manager=_data_manager)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[options_router] get_iv_rank error for %s: %s", symbol, exc)
        raise HTTPException(status_code=502, detail=f"Failed to compute IV rank: {exc}") from exc

    return {
        "symbol": symbol.upper(),
        "iv_rank": iv_rank,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# POST /options/strategy/recommend
# ---------------------------------------------------------------------------


@router.post("/strategy/recommend", tags=["options"])
async def recommend_strategy(body: StrategyRecommendRequest):
    """Recommend an options strategy based on VIX regime and underlying price.

    The ATR used by the strategy builders is estimated as 1.5% of the
    underlying price — a reasonable proxy when no live ATR is supplied.

    Returns the regime classification, recommended strategy, and the
    constructed OptionsOrder serialised as a dict.
    """
    logger.info(
        "[options_router] POST /options/strategy/recommend symbol=%s vix=%.2f price=%.2f dte=%d",
        body.symbol,
        body.vix,
        body.underlying_price,
        body.dte,
    )

    try:
        from options.strategy_executor import (
            VIXRegime,
            build_bull_put_spread,
            build_covered_call,
            build_iron_condor,
            build_protective_put,
            classify_vix_regime,
        )
    except ImportError as exc:
        logger.error("[options_router] strategy_executor import failed: %s", exc)
        raise HTTPException(status_code=503, detail="Strategy executor unavailable.") from exc

    if body.underlying_price <= 0:
        raise HTTPException(status_code=422, detail="underlying_price must be positive.")
    if body.vix < 0:
        raise HTTPException(status_code=422, detail="vix must be non-negative.")
    if body.dte < 1:
        raise HTTPException(status_code=422, detail="dte must be at least 1.")

    # Estimate ATR as 1.5% of underlying price (proxy when no live ATR is provided)
    estimated_atr = round(body.underlying_price * 0.015, 4)

    regime = classify_vix_regime(body.vix)

    try:
        if regime == VIXRegime.EXTREME:
            # Extreme VIX: protective put for downside insurance
            order = build_protective_put(
                symbol=body.symbol.upper(),
                futures_price=body.underlying_price,
                atr=estimated_atr,
                expiry_dte=body.dte,
            )
            recommendation_reason = (
                f"VIX EXTREME ({body.vix:.1f}) — protective put recommended for downside hedge."
            )

        elif regime == VIXRegime.HIGH:
            # High VIX: bull put spread (directional premium collection, single-sided)
            order = build_bull_put_spread(
                symbol=body.symbol.upper(),
                futures_price=body.underlying_price,
                atr=estimated_atr,
                expiry_dte=body.dte,
            )
            recommendation_reason = (
                f"VIX HIGH ({body.vix:.1f}) — bull put spread; iron condors blocked in high VIX."
            )

        elif regime == VIXRegime.NORMAL:
            # Normal VIX: covered call (mild premium collection)
            order = build_covered_call(
                symbol=body.symbol.upper(),
                futures_price=body.underlying_price,
                atr=estimated_atr,
                expiry_dte=body.dte,
            )
            recommendation_reason = (
                f"VIX NORMAL ({body.vix:.1f}) — covered call for steady premium collection."
            )

        else:
            # Low VIX: iron condor (range-bound premium collection)
            order = build_iron_condor(
                symbol=body.symbol.upper(),
                futures_price=body.underlying_price,
                atr=estimated_atr,
                expiry_dte=body.dte,
            )
            recommendation_reason = (
                f"VIX LOW ({body.vix:.1f}) — iron condor; low vol favours range-bound strategies."
            )

    except Exception as exc:
        logger.exception("[options_router] strategy build error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to build strategy: {exc}") from exc

    return {
        "symbol": body.symbol.upper(),
        "vix": body.vix,
        "regime": regime.value,
        "recommended_strategy": order.strategy.value,
        "recommendation_reason": recommendation_reason,
        "estimated_atr_used": estimated_atr,
        "order": _serialize(order),
    }


# ---------------------------------------------------------------------------
# GET /options/positions
# ---------------------------------------------------------------------------


@router.get("/positions", tags=["options"])
async def get_options_positions(status: Optional[str] = "OPEN"):
    """Return open (or filtered) options positions from the SQLite position store.

    Query param ``status`` accepts ``OPEN``, ``CLOSED``, ``EXPIRED``,
    or omit for all positions.
    """
    logger.info("[options_router] GET /options/positions status=%s", status)

    valid_statuses = {"OPEN", "CLOSED", "EXPIRED", None}
    if status is not None and status.upper() not in valid_statuses - {None}:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status '{status}'. Use OPEN, CLOSED, EXPIRED, or omit.",
        )

    filter_status = status.upper() if status else None

    try:
        from options.position_manager import OptionsPositionManager
    except ImportError as exc:
        logger.error("[options_router] position_manager import failed: %s", exc)
        raise HTTPException(
            status_code=503, detail="Options position manager unavailable."
        ) from exc

    try:
        mgr = OptionsPositionManager()
        positions = mgr.get_positions(status=filter_status)
    except Exception as exc:
        logger.exception("[options_router] get_positions error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Error retrieving positions: {exc}") from exc

    return {
        "positions": [_position_to_dict(p) for p in positions],
        "count": len(positions),
        "status_filter": filter_status,
    }


# ---------------------------------------------------------------------------
# Options Analyst endpoints (stage 6 — added 2026-05-20)
# ---------------------------------------------------------------------------


@router.get("/skew/{symbol}", tags=["options", "analyst"])
async def get_options_skew(symbol: str):
    """Return put/call skew and IV term-structure summary for a symbol.

    Useful for inspecting the raw signals that feed into the OptionsAnalyst
    without running the full pipeline.  Requires an active chain fetcher.
    """
    logger.info("[options_router] GET /options/skew/%s", symbol)

    result: dict = {"symbol": symbol.upper(), "timestamp": datetime.utcnow().isoformat()}

    try:
        from options.chain_fetcher import get_pc_skew, get_term_structure  # type: ignore[import]

        skew = get_pc_skew(symbol.upper())
        result["pc_skew"] = skew
        result["skew_available"] = skew is not None
    except ImportError:
        result["pc_skew"] = None
        result["skew_available"] = False
        result["skew_note"] = "chain_fetcher not available"
    except Exception as exc:
        logger.debug("[options_router] skew fetch error: %s", exc)
        result["pc_skew"] = None
        result["skew_available"] = False

    try:
        from options.chain_fetcher import get_term_structure  # type: ignore[import]

        term = get_term_structure(symbol.upper())
        result["term_structure"] = term
        result["term_available"] = term is not None
    except ImportError:
        result["term_structure"] = None
        result["term_available"] = False
    except Exception as exc:
        logger.debug("[options_router] term_structure fetch error: %s", exc)
        result["term_structure"] = None
        result["term_available"] = False

    return result


@router.get("/analyst/{symbol}", tags=["options", "analyst"])
async def get_options_analyst_verdict(symbol: str, spot_price: Optional[float] = None):
    """Run the OptionsAnalyst directly and return its verdict.

    Useful for debugging the stage-6 signal without triggering the full
    pipeline.  The analyst respects ``ENABLE_OPTIONS_ANALYST`` — when the
    flag is ``0`` it returns a neutral/disabled dict rather than an error.
    """
    logger.info("[options_router] GET /options/analyst/%s spot_price=%s", symbol, spot_price)

    try:
        from agents.options_analyst import OptionsAnalyst, is_options_analyst_enabled

        analyst = OptionsAnalyst()
        result = await analyst.analyze(symbol.upper(), spot_price=spot_price)
        return {
            "symbol": symbol.upper(),
            "enabled": is_options_analyst_enabled(),
            "verdict": result,
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as exc:
        logger.exception("[options_router] analyst verdict error for %s: %s", symbol, exc)
        raise HTTPException(status_code=500, detail=f"OptionsAnalyst error: {exc}") from exc


# ---------------------------------------------------------------------------
# Multi-Market Module Endpoints (added 2026-04-01)
# ---------------------------------------------------------------------------


@router.get("/module/status", tags=["options", "multi-market"])
async def options_module_status():
    """Return OptionsMarketModule health (from MultiMarketOrchestrator)."""
    try:
        from orchestrator import get_orchestrator

        orch = get_orchestrator()
        if not orch:
            return {
                "enabled": False,
                "connected": False,
                "daily_pnl": 0.0,
                "open_positions_count": 0,
                "vix_regime": "normal",
                "current_strategy": "—",
                "status": "not_registered",
                "message": "MultiMarketOrchestrator not initialized",
            }
        module = orch.get_module("options")
        if not module:
            return {
                "enabled": False,
                "connected": False,
                "daily_pnl": 0.0,
                "open_positions_count": 0,
                "vix_regime": "normal",
                "current_strategy": "—",
                "status": "disabled",
                "message": "Options module not in orchestrator",
            }
        health = module.health_check()
        status_val = health.status.value if hasattr(health.status, "value") else str(health.status)
        enabled = status_val not in ("disabled", "error", "not_registered")
        connected = status_val in ("ok", "degraded")
        open_count = health.open_positions if isinstance(health.open_positions, int) else 0
        vix_regime = getattr(health, "vix_regime", "normal") or "normal"
        current_strategy = getattr(health, "current_strategy", "—") or "—"
        last_scan_time = getattr(health, "last_scan_time", None)
        last_scan_iso = (
            last_scan_time.isoformat() if isinstance(last_scan_time, datetime) else last_scan_time
        )
        return {
            "enabled": enabled,
            "connected": connected,
            "daily_pnl": float(health.daily_pnl or 0.0),
            "open_positions_count": open_count,
            "vix_regime": vix_regime,
            "current_strategy": current_strategy,
            "last_scan_time": last_scan_iso,
            "status": status_val,
            "message": health.message,
        }
    except Exception as exc:
        logger.error("[options_router] module_status error: %s", exc)
        return {
            "enabled": False,
            "connected": False,
            "daily_pnl": 0.0,
            "open_positions_count": 0,
            "vix_regime": "normal",
            "current_strategy": "—",
            "status": "error",
            "message": str(exc),
        }


# ---------------------------------------------------------------------------
# GET /options/module/scan  &  /options/module/pnl  (dashboard /options page)
# ---------------------------------------------------------------------------

# VIXRegime.value → the lowercase regime string the dashboard reads
# (frontend has no "extreme" case, so EXTREME collapses to "high").
_VIX_REGIME_DISPLAY = {"LOW": "low", "NORMAL": "normal", "HIGH": "high", "EXTREME": "high"}

# Scanner's internal regime label → a frontend-recognised strategy_type
# (strategyLabel() understands iron_condor / bull_put_spread / skip).
_SCANNER_REGIME_STRATEGY = {
    "low_vix": "iron_condor",
    "normal": "bull_put_spread",
    "high_vix": "skip",
}

# Overall display regime → the headline strategy_selected for the scan card.
_DISPLAY_REGIME_STRATEGY = {
    "low": "iron_condor",
    "normal": "bull_put_spread",
    "high": "skip",
}


def _estimate_scan_premium(iv_rank: float, current_price: float) -> float:
    """Heuristic estimated credit per spread (dollars), NOT a live quote.

    A short premium-selling spread at ~30 DTE collects roughly 0.4% of the
    underlying, scaled by how rich IV is (iv_rank/50). ×100 for the option
    contract multiplier. The dashboard column is explicitly labelled
    "Est. Premium" — this is a transparent proxy, not fabricated live data.
    """
    try:
        return round(current_price * 0.004 * (max(iv_rank, 0.0) / 50.0) * 100, 2)
    except Exception:
        return 0.0


@router.get("/module/scan", tags=["options", "multi-market"])
async def options_module_scan():
    """Latest options-scan opportunities in the dashboard's OptionsScanResponse
    shape. Degrades to an empty (not 404/500) payload when the scanner or its
    data dependencies are unavailable."""
    empty = {"scan_results": [], "vix_regime": "normal", "strategy_selected": "—"}

    # Headline VIX regime from the live VIX (independent of scan hits).
    vix_regime = "normal"
    try:
        from options.strategy_executor import classify_vix_regime

        if _data_manager is not None:
            vix_data = await _data_manager.get_vix()
            vix = float(vix_data.get("value", 20.0) or 20.0)
            vix_regime = _VIX_REGIME_DISPLAY.get(
                classify_vix_regime(vix).value, "normal"
            )
    except Exception as exc:
        logger.debug("[options_router] module_scan vix lookup failed: %s", exc)

    try:
        from markets.options.scanner import OptionsScanner
    except ImportError:
        return {**empty, "vix_regime": vix_regime}

    try:
        scanner = OptionsScanner(data_manager=_data_manager)
        results = await scanner.scan_async()
    except Exception as exc:
        logger.debug("[options_router] module_scan scanner failed: %s", exc)
        return {**empty, "vix_regime": vix_regime}

    scan_results = [
        {
            "symbol": r.symbol,
            "strategy_type": _SCANNER_REGIME_STRATEGY.get(r.regime, "iron_condor"),
            "iv_rank": round(r.iv_rank, 1),
            "expiry_date": r.expiry,
            "estimated_premium": _estimate_scan_premium(r.iv_rank, r.current_price),
        }
        for r in (results or [])
    ]

    return {
        "scan_results": scan_results,
        "vix_regime": vix_regime,
        "strategy_selected": _DISPLAY_REGIME_STRATEGY.get(vix_regime, "—"),
    }


@router.get("/module/pnl", tags=["options", "multi-market"])
async def options_module_pnl():
    """Options P&L in the dashboard's OptionsPnLResponse shape.

    Open positions come from the real OptionsPositionManager store; daily P&L
    from the orchestrator module when registered. Degrades to zeros/empty when
    the module is off or the store is empty — never a 404/500.
    """
    open_mapped: list[dict] = []
    unrealised_total = 0.0
    realized_total = 0.0

    mgr = None
    try:
        from options.position_manager import OptionsPositionManager

        mgr = OptionsPositionManager()
        open_positions = mgr.get_positions(status="OPEN")
        for p in open_positions:
            open_mapped.append(
                {
                    "symbol": p.symbol,
                    "strategy": p.strategy,
                    "entry_price": p.entry_premium,
                    "current_price": p.current_premium,
                    "pnl": p.unrealised_pnl,
                    "dte": p.dte,
                }
            )
        unrealised_total = round(sum(p.unrealised_pnl for p in open_positions), 2)
    except Exception as exc:
        logger.debug("[options_router] module_pnl open-positions failed: %s", exc)

    if mgr is not None:
        try:
            closed = mgr.get_positions(status="CLOSED")
            realized_total = round(sum((p.realised_pnl or 0.0) for p in closed), 2)
        except Exception as exc:
            logger.debug("[options_router] module_pnl closed-positions failed: %s", exc)

    daily_pnl = 0.0
    try:
        from orchestrator import get_orchestrator

        orch = get_orchestrator()
        module = orch.get_module("options") if orch else None
        if module is not None:
            daily_pnl = float(await module.get_daily_pnl() or 0.0)
    except Exception as exc:
        logger.debug("[options_router] module_pnl daily_pnl failed: %s", exc)

    return {
        "daily_pnl": daily_pnl,
        "total_pnl": round(realized_total + unrealised_total, 2),
        "open_positions": open_mapped,
    }
