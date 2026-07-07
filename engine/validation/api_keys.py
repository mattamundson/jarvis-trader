"""
API Key Validation
==================
Validates external service credentials at startup.
- Required keys checked, startup fails if missing
- Optional keys checked, warnings logged if missing
- Placeholder values (like "your-key-here") are treated as missing
- Capabilities degradation tracked and logged clearly
"""

import logging
from typing import Dict, List, Tuple

logger = logging.getLogger("jarvis_trader.validation")


def validate_api_keys(config) -> Dict[str, any]:
    """
    Validate API keys from config. Returns status dict.

    Args:
        config: TradingConfig instance with all env-based settings

    Returns:
        {
            "valid": bool,
            "missing_critical": list[str],
            "missing_optional": list[str],
            "capabilities": {
                "llm_agents": bool,
                "polygon_market_data": bool,
                "fred_economic_data": bool,
                "finnhub_market_data": bool,
                "whatsapp_alerts": bool,
            },
        }
    """

    # Placeholder values that are treated as missing
    PLACEHOLDER_VALUES = {
        "your-key-here",
        "your-api-key",
        "your-api-key-here",
        "sk-ant-api03-",
        "pk_",
        "none",
        "",
    }

    def is_valid_key(value: str | None) -> bool:
        """Check if a key looks legitimate (not None, not empty, not placeholder)."""
        if not value:
            return False
        val_lower = str(value).lower().strip()
        if val_lower in PLACEHOLDER_VALUES:
            return False
        return len(val_lower) > 3  # Keys should be at least 4 chars

    # Required keys — fail startup if missing
    critical_keys: List[Tuple[str, str]] = [
        ("API_KEY", "FastAPI X-API-Key header authentication"),
    ]

    # Optional keys — warn if missing, feature disabled
    optional_keys: List[Tuple[str, str]] = [
        ("ANTHROPIC_API_KEY", "LLM agent pipeline (claude-3-5-sonnet, claude-opus)"),
        ("POLYGON_API_KEY", "Polygon.io market data (Tier 2 after IBKR)"),
        ("FRED_API_KEY", "Federal Reserve FRED economic indicators"),
        ("FINNHUB_API_KEY", "Finnhub alternative market data source"),
        ("TWILIO_ACCOUNT_SID", "WhatsApp alerts via Twilio"),
        ("TWILIO_AUTH_TOKEN", "WhatsApp alerts via Twilio"),
        ("TWILIO_WHATSAPP_FROM", "WhatsApp sender number"),
        ("WHATSAPP_TO", "WhatsApp recipient number"),
    ]

    missing_critical: List[str] = []
    missing_optional: List[str] = []

    # Check critical keys
    for key_name, description in critical_keys:
        value = getattr(config, key_name, None)
        if not is_valid_key(value):
            missing_critical.append(f"{key_name} ({description})")

    # Check optional keys
    for key_name, description in optional_keys:
        value = getattr(config, key_name, None)
        if not is_valid_key(value):
            missing_optional.append(f"{key_name} ({description})")

    # Determine capabilities based on available keys
    capabilities = {
        "llm_agents": is_valid_key(getattr(config, "ANTHROPIC_API_KEY", None)),
        "polygon_market_data": is_valid_key(getattr(config, "POLYGON_API_KEY", None)),
        "fred_economic_data": is_valid_key(getattr(config, "FRED_API_KEY", None)),
        "finnhub_market_data": is_valid_key(getattr(config, "FINNHUB_API_KEY", None)),
        "whatsapp_alerts": all(
            is_valid_key(getattr(config, k, None))
            for k in [
                "TWILIO_ACCOUNT_SID",
                "TWILIO_AUTH_TOKEN",
                "TWILIO_WHATSAPP_FROM",
                "WHATSAPP_TO",
            ]
        ),
    }

    # Log results
    if missing_critical:
        logger.error("CRITICAL: Missing required API keys:")
        for key_desc in missing_critical:
            logger.error(f"  - {key_desc}")

    if missing_optional:
        logger.warning("OPTIONAL: Some features unavailable due to missing API keys:")
        for key_desc in missing_optional:
            logger.warning(f"  - {key_desc}")

    # Log capabilities summary
    logger.info("API Key Validation Results:")
    logger.info(
        f"  LLM Agents:           {'ENABLED' if capabilities['llm_agents'] else 'DISABLED'}"
    )
    logger.info(
        f"  Polygon Market Data:  {'ENABLED' if capabilities['polygon_market_data'] else 'DISABLED'}"
    )
    logger.info(
        f"  FRED Economic Data:   {'ENABLED' if capabilities['fred_economic_data'] else 'DISABLED'}"
    )
    logger.info(
        f"  Finnhub Market Data:  {'ENABLED' if capabilities['finnhub_market_data'] else 'DISABLED'}"
    )
    logger.info(
        f"  WhatsApp Alerts:      {'ENABLED' if capabilities['whatsapp_alerts'] else 'DISABLED'}"
    )

    return {
        "valid": len(missing_critical) == 0,
        "missing_critical": missing_critical,
        "missing_optional": missing_optional,
        "capabilities": capabilities,
    }
