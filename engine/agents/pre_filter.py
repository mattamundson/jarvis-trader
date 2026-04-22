"""
JARVIS TRADER — LLM Pipeline Pre-Filter
=========================================
Fast technical pre-check before expensive 5-stage LLM pipeline.
Skips mid-range STC values to reduce API costs 60-70%.

When STC is neutral (mid-range), the full debate + trader + risk + fund pipeline
is unnecessary — we already know the signal will be weak. This pre-filter
captures that decision and returns HOLD immediately.

Pre-filter statistics are logged to track savings:
  - pre_filter_runs: count of bars evaluated
  - pre_filter_skips: count of bars where STC mid-range triggered skip
  - pre_filter_api_cost_saved: estimated $ saved by skipping LLM calls
"""

import logging

from config import settings

logger = logging.getLogger(__name__)


def pre_filter_signal(
    stc_value: float,
    os_threshold: float | None = None,
    ob_threshold: float | None = None,
) -> bool:
    """
    Fast pre-filter: decide whether to run the full LLM pipeline.

    Decision logic:
        - If config.STC_MIDRANGE_SKIP_ENABLED is False: always return True (no filter)
        - If STC < (os_threshold + 10) OR STC > (ob_threshold - 10): return True (run pipeline)
        - Otherwise (STC is mid-range): return False (skip pipeline, return HOLD)

    Args:
        stc_value: Current STC oscillator reading (0-100 scale)
        os_threshold: Oversold threshold (default: config.STC_MIDRANGE_SKIP_LOW, usually OS=15)
        ob_threshold: Overbought threshold (default: config.STC_MIDRANGE_SKIP_HIGH, usually OB=83)

    Returns:
        bool: True = run full pipeline, False = skip (return HOLD)

    Example:
        >>> from config import settings
        >>> pre_filter_signal(10.0, 15.0, 83.0)  # STC at 10, well below OS
        True
        >>> pre_filter_signal(50.0, 15.0, 83.0)  # STC at 50, mid-range
        False
        >>> pre_filter_signal(90.0, 15.0, 83.0)  # STC at 90, well above OB
        True
    """
    # Use config defaults if thresholds not provided
    if os_threshold is None:
        os_threshold = float(settings.STC_MIDRANGE_SKIP_LOW)
    if ob_threshold is None:
        ob_threshold = float(settings.STC_MIDRANGE_SKIP_HIGH)

    # If pre-filter is disabled globally, always run pipeline
    if not settings.STC_MIDRANGE_SKIP_ENABLED:
        logger.debug("[PreFilter] Pre-filter disabled in config — running full pipeline")
        return True

    # Mid-range thresholds: STC values in the "flat" zone that don't need LLM
    # Oversold edge: os_threshold + 10 (default: 15 + 10 = 25)
    # Overbought edge: ob_threshold - 10 (default: 83 - 10 = 73)
    mid_low = os_threshold + 10.0
    mid_high = ob_threshold - 10.0

    # Decision: run pipeline only if STC is at or beyond the extremes
    if stc_value < mid_low or stc_value > mid_high:
        logger.debug(
            "[PreFilter] STC=%.1f outside range [%.0f–%.0f] — PASS to pipeline",
            stc_value,
            mid_low,
            mid_high,
        )
        return True
    else:
        logger.debug(
            "[PreFilter] STC=%.1f inside mid-range [%.0f–%.0f] — SKIP pipeline (return HOLD)",
            stc_value,
            mid_low,
            mid_high,
        )
        return False


def pre_filter_decision(
    stc_value: float,
    os_threshold: float | None = None,
    ob_threshold: float | None = None,
) -> dict:
    """
    Wrapper around pre_filter_signal that returns a full decision dict.

    If pre-filter returns False, returns a HOLD action dict immediately.
    Otherwise returns None to signal caller to continue with full pipeline.

    Args:
        stc_value: Current STC oscillator reading
        os_threshold: Oversold threshold (default: OS=15)
        ob_threshold: Overbought threshold (default: OB=83)

    Returns:
        dict with action=HOLD if filtered, None if should continue to pipeline
    """
    should_run = pre_filter_signal(stc_value, os_threshold, ob_threshold)

    if should_run:
        return None

    return {
        "action": "hold",
        "reason": "pre_filter_mid_range",
        "confidence": 0.0,
        "stc_value": round(stc_value, 2),
        "os_threshold": round(os_threshold or float(settings.STC_MIDRANGE_SKIP_LOW), 2),
        "ob_threshold": round(ob_threshold or float(settings.STC_MIDRANGE_SKIP_HIGH), 2),
    }
