"""Decision-identity fingerprint for the live LLM trading pipeline (P1).

Validating an LLM trader requires knowing *which decision configuration* produced
a trade. This module computes a deterministic fingerprint of the running
pipeline's decision configuration -- everything that, if changed, could change
what the pipeline decides -- and resolves it (per-symbol) to a registered
``decision_lineage`` for forward-test attribution.

Design: docs/design/llm-decision-identity-attribution.md

Two levels:
* ``config_hash``  -- exact SHA-256 of the canonical config snapshot. Changes on
  ANY config change; used for drift detection and reproducibility.
* ``lineage``      -- the per-symbol semantic family graduation is evaluated over.
  Resolved from the decision registry; DEFAULT-MATERIAL: an unregistered hash is
  its own singleton lineage (``unregistered:<hash8>::<SYMBOL>``) and never
  inherits another lineage's forward record.

Everything here is best-effort and fail-open: a fingerprint failure must never
break a trading decision. A degraded fingerprint still carries the pipeline
version so trades are never wholly unattributable.
"""
from __future__ import annotations

import functools
import hashlib
import json
import logging
import os
import subprocess
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Bump on any change to the decision pipeline's CODE that alters behaviour. This
# is the coarse, human-owned version; config_hash captures the fine detail.
PIPELINE_VERSION = "1.0.0"


def _git_sha() -> str:
    """Short git SHA of the running tree (best-effort).

    Prefers an explicit env (set at deploy) so we don't shell out in hot paths;
    falls back to ``git rev-parse`` once, then to 'unknown'.
    """
    env = os.environ.get("JARVIS_GIT_SHA") or os.environ.get("GIT_SHA")
    if env:
        return env[:12]
    try:
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        out = subprocess.run(
            ["git", "-C", here, "rev-parse", "--short=12", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:  # pragma: no cover - git absent / not a repo
        pass
    return "unknown"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _prompt_hashes(is_paper: bool) -> dict[str, str]:
    """SHA-256 of the active system prompt of each decision-steering agent.

    The active variant depends on PAPER_TRADING (a material config), so we hash
    the variant actually in force. Best-effort per agent: an unimportable agent
    is omitted, not fatal.
    """
    targets = [
        ("trader", "agents.trader", "TraderAgent"),
        ("fund", "agents.fund_manager", "FundManagerAgent"),
        ("risk", "agents.risk_manager", "RiskManagerAgent"),
    ]
    out: dict[str, str] = {}
    for key, module_name, cls_name in targets:
        try:
            import importlib

            cls = getattr(importlib.import_module(module_name), cls_name)
            attr = "SYSTEM_PROMPT_PAPER" if is_paper else "SYSTEM_PROMPT_LIVE"
            prompt = getattr(cls, attr, None) or getattr(cls, "SYSTEM_PROMPT", None)
            if isinstance(prompt, str):
                out[key] = _sha(prompt)[:16]
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("decision_identity: prompt hash for %s failed: %s", key, exc)
    return out


def _active_analysts() -> list[str]:
    """The analyst set actually wired, gated by feature flags / env."""
    base = ["technical", "news", "social", "fundamental", "corey", "breakout", "harmonic"]
    if os.environ.get("ENABLE_KRONOS") in ("1", "true", "True"):
        base.append("kronos")
    if os.environ.get("ENABLE_OPTIONS_ANALYST") in ("1", "true", "True"):
        base.append("options")
    return sorted(base)


def _config_snapshot() -> dict[str, Any]:
    """The full canonical configuration the fingerprint hashes over.

    Reads live settings; never raises (missing setting -> omitted key).
    """
    snap: dict[str, Any] = {
        "pipeline_version": PIPELINE_VERSION,
        "git_sha": _git_sha(),
    }
    is_paper = True
    try:
        from config import settings as cfg

        is_paper = bool(getattr(cfg, "PAPER_TRADING", True))
        snap["models"] = {
            "analyst": getattr(cfg, "ANALYST_MODEL", None),
            "trader": getattr(cfg, "TRADER_MODEL", None),
            "fast": getattr(cfg, "FAST_MODEL", None),
        }
        snap["gates"] = {
            "futures_min_conf": getattr(cfg, "FUTURES_MIN_CONFIDENCE_TO_TRADE", None),
            "futures_conf_boost": getattr(cfg, "FUTURES_CONFIDENCE_BOOST", None),
            "mtf_filter": getattr(cfg, "MTF_FILTER_ENABLED", None),
            "stc_oversold": getattr(cfg, "STC_OVERSOLD", None),
            "stc_overbought": getattr(cfg, "STC_OVERBOUGHT", None),
            "paper_trading": is_paper,
        }
    except Exception as exc:  # pragma: no cover - config import issues
        logger.debug("decision_identity: settings snapshot degraded: %s", exc)
    # Autonomous enqueue threshold is env-driven, read fresh each tick.
    snap["gates"] = {
        **snap.get("gates", {}),
        "autonomous_threshold": os.environ.get("AUTONOMOUS_CONFIDENCE_THRESHOLD", "0.65"),
    }
    snap["active_analysts"] = _active_analysts()
    snap["prompt_hashes"] = _prompt_hashes(is_paper)
    return snap


@functools.lru_cache(maxsize=1)
def compute_config_fingerprint() -> dict[str, Any]:
    """The running pipeline's config fingerprint (cached for the process).

    config_hash is a property of the running configuration, NOT of any single
    decision -- the live config is loaded at startup and stable within a process,
    so a trade's fingerprint == the running config that produced it. Cached so the
    fill-mirror can call it per trade for free.
    """
    snap = _config_snapshot()
    canonical = json.dumps(snap, sort_keys=True, separators=(",", ":"), default=str)
    return {"config_hash": _sha(canonical), "snapshot": snap}


def resolve_lineage(
    config_hash: str, symbol: str, registry: Optional[dict] = None
) -> str:
    """Resolve a (config_hash, symbol) to its per-symbol decision lineage.

    DEFAULT-MATERIAL: a config_hash not registered under any lineage gets its own
    singleton ``unregistered:<hash8>::<SYMBOL>`` -- it accrues its own forward
    record and can never inherit a registered lineage's history. Folding a hash
    into an existing lineage is an explicit registry edit (see decision_registry).
    Per-symbol: the lineage id is suffixed with the symbol.
    """
    sym = (symbol or "?").upper()
    base = f"unregistered:{(config_hash or 'none')[:8]}"
    if registry is None:
        try:
            from backtest.decision_registry import load_registry

            registry = load_registry()
        except Exception:  # pragma: no cover - registry optional in P1/P2
            registry = None
    if registry:
        for lin in registry.get("lineages", []):
            if config_hash in (lin.get("member_config_hashes") or []):
                base = str(lin.get("id") or base)
                break
    return f"{base}::{sym}"


def current_decision_identity(symbol: str) -> dict[str, Any]:
    """The decision identity to stamp on a trade for ``symbol``.

    Never raises -- on any failure returns a minimal identity carrying the
    pipeline version so the trade is still attributable to a coarse identity.
    """
    try:
        fp = compute_config_fingerprint()
        chash = fp["config_hash"]
        return {
            "config_hash": chash[:16],
            "pipeline_version": PIPELINE_VERSION,
            "git_sha": fp["snapshot"].get("git_sha", "unknown"),
            "models": fp["snapshot"].get("models", {}),
            "active_analysts": fp["snapshot"].get("active_analysts", []),
            "gates": fp["snapshot"].get("gates", {}),
            "prompt_hashes": fp["snapshot"].get("prompt_hashes", {}),
            "lineage": resolve_lineage(chash, symbol),
            "symbol": (symbol or "?").upper(),
        }
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("decision_identity: current() degraded for %s: %s", symbol, exc)
        return {
            "config_hash": None,
            "pipeline_version": PIPELINE_VERSION,
            "lineage": f"unregistered:degraded::{(symbol or '?').upper()}",
            "symbol": (symbol or "?").upper(),
        }
