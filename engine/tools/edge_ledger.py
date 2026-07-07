"""Unified honest-edge ledger across BOTH forward-test attribution tracks.

A dependency-light, read-only CLI that answers ONE question honestly:

    "What, across both tracks, currently has *validated* edge -- and what is
     merely tracking or context-only?"

Two tracks feed the ledger (see ``backtest/forward_test.py``):

  * CANDIDATES -- mechanical gate-v2 strategies (``candidate_registry``). They
    only graduate at a precise attribution level; a candidate whose live trades
    attribute at symbol level (``precise_attribution == false``) is *context
    only* and is NEVER a validated edge no matter how strong its stats look.
  * LINEAGES -- LLM decision identities (``decision_registry``). A lineage that
    starts with ``unregistered:`` was never pre-registered as a hypothesis, so
    it is *context only* and likewise never a validated edge.

Honesty rule: only items the upstream report flags ``graduated == True`` count
as validated, and those are exactly the precise-candidate / pre-registered-
lineage rows. Graduation is necessary, not sufficient -- gate-v2 routing still
governs live sizing.

Read-only: no DB writes, no engine mutation. Degrades gracefully when no
forward-test data is available yet (prints a message and exits 0).
"""

from __future__ import annotations

import json
import os
import sys

# ── import shim so this runs from anywhere ──────────────────────────────────────
os.environ.setdefault("API_KEY", "x")
_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

_PERSISTED_REPORT = os.path.join(_ENGINE_ROOT, "data", "forward_test_report.json")


# ── report loading (injectable for tests) ───────────────────────────────────────

def _load_report(live: bool = False):
    """Load the forward-test report dict, or None if no data is available.

    Prefers the persisted ``forward_test_report.json`` unless ``--live`` is
    passed; otherwise runs the loop against the default DB. Any file/DB failure
    degrades to ``None`` rather than crashing.
    """
    if not live and os.path.exists(_PERSISTED_REPORT):
        try:
            with open(_PERSISTED_REPORT, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None
    try:
        from backtest.forward_test import run_forward_test
        return run_forward_test(persist=False)
    except Exception:
        return None


# ── ledger construction (pure, unit-testable) ───────────────────────────────────

def _fmt(value) -> str:
    """Format a numeric stat compactly; '-' for None."""
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def build_ledger(report: dict) -> dict:
    """Turn a forward-test report dict into ``{"verdict": {...}, "rows": [...]}``.

    Honesty rules applied here:
      * a candidate with ``precise_attribution == False`` is STATUS context-only
        and is never counted as a validated edge;
      * a lineage starting with ``unregistered:`` is STATUS context-only and is
        never counted as a validated edge, even with strong stats;
      * only rows the upstream report marks ``graduated == True`` are validated.
    """
    rows: list[dict] = []

    n_grad_candidates = 0
    for c in report.get("candidates") or []:
        f = c.get("forward") or {}
        precise = bool(c.get("precise_attribution"))
        graduated = bool(c.get("graduated"))
        if graduated:
            status = "GRADUATED"
            n_grad_candidates += 1
        elif not precise:
            status = "context-only"
        else:
            status = "tracking"
        rows.append({
            "track": "candidate",
            "id": c.get("id", ""),
            "symbol": c.get("symbol", ""),
            "status": status,
            "graduated": graduated,
            "n_oos": f.get("n_oos_windows"),
            "p_edge": f.get("p_edge"),
            "pf_ci_lower": f.get("pf_ci_lower"),
            "survives_family_fdr": bool(c.get("survives_family_fdr")),
        })

    n_grad_lineages = 0
    for lin in report.get("lineages") or []:
        f = lin.get("forward") or {}
        lineage = str(lin.get("lineage", ""))
        pre_registered = bool(lin.get("pre_registered"))
        graduated = bool(lin.get("graduated"))
        unregistered = lineage.startswith("unregistered:")
        if graduated and not unregistered:
            status = "GRADUATED"
            n_grad_lineages += 1
        elif unregistered or not pre_registered:
            status = "context-only"
        else:
            status = "tracking"
        rows.append({
            "track": "lineage",
            "id": lineage,
            "symbol": "",
            "status": status,
            "graduated": graduated and not unregistered,
            "n_oos": f.get("n_oos_windows"),
            "p_edge": f.get("p_edge"),
            "pf_ci_lower": f.get("pf_ci_lower"),
            "survives_family_fdr": bool(lin.get("survives_family_fdr")),
        })

    # Sort: graduated first, then tracking, then context-only; stable within.
    order = {"GRADUATED": 0, "tracking": 1, "context-only": 2}
    rows.sort(key=lambda r: order.get(r["status"], 3))

    verdict = {
        "n_graduated_candidates": n_grad_candidates,
        "n_graduated_lineages": n_grad_lineages,
        "n_validated_total": n_grad_candidates + n_grad_lineages,
    }
    return {"verdict": verdict, "rows": rows}


def render_table(ledger: dict) -> str:
    """Render the unified ledger as a header verdict + fixed-width table."""
    v = ledger["verdict"]
    lines = [
        f"VALIDATED EDGES: {v['n_graduated_candidates']} mechanical + "
        f"{v['n_graduated_lineages']} LLM-lineage = {v['n_validated_total']}",
        "graduation is necessary, not sufficient -- gate-v2 routing still "
        "governs live sizing",
        "",
    ]
    header = (
        f"{'TRACK':<10} {'ID/LINEAGE':<40} {'SYMBOL':<7} {'STATUS':<13} "
        f"{'N_OOS':>5} {'P_EDGE':>7} {'PF_CI_LO':>9} {'FDR':>3}"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for r in ledger["rows"]:
        lines.append(
            f"{r['track']:<10} {str(r['id'])[:40]:<40} {str(r['symbol']):<7} "
            f"{r['status']:<13} {_fmt(r['n_oos']):>5} {_fmt(r['p_edge']):>7} "
            f"{_fmt(r['pf_ci_lower']):>9} "
            f"{'Y' if r['survives_family_fdr'] else '.':>3}"
        )
    if not ledger["rows"]:
        lines.append("(no candidates or lineages in report)")
    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────────────────────────

def main(argv: list[str], load_report=_load_report) -> int:
    """Tie the pieces together. ``load_report`` is injectable for tests."""
    live = "--live" in argv
    as_json = "--json" in argv

    report = load_report(live=live)
    if report is None:
        print("no forward-test data available yet (no persisted report and no "
              "live DB) -- run the forward-test loop first")
        return 0

    ledger = build_ledger(report)
    if as_json:
        print(json.dumps(ledger, indent=2, default=str))
    else:
        print(render_table(ledger))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
