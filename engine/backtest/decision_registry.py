"""Decision-lineage registry loader (P2 scaffold).

Parallel to ``candidate_registry`` but for LLM decision lineages. P1/P2 ship the
loader + resolution helpers with an empty lineage list (everything resolves
default-material / honest). Graduation evaluation over lineages lands in P4.

Design: docs/design/llm-decision-identity-attribution.md
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_REGISTRY = os.path.join(_HERE, "decision_registry.json")


def load_registry(path: Optional[str] = None) -> dict[str, Any]:
    """Load and lightly validate the decision registry."""
    p = path or _DEFAULT_REGISTRY
    with open(p, encoding="utf-8") as fh:
        reg = json.load(fh)
    if not isinstance(reg, dict) or "lineages" not in reg:
        raise ValueError(f"decision_registry at {p} missing 'lineages'")
    if not isinstance(reg["lineages"], list):
        raise ValueError("decision_registry 'lineages' must be a list")
    return reg


def verify_registry(registry: dict[str, Any]) -> list[str]:
    """Pure structural check; returns a list of problems (empty == ok).

    Enforces the contract the resolver relies on: unique lineage ids, valid
    status, and -- the honesty guard -- no config_hash claimed by more than one
    lineage (which would make attribution ambiguous).
    """
    problems: list[str] = []
    if not isinstance(registry, dict):
        return ["registry is not a JSON object"]
    allowed = set(registry.get("allowed_status", []))
    seen_ids: set[str] = set()
    hash_owner: dict[str, str] = {}
    for lin in registry.get("lineages", []):
        lid = lin.get("id")
        if not lid:
            problems.append("lineage missing id")
            continue
        if lid in seen_ids:
            problems.append(f"duplicate lineage id: {lid}")
        seen_ids.add(lid)
        if allowed and lin.get("status") not in allowed:
            problems.append(f"{lid}: bad status {lin.get('status')!r}")
        for h in lin.get("member_config_hashes") or []:
            if h in hash_owner and hash_owner[h] != lid:
                problems.append(
                    f"config_hash {h[:8]} claimed by both {hash_owner[h]} and {lid}"
                )
            hash_owner[h] = lid
    return problems


def get_active_lineages(registry: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """Lineages currently forward-testing."""
    reg = registry or load_registry()
    return [lin for lin in reg["lineages"] if lin.get("status") == "forward_testing"]


def lineage_for_config_hash(
    config_hash: str, registry: Optional[dict[str, Any]] = None
) -> Optional[str]:
    """The registered lineage id owning ``config_hash`` (None if unregistered)."""
    reg = registry or load_registry()
    for lin in reg["lineages"]:
        if config_hash in (lin.get("member_config_hashes") or []):
            return str(lin.get("id"))
    return None


# ── graduation (P4) ─────────────────────────────────────────────────────────────

UNREGISTERED_PREFIX = "unregistered:"


def is_pre_registered(lineage: str) -> bool:
    """A lineage may graduate only if it was pre-registered (honesty guard).

    Default-material singletons carry the ``unregistered:`` prefix; they were
    never asserted as an edge hypothesis *before* their forward window, so they
    can never graduate -- this is what stops post-hoc cherry-picking of whichever
    config happened to print money.
    """
    return bool(lineage) and not str(lineage).startswith(UNREGISTERED_PREFIX)


def meets_graduation(
    forward_stats: dict[str, Any], registry: Optional[dict[str, Any]] = None
) -> bool:
    """True when a lineage's forward (paper) OOS stats clear the graduation rule.

    Reuses the candidate-registry rule evaluator (identical ``graduation_rule``
    schema) so the mechanical and LLM tracks graduate on exactly the same bar.
    Missing stat keys default to the conservative (fail) value.
    """
    from backtest.candidate_registry import meets_graduation as _meets  # acyclic

    reg = registry or load_registry()
    return _meets(forward_stats, reg)
