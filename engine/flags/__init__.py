"""
JARVIS TRADER — Feature Flags
==============================
Two-layer feature flag system:
  - Layer 1 (static):  compile-time defaults from TradingConfig
  - Layer 2 (runtime): per-flag overrides persisted to SQLite

Usage
-----
    from flags import get_flags

    flags = get_flags()
    if flags.is_enabled("ENABLE_TILT_DETECTION"):
        ...

In main.py lifespan:
    from flags import FeatureFlags, set_flags_instance
    feature_flags = FeatureFlags(config=settings, db=db_manager)
    set_flags_instance(feature_flags)
"""

from .registry import FeatureFlags, get_flags, set_flags_instance

__all__ = ["FeatureFlags", "get_flags", "set_flags_instance"]
