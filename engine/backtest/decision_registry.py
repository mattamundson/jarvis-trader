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


# Strategy classes a lineage may declare. ``llm`` is the historical default (LLM
# decision identities); the other three are systematic/non-LLM units routed through
# the SAME lineage track (R1). Each non-llm class carries extra required fields so a
# reviewer can see exactly what was pre-registered.
ALLOWED_STRATEGY_TYPES = ("llm", "mechanical", "spread", "calendar")
# field -> classes that must declare it (besides the universal ``inception`` for non-llm)
_REQUIRED_BY_TYPE: dict[str, tuple[str, ...]] = {
    "spread": ("legs", "composite_symbol"),
    "calendar": ("rule", "vehicle"),
}


def verify_registry(registry: dict[str, Any]) -> list[str]:
    """Pure structural check; returns a list of problems (empty == ok).

    Enforces the contract the resolver relies on: unique lineage ids, valid
    status, no config_hash claimed by more than one lineage (attribution
    ambiguity), and -- for non-LLM strategy classes (R1) -- the class-specific
    fields plus a machine-checkable ``inception`` date (pre-registration must
    predate the forward window).
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
                problems.append(f"config_hash {h[:8]} claimed by both {hash_owner[h]} and {lid}")
            hash_owner[h] = lid

        # Strategy-class contract (R1). Absent strategy_type == "llm" (back-compat).
        stype = lin.get("strategy_type", "llm")
        if stype not in ALLOWED_STRATEGY_TYPES:
            problems.append(
                f"{lid}: bad strategy_type {stype!r} (allowed: {ALLOWED_STRATEGY_TYPES})"
            )
            continue
        if stype != "llm":
            if not lin.get("inception"):
                problems.append(
                    f"{lid}: {stype} lineage missing 'inception' (pre-registration date)"
                )
            for field in _REQUIRED_BY_TYPE.get(stype, ()):
                if not lin.get(field):
                    problems.append(f"{lid}: {stype} lineage missing '{field}'")
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


def is_pre_registered(lineage: str, registry: Optional[dict[str, Any]] = None) -> bool:
    """A lineage may graduate only if it was pre-registered (honesty guard).

    Default-material singletons carry the ``unregistered:`` prefix; they were
    never asserted as an edge hypothesis *before* their forward window, so they
    can never graduate -- this is what stops post-hoc cherry-picking of whichever
    config happened to print money.

    When ``registry`` is provided, the check is strengthened to require actual
    membership: the lineage's id stem (the part before ``::``) must be a
    registered lineage id. This is what keeps an intentionally-UNregistered but
    cleanly-stamped track (e.g. ``es_nq_spread_v1::ES_NQ_SPREAD``) context-only
    instead of silently graduation-eligible. With no registry, the historical
    prefix-only behaviour is preserved (back-compat).
    """
    if not lineage or str(lineage).startswith(UNREGISTERED_PREFIX):
        return False
    if registry is None:
        return True
    stem = str(lineage).split("::", 1)[0]
    registered_ids = {lin.get("id") for lin in registry.get("lineages", [])}
    return stem in registered_ids


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
