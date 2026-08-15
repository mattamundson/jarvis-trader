"""Config overview router — exposes categorized TradingConfig fields (P2-C)."""

from __future__ import annotations

import os

from fastapi import APIRouter

from config import settings

router = APIRouter(prefix="/config", tags=["config"])

# SECURITY: redact-by-default allowlist (GT-02).
#
# This used to be a hand-maintained SENSITIVE_KEYS *denylist* — every new
# secret-bearing env var the engine loaded (SCHWAB_APP_SECRET, POSTGRES_URL
# with an embedded username:password, KRAKEN_*_API_SECRET, API_KEY,
# TELEGRAM_BOT_TOKEN, HERMES_CLOUD_API_KEY, ...) had to be remembered and
# added by hand, and every one that was forgotten leaked in plaintext via
# /config/overview's "other" (uncategorized) section.
#
# The allowlist below inverts that: a field is shown in full ONLY if it is
# explicitly listed here as reviewed-and-confirmed to carry no credential
# material. Every other key -- known today or added to TradingConfig
# tomorrow -- is redacted by default. When adding a new config field that
# should be visible on the dashboard, add it here deliberately; do nothing
# and it stays safely masked.
SAFE_TO_DISPLAY_KEYS = {
    # risk/safety parameters -- plain numbers and booleans, not credentials
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
    # broker connection topology -- no embedded credentials
    "IBKR_HOST",
    "IBKR_PORT",
    "IBKR_PAPER_MODE",
    # provider mode / selector flags, not secrets themselves
    "ALPACA_PAPER",
    "LLM_PROVIDER",
    # deliberately public URL used in outbound alert links
    "DASHBOARD_PUBLIC_URL",
    # internal engine base URL (e.g. http://127.0.0.1:8010) -- a bare
    # host:port, no embedded credentials
    "ENGINE_INTERNAL_URL",
    # feature flags -- booleans and plain tick intervals
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


def _redact(key: str, value):
    """Return (displayed_value, sensitive_flag) for one config field.

    Redact-by-default: any key not on SAFE_TO_DISPLAY_KEYS is treated as
    potentially secret. Only non-empty *strings* can actually carry
    credential material -- API keys, tokens, account SIDs, and connection
    strings are always strings -- so a bool/int/float/list/dict/None value
    passes through unmasked even for a not-yet-reviewed key: there is
    nothing in e.g. a boolean feature flag that could leak a credential.
    This keeps the "sensitive" flag and the masking decision atomic (a
    field can never be reported sensitive=True while its value is shown
    in the clear, or vice versa).
    """
    if key in SAFE_TO_DISPLAY_KEYS:
        return value, False

    if not isinstance(value, str) or not value:
        return value, False

    masked = "***" + value[-4:] if len(value) > 4 else "***"
    return masked, True


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
                display_value, sensitive = _redact(key, config_dict[key])
                items.append(
                    {
                        "key": key,
                        "value": display_value,
                        "sensitive": sensitive,
                    }
                )
                seen_keys.add(key)
        categorized[category] = items

    # The "llm" category's LLM_PROVIDER field is loaded from TradingConfig but
    # not wired to any routing decision -- every real provider selection reads
    # os.getenv("JARVIS_LLM_PROVIDER", "ollama") directly (llm/client.py,
    # main.py), bypassing settings entirely. That left this endpoint able to
    # show e.g. "openai" while the engine actually ran single-leg ollama, with
    # nothing on the dashboard to catch the mismatch. Surface the value that
    # actually drives routing, using the identical resolution both call sites
    # use, so anyone checking "what provider is active" sees the truth
    # alongside (not instead of) the pre-existing, non-authoritative field.
    active_llm_provider = os.getenv("JARVIS_LLM_PROVIDER", "ollama").strip().lower()
    categorized.setdefault("llm", []).append(
        {
            "key": "JARVIS_LLM_PROVIDER",
            "value": active_llm_provider,
            "sensitive": False,
        }
    )
    seen_keys.add("JARVIS_LLM_PROVIDER")

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
            display_value, sensitive = _redact(key, value)
            other.append(
                {
                    "key": key,
                    "value": display_value,
                    "sensitive": sensitive,
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
