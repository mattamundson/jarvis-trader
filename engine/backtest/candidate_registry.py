"""Pre-registered candidate registry for forward-testing (north-star ROI #6).

Screening many strategy x instrument x param-grid combinations manufactures
false positives -- the family-wide BH-FDR over the gate-v2 campaign finds 0 of 34
OOS-scored verdicts survive (see ``family_fdr.py``). The honest path to a *new*
validated edge is to **freeze** a small candidate set with explicit hypotheses
and locked params BEFORE forward-testing, then judge each candidate only on
independent forward (paper) out-of-sample windows. This module is the loader +
validator for that frozen registry (``engine/data/candidate_registry.json``).

Design rules enforced here:
  * every candidate has a stable ``id``, a ``symbol``, a ``hypothesis`` and a
    non-empty ``params`` block;
  * ``id`` is unique (you register a *new* id rather than mutating params);
  * ``status`` is drawn from the registry's ``allowed_status`` set;
  * ``lock_in_sample`` records the in-sample stats AT registration time, so
    forward results can be compared against the frozen expectation.

The companion forward-test loop (ROI #2) reads ``get_active_candidates()`` and,
per candidate, accumulates forward OOS windows until ``meets_graduation()`` is
satisfied. Graduation is necessary -- not sufficient -- for live sizing; gate-v2
(``GATE_V2_ENFORCE_ROUTING``) still governs routing.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
# The registry is a committed SOURCE lock (not runtime output), so it lives next
# to this loader rather than under the gitignored engine/data/ runtime dir.
_DEFAULT_REGISTRY = os.path.join(_HERE, "candidate_registry.json")

_REQUIRED_CANDIDATE_FIELDS = ("id", "symbol", "family", "status", "hypothesis", "params")
_REQUIRED_TOP_FIELDS = ("schema_version", "candidates", "allowed_status", "graduation_rule")


def load_registry(path: Optional[str] = None) -> dict[str, Any]:
    """Load and validate the candidate registry.

    Raises ``ValueError`` if the registry is structurally invalid, so a caller
    never silently forward-tests against a malformed lock file.
    """
    path = path or _DEFAULT_REGISTRY
    with open(path, encoding="utf-8") as fh:
        registry = json.load(fh)
    problems = verify_registry(registry)
    if problems:
        raise ValueError(
            "candidate_registry is invalid:\n  - " + "\n  - ".join(problems)
        )
    return registry


def verify_registry(registry: dict[str, Any]) -> list[str]:
    """Return a list of structural problems (empty list == valid).

    Pure / side-effect free so it can be unit-tested and reused by a CI check.
    """
    problems: list[str] = []
    if not isinstance(registry, dict):
        return ["registry is not a JSON object"]

    for field in _REQUIRED_TOP_FIELDS:
        if field not in registry:
            problems.append(f"missing top-level field '{field}'")

    allowed = set(registry.get("allowed_status") or [])
    if not allowed:
        problems.append("allowed_status is empty or missing")

    candidates = registry.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        problems.append("candidates must be a non-empty list")
        return problems

    seen_ids: set[str] = set()
    for i, cand in enumerate(candidates):
        if not isinstance(cand, dict):
            problems.append(f"candidate[{i}] is not an object")
            continue
        cid = cand.get("id")
        label = cid or f"index {i}"
        for field in _REQUIRED_CANDIDATE_FIELDS:
            if not cand.get(field):
                problems.append(f"candidate '{label}' missing/empty '{field}'")
        if cid:
            if cid in seen_ids:
                problems.append(f"duplicate candidate id '{cid}'")
            seen_ids.add(cid)
        if allowed and cand.get("status") and cand["status"] not in allowed:
            problems.append(
                f"candidate '{label}' status '{cand['status']}' not in allowed_status"
            )
        params = cand.get("params")
        if not isinstance(params, dict) or not params:
            problems.append(f"candidate '{label}' params must be a non-empty object")
    return problems


def get_active_candidates(registry: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """Candidates currently being forward-tested (status == 'forward_testing')."""
    reg = registry or load_registry()
    return [c for c in reg["candidates"] if c.get("status") == "forward_testing"]


def get_candidate(
    candidate_id: str, registry: Optional[dict[str, Any]] = None
) -> Optional[dict[str, Any]]:
    """Look up a single candidate by id (None if absent)."""
    reg = registry or load_registry()
    for c in reg["candidates"]:
        if c.get("id") == candidate_id:
            return c
    return None


def live_candidate_for_symbol(
    symbol: str, registry: Optional[dict[str, Any]] = None
) -> Optional[str]:
    """The candidate_id whose EXACT params the live scanner trades for ``symbol``.

    Returns the id of the single ``deployed_live: true`` candidate for the symbol,
    used by the paper-entry path to tag new trades so forward-testing attributes
    them at the precise (graduating) level.

    Fail-safe: returns None when zero candidates are deployed for the symbol OR
    when more than one is (ambiguous) -- a wrong tag corrupts attribution, so the
    ambiguous case must stay untagged (symbol-level context only), never guessed.
    """
    if not symbol:
        return None
    reg = registry or load_registry()
    sym = symbol.upper()
    deployed = [
        c
        for c in reg["candidates"]
        if c.get("deployed_live") is True
        and str(c.get("symbol", "")).upper() == sym
    ]
    if len(deployed) != 1:
        return None
    return deployed[0].get("id")


def meets_graduation(
    forward_stats: dict[str, Any], registry: Optional[dict[str, Any]] = None
) -> bool:
    """True when forward (paper) OOS stats clear the registry graduation rule.

    ``forward_stats`` is expected to expose: ``n_oos_windows`` (int),
    ``pf_ci_lower`` (float), ``p_edge`` (float), and ``survives_family_fdr``
    (bool). Missing keys default to the most conservative (fail) value, so a
    half-populated stat block can never accidentally graduate a candidate.
    """
    reg = registry or load_registry()
    rule = reg.get("graduation_rule") or {}

    n = int(forward_stats.get("n_oos_windows", 0) or 0)
    pf = float(forward_stats.get("pf_ci_lower", 0.0) or 0.0)
    p_edge = float(forward_stats.get("p_edge", 0.0) or 0.0)
    fdr_ok = bool(forward_stats.get("survives_family_fdr", False))

    if n < int(rule.get("min_forward_oos_windows", 1)):
        return False
    if pf < float(rule.get("min_forward_pf_ci_lower", 0.0)):
        return False
    if p_edge < float(rule.get("min_forward_p_edge", 0.0)):
        return False
    if rule.get("must_survive_family_fdr", False) and not fdr_ok:
        return False
    return True


def summarize(registry: Optional[dict[str, Any]] = None) -> str:
    """Human-readable one-screen summary of the registry."""
    reg = registry or load_registry()
    lines = [
        f"Candidate registry v{reg.get('schema_version')} "
        f"(registered {reg.get('registered_at')})",
        f"{len(reg['candidates'])} candidates "
        f"({len(get_active_candidates(reg))} forward_testing)",
        "",
        f"{'id':<32} {'sym':<4} {'status':<14} {'pf_ci_lo':>8} {'p_edge':>7} {'n_oos':>5}",
    ]
    for c in reg["candidates"]:
        s = c.get("lock_in_sample") or {}
        lines.append(
            f"{c['id']:<32} {c['symbol']:<4} {c['status']:<14} "
            f"{s.get('pf_ci_lower', 0):>8} {s.get('p_edge', 0):>7} "
            f"{s.get('n_oos_windows', 0):>5}"
        )
    return "\n".join(lines)


def main() -> None:  # pragma: no cover - thin CLI wrapper
    print(summarize())


if __name__ == "__main__":  # pragma: no cover
    main()
