"""
KAIROS — Proactive Monitoring Daemon
======================================
Always-on background monitoring for JARVIS TRADER.

Components:
  KairosDaemon     — background asyncio task, runs watchers on each tick
  BaseWatcher      — ABC for all rule-based watchers
  Observation      — single observation data class
  Severity         — info / warning / critical
  ObservationLog   — append-only JSONL log (one file per day)
  KairosDreamer    — nightly pattern consolidation (optional LLM)

Usage in FastAPI lifespan:
    from kairos import KairosDaemon, set_kairos_instance
    from kairos.watchers import (
        RegimeChangeWatcher, STCCrossoverWatcher, RiskLimitWatcher,
        VIXSpikeWatcher, VolumeAnomalyWatcher, SpreadWideningWatcher,
        CorrelationBreakWatcher,
    )

    daemon = KairosDaemon(config=settings, safety_layer=safety_layer, ...)
    daemon.register_watcher(RegimeChangeWatcher())
    # ... register other watchers ...
    await daemon.start()
    set_kairos_instance(daemon)
"""

from .daemon import KairosDaemon, get_kairos, set_kairos_instance
from .dreaming import KairosDreamer
from .observation_log import ObservationLog
from .watchers import BaseWatcher, Observation, Severity

__all__ = [
    "KairosDaemon",
    "get_kairos",
    "set_kairos_instance",
    "BaseWatcher",
    "Observation",
    "Severity",
    "ObservationLog",
    "KairosDreamer",
]
