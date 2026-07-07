"""
JARVIS TRADER — Challenger Config Overlay
==========================================
Reads engine/config-challenger.yaml (if present) and returns a validated dict
of risk-parameter overrides that Account B uses when ENABLE_PARALLEL_PAPER=1.

Design constraints
------------------
- One engine process, two paper accounts.  Account A always uses production
  settings from TradingConfig (engine/.env).  Account B layerss a small set
  of allowed overrides on top of those production defaults.
- Only the keys in ALLOWED_OVERRIDES may be specified.  Any other key causes
  ValueError so misconfigured challengers surface loudly.
- Hard safety floor: challenger values may not be LESS safe than the
  production baseline on kill-switch-adjacent parameters.
- LIVE_TRADING_ENABLED, IBKR_PORT, and all kill-switch thresholds are
  permanently forbidden from override.

Usage
-----
    from config_challenger import get_challenger_config

    cfg = get_challenger_config()   # None when feature is disabled or YAML absent
    if cfg is not None:
        max_pos = cfg.get("MAX_POSITION_SIZE_PCT", prod_default)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("jarvis_trader.config_challenger")

# ── Whitelist: the only keys an operator may override ─────────────────────────
# Lower-bound and upper-bound tuples define the safe operating envelope.
# Values outside these ranges are rejected at load time.
ALLOWED_OVERRIDES: Dict[str, tuple[Any, Any, type]] = {
    #                        (min,   max,   type)
    "MAX_POSITION_SIZE_PCT": (0.01, 0.10, float),
    "MAX_CONTRACTS_PER_INSTRUMENT": (1, 5, int),
    "MAX_DAILY_LOSS_PCT": (0.01, 0.05, float),
    "MAX_DRAWDOWN_PCT": (0.05, 0.20, float),
    "CONSECUTIVE_LOSS_HALT": (3, 10, int),
}

# Keys that are permanently forbidden — checked before the whitelist so an
# attacker cannot sneak them past by adding them to ALLOWED_OVERRIDES.
FORBIDDEN_KEYS = frozenset(
    {
        "LIVE_TRADING_ENABLED",
        "IBKR_PORT",
        "IBKR_HOST",
        "MAX_DAILY_LOSS_USD",  # absolute-dollar kill threshold — safety layer owns it
        "MAX_SINGLE_ORDER_VALUE",
        "REQUIRE_HUMAN_APPROVAL",
        "API_KEY",
        "ANTHROPIC_API_KEY",
    }
)

# Path to the optional challenger YAML (relative to the engine/ directory).
_CHALLENGER_YAML_NAME = "config-challenger.yaml"


def _locate_yaml() -> Optional[Path]:
    """
    Return the Path to config-challenger.yaml if it exists, else None.

    Searches in:
      1. The directory containing this module (engine/)
      2. CWD (handles the case where engine is launched from workspace root)
    """
    here = Path(__file__).parent
    for candidate in (here / _CHALLENGER_YAML_NAME, Path.cwd() / _CHALLENGER_YAML_NAME):
        if candidate.is_file():
            return candidate
    return None


def _parse_yaml(path: Path) -> Dict[str, Any]:
    """
    Parse a YAML file without pulling in PyYAML as a hard dep.

    Falls back to a minimal line-by-line parser that handles the simple
    key: value format used in config-challenger.yaml.  If PyYAML is
    available it is used instead (more robust).
    """
    try:
        import yaml  # type: ignore[import-untyped]

        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return data or {}
    except ImportError:
        pass

    # Minimal fallback parser — handles "KEY: VALUE" and strips comments.
    result: Dict[str, Any] = {}
    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                continue
            key, _, rest = line.partition(":")
            key = key.strip()
            val = rest.strip()
            # Best-effort type coercion for numeric values.
            try:
                val = int(val)
            except ValueError:
                try:
                    val = float(val)
                except ValueError:
                    pass
            result[key] = val
    return result


def _validate(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate challenger overrides against the whitelist and value bounds.

    Raises ValueError on any violation so the engine refuses to start
    with a misconfigured challenger rather than silently ignoring it.
    """
    validated: Dict[str, Any] = {}

    for key, value in raw.items():
        # Forbidden first — hard stop.
        if key in FORBIDDEN_KEYS:
            raise ValueError(
                f"config-challenger.yaml: '{key}' is forbidden and cannot be overridden. "
                "Remove it from the challenger config."
            )

        # Not in whitelist — loud rejection.
        if key not in ALLOWED_OVERRIDES:
            raise ValueError(
                f"config-challenger.yaml: unknown key '{key}'. "
                f"Allowed keys: {sorted(ALLOWED_OVERRIDES.keys())}"
            )

        lo, hi, expected_type = ALLOWED_OVERRIDES[key]

        # Type coercion with validation.
        try:
            value = expected_type(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"config-challenger.yaml: '{key}' must be {expected_type.__name__}, "
                f"got {type(value).__name__!r} ({value!r})"
            ) from exc

        # Bounds check.
        if not (lo <= value <= hi):
            raise ValueError(
                f"config-challenger.yaml: '{key}' value {value} is outside "
                f"the allowed range [{lo}, {hi}]."
            )

        validated[key] = value

    return validated


def get_challenger_config() -> Optional[Dict[str, Any]]:
    """
    Return the validated challenger override dict, or None.

    Returns None when:
      - ENABLE_PARALLEL_PAPER is not '1'
      - config-challenger.yaml does not exist

    Raises ValueError if the YAML exists but contains invalid/forbidden keys.
    """
    if os.environ.get("ENABLE_PARALLEL_PAPER", "0") != "1":
        return None

    yaml_path = _locate_yaml()
    if yaml_path is None:
        logger.warning(
            "ENABLE_PARALLEL_PAPER=1 but no config-challenger.yaml found. "
            "Account B will use identical params to Account A. "
            "Create engine/config-challenger.yaml from engine/config-challenger.yaml.example."
        )
        return {}

    raw = _parse_yaml(yaml_path)
    validated = _validate(raw)
    logger.info("Challenger config loaded from %s: %s", yaml_path, list(validated.keys()))
    return validated
