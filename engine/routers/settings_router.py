"""
Risk settings and strategy parameters
"""

import logging
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["settings"])

# Global references (injected from main.py)
safety_layer = None
db_manager = None
settings_obj = None


def inject_dependencies(s, dbm, sl):
    """Inject dependencies from main.py"""
    global settings_obj, db_manager, safety_layer
    settings_obj = s
    db_manager = dbm
    safety_layer = sl


@router.get("/settings/risk")
async def get_risk_settings():
    """Get current risk/circuit breaker settings."""
    try:
        # Get live circuit breaker state
        cb_status = {}
        if safety_layer:
            cb_status = safety_layer.check_circuit_breakers()

        # Get config defaults from env / TradingConfig
        config = {
            "daily_loss_limit": float(
                os.getenv("DAILY_LOSS_LIMIT", str(settings.MAX_DAILY_LOSS_PCT * 10000))
            ),
            "max_drawdown_pct": settings_obj.MAX_DRAWDOWN_PCT,
            "max_contracts": settings_obj.MAX_CONTRACTS_PER_INSTRUMENT,
            "risk_per_trade_pct": float(os.getenv("RISK_PER_TRADE_PCT", "0.01")),
            "atr_stop_multiplier": float(os.getenv("ATR_STOP_MULTIPLIER", "0.70")),
            "atr_target_multiplier": float(os.getenv("ATR_TARGET_MULTIPLIER", "1.50")),
        }

        # Override with DB settings if available (DB values take precedence over env)
        if db_manager:
            for key in config:
                val = db_manager.get_setting(key)
                if val is not None:
                    try:
                        config[key] = type(config[key])(val)
                    except (ValueError, TypeError):
                        pass

        return {
            "config": config,
            "circuit_breakers": cb_status,
            "editable_keys": list(config.keys()),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/settings/risk")
async def update_risk_settings(payload: dict):
    """Update risk settings (persists to DB settings table)."""
    if not db_manager:
        raise HTTPException(status_code=503, detail="Database not initialized")

    ALLOWED_KEYS = {
        "daily_loss_limit",
        "max_drawdown_pct",
        "max_contracts",
        "risk_per_trade_pct",
        "atr_stop_multiplier",
        "atr_target_multiplier",
    }

    VALIDATORS = {
        "daily_loss_limit": lambda v: float(v) > 0,
        "max_drawdown_pct": lambda v: 0 < float(v) <= 1.0,
        "max_contracts": lambda v: 1 <= int(v) <= 10,
        "risk_per_trade_pct": lambda v: 0 < float(v) <= 0.05,
        "atr_stop_multiplier": lambda v: 0.1 <= float(v) <= 3.0,
        "atr_target_multiplier": lambda v: 0.1 <= float(v) <= 5.0,
    }

    updated = {}
    errors = {}

    for key, value in payload.items():
        if key not in ALLOWED_KEYS:
            errors[key] = "Unknown setting"
            continue

        validator = VALIDATORS.get(key)
        try:
            if validator and not validator(value):
                errors[key] = f"Value {value} out of allowed range"
                continue
            db_manager.set_setting(key, str(value))
            updated[key] = value
        except Exception as e:
            errors[key] = str(e)[:80]

    return {
        "updated": updated,
        "errors": errors,
        "count": len(updated),
    }


# ── Strategy Parameters ────────────────────────────────────────────────────────


class StrategyParams(BaseModel):
    """Strategy parameter configuration."""

    model_config = {"extra": "forbid"}

    ema_short: int = 8
    ema_long: int = 21
    ema_smoother: int = 34
    atr_length: int = 14
    atr_mult_stop: float = 1.5
    atr_mult_target: float = 3.0
    min_volume_sma: int = 20
    rsi_length: int = 14
    rsi_oversold: int = 30
    rsi_overbought: int = 70
    adaptive_regime: bool = True
    volume_filter: bool = False
    mtf_filter: bool = False


# In-memory strategy params (would be persisted in production)
_strategy_params = StrategyParams()


@router.get("/strategy/params")
async def get_strategy_params():
    """
    Get current strategy parameter configuration.

    Returns:
        ema_short: Short-term EMA period (default 8)
        ema_long: Medium-term EMA period (default 21)
        ema_smoother: Long-term EMA period (default 34)
        atr_length: ATR indicator period (default 14)
        atr_mult_stop: Stop loss as multiple of ATR (default 1.5x)
        atr_mult_target: Profit target as multiple of ATR (default 3.0x)
        min_volume_sma: Minimum volume SMA period (default 20)
        rsi_length: RSI indicator period (default 14)
        rsi_oversold: RSI oversold threshold (default 30)
        rsi_overbought: RSI overbought threshold (default 70)
        adaptive_regime: Apply regime-based filters (default True)
        volume_filter: Apply volume filters (default False)
        mtf_filter: Apply multi-timeframe filters (default False)
    """
    global _strategy_params
    return _strategy_params.model_dump()


@router.put("/strategy/params")
async def update_strategy_params(params: StrategyParams):
    """
    Update strategy parameter configuration.

    Changes take effect immediately for future backtests and live trading.
    Existing positions are unaffected.

    Request:
        ema_short, ema_long, ema_smoother: EMA periods
        atr_length, atr_mult_stop, atr_mult_target: ATR configuration
        min_volume_sma, rsi_length, rsi_oversold, rsi_overbought: Indicator settings
        adaptive_regime, volume_filter, mtf_filter: Feature flags
    """
    global _strategy_params
    try:
        # Validate parameters
        if not (1 < params.ema_short < params.ema_long < params.ema_smoother < 200):
            raise ValueError("EMA periods must satisfy: 1 < short < long < smoother < 200")
        if not (1 <= params.atr_length <= 50):
            raise ValueError("ATR length must be 1-50")
        if not (0.5 <= params.atr_mult_stop <= 10.0):
            raise ValueError("ATR stop multiplier must be 0.5-10.0")
        if not (0.5 <= params.atr_mult_target <= 10.0):
            raise ValueError("ATR target multiplier must be 0.5-10.0")
        if not (1 <= params.rsi_length <= 50):
            raise ValueError("RSI length must be 1-50")
        if not (0 < params.rsi_oversold < 50):
            raise ValueError("RSI oversold must be 0-50")
        if not (50 < params.rsi_overbought < 100):
            raise ValueError("RSI overbought must be 50-100")

        old_params = _strategy_params.model_dump()
        _strategy_params = params
        logger.info(f"[STRATEGY] Parameters updated: {params.model_dump()}")

        return {
            "status": "updated",
            "old_params": old_params,
            "new_params": params.model_dump(),
        }
    except ValueError as e:
        raise HTTPException(400, f"Invalid parameter: {e}") from e
    except Exception as e:
        logger.error(f"[STRATEGY] Update failed: {e}")
        raise HTTPException(500, f"Failed to update strategy parameters: {e}") from e


# ── Analysis ──────────────────────────────────────────────────────────────


@router.get("/position-sizing/calculate")
async def calculate_position_size_alias():
    """Top-level alias for position sizing calculation."""
    from utils.position_sizing import calculate_position_size

    result = calculate_position_size(
        symbol="MES",
        account_value=settings.INITIAL_CAPITAL,
        atr=15.0,
        risk_pct=0.01,
        atr_stop_multiplier=0.70,
        max_contracts=2,
    )
    return {
        "symbol": result.symbol,
        "contracts": result.contracts,
        "risk_per_trade": result.risk_per_trade,
        "stop_distance": result.stop_distance,
        "dollar_risk_per_contract": result.dollar_risk_per_contract,
        "account_value": result.account_value,
        "reasoning": result.reasoning,
    }
