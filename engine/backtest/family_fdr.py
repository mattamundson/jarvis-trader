"""Family-wide Benjamini-Hochberg FDR correction across the gate-v2 campaign.

Gate-v2 validates each strategy *in isolation*. But the campaign runs ~38
strategies x instruments x param-grids, and screening that many candidates
manufactures false positives: at raw p<0.05 you expect ~2 spurious "edges" per
38 tests by chance alone -- the "there's always something significant" illusion.

This module applies a Benjamini-Hochberg false-discovery-rate correction ACROSS
the whole campaign treated as ONE family (mirrors amo-arbitrage's `_bh_fdr`,
PR #44). It is a *secondary* gate: it can only SHRINK the gate-v2-validated set,
never add to it.

Per-strategy p-value
--------------------
PRIMARY -- a binomial sign-test on out-of-sample window profitability. Under H0
(no edge) each OOS window is profitable with probability 0.5, so the count of
profitable windows ~ Binomial(n, 0.5) and the one-sided p-value is P(X >= k),
where k = round(p_edge * n) and p_edge is the stored fraction of profitable OOS
windows. This is fully reproducible from the stored verdict and makes no
distributional assumption beyond the sign test.

SECONDARY (sensitivity) -- 1 - deflated_sharpe. The DSR is already deflated for
within-strategy trial count (Lopez de Prado), so 1-DSR is a within-strategy
null probability. Reported alongside the primary so the reader can see whether
the conclusion is robust to the choice of statistic. NOT used for the actionable
verdict because the stored DSR saturates to {0, 1} for many strategies.

Honesty note: with only 5-19 OOS windows per strategy the binomial test is
*conservative* (under-powered) -- a strict family-wide BH line in a ~34-member
family can reject everything even when a strategy has a strong PF CI. That is a
real property of the data (too few non-overlapping OOS windows), not a bug, and
it is surfaced explicitly in the report rather than hidden.
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
import os
from typing import Any

import numpy as np
from scipy.stats import binom

logger = logging.getLogger("jarvis_trader.backtest.family_fdr")

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_VERDICT_DIR = os.path.normpath(os.path.join(_THIS_DIR, "..", "data", "gate_v2_verdicts"))
_REPORT_DIR = os.path.normpath(os.path.join(_THIS_DIR, "..", "data"))

DEFAULT_Q = 0.10


def bh_fdr(pvals: list[float], q: float = DEFAULT_Q) -> list[bool]:
    """Benjamini-Hochberg FDR control at level ``q``.

    Returns a bool per input p-value (original order): True == discovery survives
    the BH line. Guarantees the expected proportion of false discoveries <= q.
    Identical algorithm to amo-arbitrage ``seasonals._bh_fdr`` (PR #44), with the
    level exposed as a parameter.
    """
    n = len(pvals)
    if n == 0:
        return []
    order = np.argsort(pvals)
    ranked = np.asarray(pvals, dtype=float)[order]
    thresh = q * (np.arange(1, n + 1) / n)
    passed = ranked <= thresh
    flags = [False] * n
    if passed.any():
        kmax = int(np.max(np.where(passed)[0]))  # largest rank meeting the BH line
        cutoff = ranked[kmax]
        for orig_idx in order:
            flags[orig_idx] = bool(pvals[orig_idx] <= cutoff)
    return flags


def binomial_oos_pvalue(p_edge: float, n_windows: int) -> float:
    """One-sided sign-test p-value: P(X >= k) for X ~ Binomial(n_windows, 0.5).

    k = round(p_edge * n_windows) profitable OOS windows. p_edge is the stored
    fraction of profitable OOS windows. Returns 1.0 for n_windows <= 0.
    """
    if n_windows <= 0:
        return 1.0
    k = int(round(p_edge * n_windows))
    k = max(0, min(k, n_windows))
    return float(binom.sf(k - 1, n_windows, 0.5))  # P(X >= k)


def _n_oos(verdict: dict) -> int:
    w = verdict.get("wfo_config") or {}
    for key in ("n_oos_windows", "n_windows"):
        v = w.get(key)
        if v:
            try:
                return int(v)
            except (TypeError, ValueError):
                continue
    return 0


def load_verdicts(verdict_dir: str = _VERDICT_DIR) -> list[dict]:
    """Load every gate-v2 verdict JSON, tagging each with its file id."""
    out: list[dict] = []
    for path in sorted(glob.glob(os.path.join(verdict_dir, "*.json"))):
        try:
            d = json.load(open(path, encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("family_fdr: skipping unreadable %s: %s", path, exc)
            continue
        d["_id"] = os.path.basename(path).replace(".json", "")
        out.append(d)
    return out


def build_family(verdicts: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split verdicts into the FDR family (have OOS data) and the excluded set.

    Excluded strategies carry no computable p-value (missing/zero OOS windows);
    they are reported explicitly, never silently dropped.
    """
    family: list[dict] = []
    excluded: list[dict] = []
    for v in verdicts:
        m = v.get("gate_v2_metrics") or {}
        n = _n_oos(v)
        p_edge = m.get("p_edge")
        if n <= 0 or p_edge is None:
            excluded.append(
                {
                    "id": v["_id"],
                    "gate_verdict": v.get("verdict"),
                    "reason": "no OOS-window data (cannot compute family p-value)",
                }
            )
            continue
        dsr = m.get("dsr")
        family.append(
            {
                "id": v["_id"],
                "symbol": v.get("symbol"),
                "family": v.get("family"),
                "gate_verdict": v.get("verdict"),
                "pf_ci_lower": m.get("pf_ci_lower"),
                "p_edge": float(p_edge),
                "n_oos_windows": n,
                "k_profitable": int(round(float(p_edge) * n)),
                "dsr": dsr,
                "p_binom": binomial_oos_pvalue(float(p_edge), n),
                "p_dsr": (None if dsr is None else max(0.0, 1.0 - float(dsr))),
            }
        )
    return family, excluded


def run(q: float = DEFAULT_Q, verdict_dir: str = _VERDICT_DIR) -> dict[str, Any]:
    """Compute the family-wide FDR report. Pure function -- no file writes."""
    verdicts = load_verdicts(verdict_dir)
    family, excluded = build_family(verdicts)

    if family:
        binom_flags = bh_fdr([r["p_binom"] for r in family], q)
        # DSR sensitivity uses only rows that have a DSR; map back by index.
        dsr_idx = [i for i, r in enumerate(family) if r["p_dsr"] is not None]
        dsr_flags_compact = bh_fdr([family[i]["p_dsr"] for i in dsr_idx], q)
        dsr_flags = [False] * len(family)
        for compact_i, fam_i in enumerate(dsr_idx):
            dsr_flags[fam_i] = dsr_flags_compact[compact_i]
        for r, bf, df in zip(family, binom_flags, dsr_flags, strict=True):
            r["bh_significant_binom"] = bool(bf)
            r["bh_significant_dsr"] = bool(df)
            # Actionable: gate-v2 PASS AND survives the PRIMARY (binomial) family FDR.
            r["robust_edge"] = bool(r["gate_verdict"] == "PASS" and bf)

    family_sorted = sorted(family, key=lambda r: r["p_binom"])
    gate_pass = [r for r in family_sorted if r["gate_verdict"] == "PASS"]
    robust = [r for r in family_sorted if r.get("robust_edge")]

    return {
        "q": q,
        "n_verdicts_total": len(verdicts),
        "n_family": len(family),
        "n_excluded": len(excluded),
        "n_gate_pass": len(gate_pass),
        "n_robust_edge": len(robust),
        "family": family_sorted,
        "excluded": excluded,
        "gate_pass_ids": [r["id"] for r in gate_pass],
        "robust_edge_ids": [r["id"] for r in robust],
    }


def _markdown(report: dict[str, Any]) -> str:
    q = report["q"]
    lines = [
        "# Family-wide BH-FDR — jarvis gate-v2 campaign",
        "",
        f"- Verdicts total: **{report['n_verdicts_total']}**  |  "
        f"FDR family (have OOS data): **{report['n_family']}**  |  "
        f"excluded (no OOS data): **{report['n_excluded']}**",
        f"- gate-v2 PASS: **{report['n_gate_pass']}**  |  "
        f"survive family BH-FDR (q={q}) AND gate-PASS = **ROBUST_EDGE: "
        f"{report['n_robust_edge']}**",
        "",
        "Primary p-value = binomial sign-test on OOS-window profitability. "
        "`robust_edge` = gate-v2 PASS AND survives the primary family BH line.",
        "",
        "| id | gate | pf_ci_lo | p_edge | n_oos | p_binom | BH-binom | p_dsr | BH-dsr | ROBUST |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in report["family"]:
        lines.append(
            "| {id} | {gv} | {pf} | {pe} | {n} | {pb:.4f} | {bb} | {pd} | {bd} | {rob} |".format(
                id=r["id"],
                gv=r["gate_verdict"],
                pf="" if r["pf_ci_lower"] is None else f"{r['pf_ci_lower']:.3f}",
                pe=f"{r['p_edge']:.3f}",
                n=r["n_oos_windows"],
                pb=r["p_binom"],
                bb="Y" if r.get("bh_significant_binom") else "·",
                pd="" if r["p_dsr"] is None else f"{r['p_dsr']:.4f}",
                bd="Y" if r.get("bh_significant_dsr") else "·",
                rob="**YES**" if r.get("robust_edge") else "·",
            )
        )
    if report["excluded"]:
        lines += ["", "## Excluded (no OOS-window data — no family p-value)", ""]
        for e in report["excluded"]:
            lines.append(f"- `{e['id']}` (gate={e['gate_verdict']}) — {e['reason']}")
    lines += [
        "",
        "## Honest read",
        "",
        f"- **{report['n_robust_edge']}** strategies are both gate-v2 PASS and "
        "survive the whole-campaign BH-FDR. ",
        "- With only 5–19 non-overlapping OOS windows per strategy the binomial "
        "sign-test is deliberately conservative; a strict BH line over a "
        f"{report['n_family']}-member family can reject strong-PF strategies on "
        "window count alone. The ranking (lowest `p_binom` first) shows which "
        "strategies are *closest* to robust — that is where real edge, if any, lives.",
        "- This correction can only SHRINK the validated set. A NO survivor result "
        "is the honest outcome of screening many candidates with few OOS windows, "
        "not proof that no edge exists.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Family-wide BH-FDR over gate-v2 verdicts")
    parser.add_argument("--q", type=float, default=DEFAULT_Q, help="FDR level (default 0.10)")
    parser.add_argument("--json", action="store_true", help="print full JSON report")
    args = parser.parse_args()

    report = run(q=args.q)
    md_path = os.path.join(_REPORT_DIR, "family_fdr_report.md")
    json_path = os.path.join(_REPORT_DIR, "family_fdr_report.json")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(_markdown(report))
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(_markdown(report))
    print(f"\n[written] {md_path}\n[written] {json_path}")


if __name__ == "__main__":
    main()
