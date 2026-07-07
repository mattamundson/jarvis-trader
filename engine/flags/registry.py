"""
JARVIS TRADER — Feature Flags Registry
========================================
FeatureFlags class: two-layer flag resolution.

Layer 1 — Static defaults from TradingConfig (compile-time).
Layer 2 — Runtime overrides persisted to the SQLite feature_flags table.

Runtime overrides take precedence over config defaults.
Resetting a flag removes the override and falls back to the config default.

Thread safety: All SQLite operations are serialised via the DatabaseManager's
internal lock (connection-per-call pattern, same as all other DB operations).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("jarvis_trader.flags")

# ---------------------------------------------------------------------------
# Flag definitions — name, config-level default, metadata
# ---------------------------------------------------------------------------

FLAG_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "ENABLE_KAIROS",
        "default": False,
        "description": "Always-on proactive monitoring daemon",
        "category": "ai",
        "requires_restart": True,
    },
    {
        "name": "ENABLE_SPECULATION",
        "default": False,
        "description": "Pre-execution speculation engine",
        "category": "ai",
        "requires_restart": False,
    },
    {
        "name": "ENABLE_TILT_DETECTION",
        "default": True,
        "description": "Tilt/revenge trading detection",
        "category": "risk",
        "requires_restart": False,
    },
    {
        "name": "ENABLE_DREAM_CONSOLIDATION",
        "default": False,
        "description": "Nightly pattern consolidation",
        "category": "ai",
        "requires_restart": False,
    },
    {
        "name": "ENABLE_CONTEXT_COMPACTION",
        "default": True,
        "description": "4-tier LLM context management",
        "category": "ai",
        "requires_restart": False,
    },
    {
        "name": "ENABLE_CRYPTO",
        "default": False,
        "description": "Crypto market module (Freqtrade)",
        "category": "market",
        "requires_restart": True,
    },
    {
        "name": "ENABLE_POLYMARKET",
        "default": False,
        "description": "Polymarket module (US regulatory risk)",
        "category": "market",
        "requires_restart": True,
    },
    {
        "name": "ENABLE_RL_TRADING",
        "default": False,
        "description": "RL-based strategy execution",
        "category": "experimental",
        "requires_restart": False,
    },
    {
        "name": "ENABLE_SIGNAL_SANITIZATION",
        "default": False,
        "description": "Anti-signal-leakage log sanitization",
        "category": "security",
        "requires_restart": False,
    },
    {
        "name": "ENABLE_MACRO_TREND_BIAS",
        "default": False,
        "description": "Advisory macro trend bias (SPX weekly Supertrend + monthly momentum) folded into the pipeline regime context",
        "category": "ai",
        "requires_restart": False,
    },
]

# Build a fast lookup dict: name -> definition
_FLAG_META: Dict[str, Dict[str, Any]] = {f["name"]: f for f in FLAG_DEFINITIONS}

# ---------------------------------------------------------------------------
# Singleton plumbing
# ---------------------------------------------------------------------------

_instance: Optional["FeatureFlags"] = None


def get_flags() -> "FeatureFlags":
    """
    Return the application-level FeatureFlags singleton.

    Raises RuntimeError if set_flags_instance() has not been called yet.
    This mirrors the pattern used by other engine singletons.
    """
    if _instance is None:
        raise RuntimeError(
            "FeatureFlags singleton is not initialised. "
            "Call set_flags_instance() in the FastAPI lifespan startup block."
        )
    return _instance


def set_flags_instance(instance: "FeatureFlags") -> None:
    """Register the application-level FeatureFlags singleton."""
    global _instance
    _instance = instance
    logger.info("FeatureFlags singleton registered (%d flags defined)", len(FLAG_DEFINITIONS))


# ---------------------------------------------------------------------------
# FeatureFlags class
# ---------------------------------------------------------------------------


class FeatureFlags:
    """
    Two-layer feature flag system.

    Layer 1 — Static defaults read from a TradingConfig instance.
    Layer 2 — Runtime overrides persisted in the SQLite ``feature_flags`` table.

    The runtime layer always takes precedence over the config layer.
    Callers should interact exclusively through is_enabled() / set_flag() /
    reset_flag() / list_flags(); direct SQL access is internal.

    Parameters
    ----------
    config:
        A TradingConfig instance (or any object with matching ENABLE_* attributes).
    db:
        A DatabaseManager instance used for persistence.
    """

    def __init__(self, config: Any, db: Any) -> None:
        self._config = config
        self._db = db
        self._ensure_table()
        logger.info("FeatureFlags initialised with %d flag definitions", len(FLAG_DEFINITIONS))

    def _ensure_table(self) -> None:
        """Create the feature_flags table if it does not exist.

        Nothing else in the schema bootstrap owns this table (B3, 2026-06-11:
        the engine logged 'no such table: feature_flags' at every boot and the
        RL autostart gate could only fail-safe instead of reading the flag).
        Failures are logged, not raised, so a degraded DB cannot block engine
        startup -- the first real flag operation will still surface the error.
        """
        try:
            with self._db._lock:
                conn = self._db._connect()
                try:
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS feature_flags (
                            name       TEXT PRIMARY KEY,
                            enabled    INTEGER NOT NULL,
                            updated_at TEXT,
                            updated_by TEXT
                        )
                        """
                    )
                    conn.commit()
                finally:
                    conn.close()
        except Exception as exc:  # pragma: no cover - defensive boot path
            logger.warning("feature_flags table ensure failed (non-fatal): %s", exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_enabled(self, flag_name: str) -> bool:
        """
        Return True if the named flag is enabled.

        Resolution order (highest priority first):
          1. Runtime override in SQLite feature_flags table
          2. Config field on TradingConfig (e.g. settings.ENABLE_KAIROS)
          3. FLAG_DEFINITIONS default value

        Parameters
        ----------
        flag_name:
            Upper-case flag name, e.g. "ENABLE_TILT_DETECTION".

        Returns
        -------
        bool
            Resolved enabled state.
        """
        if flag_name not in _FLAG_META:
            logger.warning("is_enabled called for unknown flag %r — returning False", flag_name)
            return False

        # 1. Check runtime override in SQLite
        runtime = self._get_runtime_override(flag_name)
        if runtime is not None:
            return runtime

        # 2. Check TradingConfig field
        config_val = getattr(self._config, flag_name, None)
        if config_val is not None:
            return bool(config_val)

        # 3. Fall back to FLAG_DEFINITIONS default
        return bool(_FLAG_META[flag_name]["default"])

    def set_flag(self, flag_name: str, enabled: bool, updated_by: str = "api") -> None:
        """
        Persist a runtime override for the named flag to SQLite.

        Parameters
        ----------
        flag_name:
            Upper-case flag name.
        enabled:
            Desired enabled state.
        updated_by:
            Identifier of who/what made the change (default "api").

        Raises
        ------
        ValueError
            If flag_name is not in FLAG_DEFINITIONS.
        """
        if flag_name not in _FLAG_META:
            raise ValueError(
                f"Unknown feature flag: {flag_name!r}. " f"Valid flags: {sorted(_FLAG_META.keys())}"
            )

        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        enabled_int = 1 if enabled else 0

        with self._db._lock:
            conn = self._db._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO feature_flags (name, enabled, updated_at, updated_by)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET
                        enabled    = excluded.enabled,
                        updated_at = excluded.updated_at,
                        updated_by = excluded.updated_by
                    """,
                    (flag_name, enabled_int, now_utc, updated_by),
                )
                conn.commit()
            finally:
                conn.close()

        logger.info("Feature flag %r set to %s by %s", flag_name, enabled, updated_by)

    def reset_flag(self, flag_name: str) -> None:
        """
        Remove the runtime override for the named flag.

        After reset, is_enabled() will fall back to the TradingConfig value
        or the FLAG_DEFINITIONS default.

        Parameters
        ----------
        flag_name:
            Upper-case flag name.

        Raises
        ------
        ValueError
            If flag_name is not in FLAG_DEFINITIONS.
        """
        if flag_name not in _FLAG_META:
            raise ValueError(
                f"Unknown feature flag: {flag_name!r}. " f"Valid flags: {sorted(_FLAG_META.keys())}"
            )

        with self._db._lock:
            conn = self._db._connect()
            try:
                conn.execute("DELETE FROM feature_flags WHERE name = ?", (flag_name,))
                conn.commit()
            finally:
                conn.close()

        logger.info("Feature flag %r runtime override removed (reset to config default)", flag_name)

    def list_flags(self) -> List[Dict[str, Any]]:
        """
        Return metadata for all registered flags including their current state.

        Returns
        -------
        list[dict]
            One dict per flag with keys:
              name, enabled, description, category, requires_restart, source
            where ``source`` is "runtime" if a SQLite override exists, else "config".
        """
        # Load all runtime overrides in one query
        runtime_map: Dict[str, bool] = {}
        with self._db._lock:
            conn = self._db._connect()
            try:
                rows = conn.execute("SELECT name, enabled FROM feature_flags").fetchall()
                for row in rows:
                    runtime_map[row["name"]] = bool(row["enabled"])
            finally:
                conn.close()

        result = []
        for defn in FLAG_DEFINITIONS:
            flag_name = defn["name"]
            if flag_name in runtime_map:
                enabled = runtime_map[flag_name]
                source = "runtime"
            else:
                config_val = getattr(self._config, flag_name, None)
                if config_val is not None:
                    enabled = bool(config_val)
                else:
                    enabled = bool(defn["default"])
                source = "config"

            result.append(
                {
                    "name": flag_name,
                    "enabled": enabled,
                    "description": defn["description"],
                    "category": defn["category"],
                    "requires_restart": defn["requires_restart"],
                    "source": source,
                }
            )

        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_runtime_override(self, flag_name: str) -> Optional[bool]:
        """
        Fetch the runtime override for flag_name from SQLite.

        Returns None if no override exists (caller should fall through to config).
        """
        with self._db._lock:
            conn = self._db._connect()
            try:
                row = conn.execute(
                    "SELECT enabled FROM feature_flags WHERE name = ?", (flag_name,)
                ).fetchone()
            finally:
                conn.close()

        if row is None:
            return None
        return bool(row["enabled"])
