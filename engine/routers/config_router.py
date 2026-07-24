"""Config overview router — exposes categorized TradingConfig fields (P2-C)."""

from __future__ import annotations

from fastapi import APIRouter

from config import settings

router = APIRouter(prefix="/config", tags=["config"])

SENSITIVE_KEYS = {
    "ANTHROPIC_API_KEY",
    "FINNHUB_API_KEY",
    "POLYGON_API_KEY",
    "ALPACA_API_KEY",
    "ALPACA_SECRET_KEY",
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_WHATSAPP_FROM",
    "WHATSAPP_TO",
    "IBKR_CLIENT_ID",
}

CATEGORIES: dict[str, list[str]] = {
    "safety": [
        "MAX_POSITION_SIZE_PCT",
        "MAX_DAILY_LOSS_PCT",
        "MAX_DRAWDOWN_PCT",
        "MAX_CONTRACTS_PER_INSTRUMENT",
        "MAX_OVERNIGHT_CONTRACTS",
        "MAX_SINGLE_ORDER_VALUE",
        "MAX_MARGIN_UTILIZATION",
        "MAX_CORRELATED_EXPOSURE_PCT",
        "MAX_ORDERS_PER_MINUTE",
        "LIVE_TRADING_ENABLED",
        "REQUIRE_HUMAN_APPROVAL",
    ],
    "broker": [
        "IBKR_HOST",
        "IBKR_PORT",
        "IBKR_CLIENT_ID",
        "IBKR_PAPER_MODE",
    ],
    "data": [
        "POLYGON_API_KEY",
        "FINNHUB_API_KEY",
        "ALPACA_API_KEY",
        "ALPACA_SECRET_KEY",
        "ALPACA_PAPER",
    ],
    "llm": [
        "ANTHROPIC_API_KEY",
        "LLM_PROVIDER",
    ],
    "notifications": [
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "TWILIO_WHATSAPP_FROM",
        "WHATSAPP_TO",
    ],
    "feature_flags": [
        "ENABLE_KAIROS",
        "ENABLE_SPECULATION",
        "ENABLE_TILT_DETECTION",
        "ENABLE_DREAM_CONSOLIDATION",
        "ENABLE_CONTEXT_COMPACTION",
        "ENABLE_CRYPTO",
        "ENABLE_POLYMARKET",
        "ENABLE_RL_TRADING",
        "ENABLE_SIGNAL_SANITIZATION",
        "KAIROS_TICK_SECONDS",
        "KAIROS_OFF_HOURS_TICK_SECONDS",
        "KAIROS_NOTIFY_SEVERITY",
    ],
}


def _mask(key: str, value) -> str:
    if key in SENSITIVE_KEYS and value:
        s = str(value)
        if len(s) > 4:
            return "***" + s[-4:]
        return "***"
    return value


@router.get("/overview")
async def config_overview():
    """Return all TradingConfig fields grouped by category, sensitive values masked."""
    config_dict = settings.model_dump() if hasattr(settings, "model_dump") else settings.dict()

    # Pull feature flags from registry (they live there, not in TradingConfig)
    try:
        from flags.registry import get_flags

        try:
            flags_registry = get_flags()
            # list_flags() returns a List[Dict] (one dict per flag), not a
            # name -> dict mapping — GT-14: the old `.items()` call above
            # raised AttributeError on every request, silently swallowed by
            # the broad except below, leaving flag_data = {} and the /config
            # Feature Flags card permanently empty despite ~9 live boot-time
            # ENABLE_* flags.
            flag_data = {
                info["name"]: info["enabled"] for info in flags_registry.list_flags()
            }
        except RuntimeError:
            # Singleton not initialized (e.g. in tests) — use static FLAG_DEFINITIONS defaults
            from flags.registry import FLAG_DEFINITIONS

            flag_data = {f["name"]: f["default"] for f in FLAG_DEFINITIONS}
    except Exception:
        flag_data = {}

    categorized: dict[str, list] = {}
    seen_keys: set[str] = set()

    for category, keys in CATEGORIES.items():
        items = []
        for key in keys:
            # Feature flags come from registry, other keys from config_dict
            if category == "feature_flags" and key in flag_data:
                items.append(
                    {
                        "key": key,
                        "value": flag_data[key],
                        "sensitive": False,
                    }
                )
                seen_keys.add(key)
            elif key in config_dict:
                items.append(
                    {
                        "key": key,
                        "value": _mask(key, config_dict[key]),
                        "sensitive": key in SENSITIVE_KEYS,
                    }
                )
                seen_keys.add(key)
        categorized[category] = items

    # GT-14: don't let the "feature_flags" category silently miss a flag that
    # was added to FLAG_DEFINITIONS but never back-filled into the static
    # CATEGORIES list above (e.g. ENABLE_MACRO_TREND_BIAS). The registry
    # (flag_data) is the source of truth for which ENABLE_* flags actually
    # exist at boot — surface all of them, not just the ones this file
    # happens to enumerate.
    feature_flag_items = categorized.setdefault("feature_flags", [])
    already_listed = {item["key"] for item in feature_flag_items}
    for flag_name, flag_enabled in flag_data.items():
        if flag_name not in already_listed:
            feature_flag_items.append(
                {"key": flag_name, "value": flag_enabled, "sensitive": False}
            )
            seen_keys.add(flag_name)

    # Uncategorized fields
    other: list = []
    for key, value in config_dict.items():
        if key not in seen_keys and key != "AGENT_MAX_TOKENS":
            other.append(
                {
                    "key": key,
                    "value": _mask(key, value),
                    "sensitive": key in SENSITIVE_KEYS,
                }
            )
    if other:
        categorized["other"] = other

    return {
        "categories": categorized,
        "total_fields": len(config_dict),
    }


@router.get("/health-check")
async def config_health_check():
    """Check which critical API keys are configured (not their values)."""
    config_dict = settings.model_dump() if hasattr(settings, "model_dump") else settings.dict()

    critical_keys = [
        "ANTHROPIC_API_KEY",
        "FINNHUB_API_KEY",
        "POLYGON_API_KEY",
        "ALPACA_API_KEY",
        "TWILIO_ACCOUNT_SID",
        "WHATSAPP_TO",
    ]

    return {
        "configured": {k: bool(config_dict.get(k)) for k in critical_keys},
        "live_trading_enabled": config_dict.get("LIVE_TRADING_ENABLED", False),
        "require_human_approval": config_dict.get("REQUIRE_HUMAN_APPROVAL", True),
        "paper_trading": not config_dict.get("LIVE_TRADING_ENABLED", False),
    }
