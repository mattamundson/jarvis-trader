"""Family-wide Benjamini-Hochberg FDR correction across the gate-v2 campaign.

Gate-v2 validates each strategy *in isolation*. But the campaign runs ~38
strategies x instruments x param-grids, and screening that many candidates
manufactures false positives: at raw p<0.05 you expect ~2 spurious "edges" per
38 tests by chance alone -- the "there's always something significant" illusion.

This module applies a Benjamini-Hochberg false-discovery-rate correction ACROSS
the whole campaign treated as ONE family (mirrors amo-arbitrage's `_bh_fdr`,
PR #44). It is a *secondary* gate: it can only SHRINK the gate-v2-validated set,
never add to it.

FDR family redefinition (P5-1, 2026-08-10): the campaign scanned here (every
gate_v2_verdicts/*.json ever produced) is a POST-HOC discovery set, not a
pre-registered hypothesis family -- it grows every time a new strategy x
instrument x param-grid combination is screened, and which candidates get
screened is itself influenced by earlier results. A family-wide BH line over a
family like that cannot honestly certify a "robust" edge no matter what the
p-values say: pre-registration must happen BEFORE the data is seen
(`candidate_registry.json`'s methodology note), and this module runs entirely
AFTER. So `robust_edge` here is diagnostic-only and is now hard-coded to False
-- it can rank candidates by closeness-to-significance and report the honest
0-survivor campaign result, but it can never authorize. The only path that CAN
certify is the pre-registered forward path in `forward_test.py`
(`run_forward_test`), which recomputes the BH line over exactly the frozen
`candidate_registry.json` active set (n_family == len(active_candidates)) using
independent forward (paper) OOS windows gathered AFTER registration.

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
from datetime import datetime, timezone
from typing import Any

import numpy as np
from scipy.stats import binom

logger = logging.getLogger("jarvis_trader.backtest.family_fdr")

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_VERDICT_DIR = os.path.normpath(os.path.join(_THIS_DIR, "..", "data", "gate_v2_verdicts"))
_REPORT_DIR = os.path.normpath(os.path.join(_THIS_DIR, "..", "data"))
_HISTORY_PATH = os.path.join(_REPORT_DIR, "family_fdr_history.jsonl")

DEFAULT_Q = 0.10

# Minimum total OOS trades for a strategy's PASS to be sample-adequate. Mirrors
# gate-v2's MIN_OOS_TRADES_TOTAL: a "PASS" built on too few OOS trades (e.g. PF
# 295 / inf on 2-trade windows) is a small-sample mirage, not an edge. The
# campaign report must surface this so the lowest-p_binom row is not mistaken
# for "where real edge lives" when it is sample-inadequate.
try:  # pragma: no cover - exercised via the value, not the import path
    from backtest._gate_v2_helpers import MIN_OOS_TRADES_TOTAL as _MIN_OOS_TRADES
except Exception:  # pragma: no cover - defensive fallback if helper moves
    _MIN_OOS_TRADES = 30
MIN_OOS_TRADES = int(_MIN_OOS_TRADES)

# Per-window adequacy floor. The aggregate MIN_OOS_TRADES floor is
# NECESSARY BUT NOT SUFFICIENT: a strategy can clear 30 aggregate OOS trades
# while its per-window samples are 1-4 trades with degenerate PFs (inf/666/295)
# concentrated in a few fat windows. The per-window signal exposes that gap;
# `per_window_adequate` requires the MEDIAN window to clear this floor.
try:  # pragma: no cover - exercised via the value, not the import path
    from backtest._gate_v2_helpers import MIN_OOS_TRADES_PER_WINDOW as _MIN_OOS_TRADES_PW
except Exception:  # pragma: no cover - defensive fallback if helper moves
    _MIN_OOS_TRADES_PW = 5
MIN_OOS_TRADES_PER_WINDOW = int(_MIN_OOS_TRADES_PW)


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


def _total_oos_trades(verdict: dict) -> int | None:
    """Total OOS trades behind the verdict, or None if the field is absent.

    None means "unknown sample size" — distinct from a known-small one. Robust
    edge certification treats unknown as not-adequate (fail-safe), but the report
    shows it as ``?`` rather than a hard inadequacy.
    """
    w = verdict.get("wfo_config") or {}
    v = w.get("total_oos_trades")
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _per_window_oos_trades(verdict: dict) -> list[int] | None:
    """Per-window OOS trade counts from the verdict's ``windows[]``, or None.

    None means the verdict carries no per-window breakdown (legacy / aggregate-
    only / CPCV) — distinct from a known-thin one. Per-window adequacy fails OPEN
    on None: it can only ADD a block when the data is present and shows thin
    windows, never manufacture one from missing data (the aggregate floor still
    applies via ``sample_adequate``).
    """
    windows = verdict.get("windows")
    if not windows or not isinstance(windows, list):
        return None
    counts: list[int] = []
    for w in windows:
        t = (w or {}).get("oos_trades")
        if t is None:
            continue
        try:
            counts.append(int(t))
        except (TypeError, ValueError):
            continue
    return counts or None


def _per_window_adequacy(per_window: list[int] | None) -> dict[str, Any]:
    """Compute the per-window adequacy summary. Absent data -> all-None / None flag."""
    if not per_window:
        return {
            "median_oos_trades_per_window": None,
            "n_thin_windows": None,
            "frac_trades_in_thin_windows": None,
            "per_window_adequate": None,
        }
    median = float(np.median(per_window))
    thin = [t for t in per_window if t < MIN_OOS_TRADES_PER_WINDOW]
    total = sum(per_window)
    return {
        "median_oos_trades_per_window": int(median) if median.is_integer() else round(median, 1),
        "n_thin_windows": len(thin),
        "frac_trades_in_thin_windows": round(sum(thin) / total, 4) if total else 0.0,
        "per_window_adequate": bool(median >= MIN_OOS_TRADES_PER_WINDOW),
    }


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
        # CPCV (combinatorial purged CV) verdicts report len(folds) OOS "windows",
        # but those folds OVERLAP (they resample from a handful of contiguous
        # groups), so they are NOT independent Bernoulli windows. Feeding them
        # into the binomial sign-test -- which assumes independence -- would
        # overstate significance. Per the CPCV design they are additive,
        # non-authorizing evidence, so exclude them from the sign-test family.
        wfo = v.get("wfo_config") or {}
        if str(wfo.get("cv_method") or "").lower() == "cpcv":
            excluded.append(
                {
                    "id": v["_id"],
                    "gate_verdict": v.get("verdict"),
                    "reason": "CPCV folds overlap (not independent OOS windows); "
                    "additive evidence only -- excluded from the sign-test family",
                }
            )
            continue
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
        oos_trades = _total_oos_trades(v)
        sample_adequate = None if oos_trades is None else (oos_trades >= MIN_OOS_TRADES)
        per_window = _per_window_adequacy(_per_window_oos_trades(v))
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
                "total_oos_trades": oos_trades,
                "sample_adequate": sample_adequate,
                **per_window,
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
            # would_survive_binom_fdr mirrors what "robust_edge" used to mean here:
            # gate-v2 PASS AND survives the PRIMARY (binomial) family FDR AND has a
            # sample-adequate OOS trade count AND is not per-window thin. Kept as a
            # diagnostic ranking signal only (P5-1: the campaign family is post-hoc,
            # not pre-registered, so it can never itself authorize -- see module
            # docstring). robust_edge below is hard-coded False for every row.
            r["would_survive_binom_fdr"] = bool(
                r["gate_verdict"] == "PASS"
                and bf
                and r.get("sample_adequate") is True
                and r.get("per_window_adequate") is not False
            )
            # P5-1: the campaign path can never certify -- only the pre-registered
            # forward path (forward_test.run_forward_test, BH-FDR over exactly
            # candidate_registry.json's active set) can set an edge as robust.
            r["robust_edge"] = False

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


def append_history(
    report: dict[str, Any],
    path: str = _HISTORY_PATH,
    ts: str | None = None,
) -> dict[str, Any]:
    """Append one compact JSONL record of this FDR run to a history ledger.

    Lets `robust_edge` drift be tracked across the standing WFO-refresh cadence
    (a single overwriting report hides whether the validated set is shrinking or
    holding). One line per run; never rewrites prior lines. ``ts`` is injectable
    for deterministic tests; defaults to the current UTC timestamp.
    """
    record = {
        "ts": ts or datetime.now(timezone.utc).isoformat(),
        "q": report.get("q"),
        "n_verdicts_total": report.get("n_verdicts_total"),
        "n_family": report.get("n_family"),
        "n_gate_pass": report.get("n_gate_pass"),
        "n_robust_edge": report.get("n_robust_edge"),
        "robust_edge_ids": report.get("robust_edge_ids", []),
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")
    return record


def _markdown(report: dict[str, Any]) -> str:
    q = report["q"]
    lines = [
        "# Family-wide BH-FDR — jarvis gate-v2 campaign",
        "",
        f"- Verdicts total: **{report['n_verdicts_total']}**  |  "
        f"FDR family (have OOS data): **{report['n_family']}**  |  "
        f"excluded (no OOS data): **{report['n_excluded']}**",
        f"- gate-v2 PASS: **{report['n_gate_pass']}**  |  "
        f"would survive family BH-FDR (q={q}) AND gate-PASS = **CLOSEST-TO-ROBUST: "
        f"{sum(1 for r in report['family'] if r.get('would_survive_binom_fdr'))}**  |  "
        f"**ROBUST_EDGE (this path can never certify — see below): "
        f"{report['n_robust_edge']}**",
        "",
        "Primary p-value = binomial sign-test on OOS-window profitability. "
        "`would_survive_binom_fdr` = gate-v2 PASS AND survives the primary family "
        "BH line — a diagnostic ranking signal only. `robust_edge` is hard-coded "
        "False on every row (P5-1): this campaign is a post-hoc discovery set, not "
        "a pre-registered family, so it cannot itself certify an edge. See "
        "`forward_test.py` for the pre-registered path that can.",
        "",
        "| id | gate | pf_ci_lo | p_edge | n_oos | oos_tr | adq | med_tr/win | "
        "thin | pwadq | p_binom | BH-binom | p_dsr | BH-dsr | CLOSEST |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    _adq = {True: "Y", False: "**n**", None: "?"}
    for r in report["family"]:
        _mtw = r.get("median_oos_trades_per_window")
        _nthin = r.get("n_thin_windows")
        lines.append(
            "| {id} | {gv} | {pf} | {pe} | {n} | {ot} | {adq} | {mtw} | {thin} | "
            "{pwadq} | {pb:.4f} | {bb} | {pd} | {bd} | {rob} |".format(
                id=r["id"],
                gv=r["gate_verdict"],
                pf="" if r["pf_ci_lower"] is None else f"{r['pf_ci_lower']:.3f}",
                pe=f"{r['p_edge']:.3f}",
                n=r["n_oos_windows"],
                ot="?" if r.get("total_oos_trades") is None else r["total_oos_trades"],
                adq=_adq[r.get("sample_adequate")],
                mtw="?" if _mtw is None else _mtw,
                thin="?" if _nthin is None else _nthin,
                pwadq=_adq[r.get("per_window_adequate")],
                pb=r["p_binom"],
                bb="Y" if r.get("bh_significant_binom") else "·",
                pd="" if r["p_dsr"] is None else f"{r['p_dsr']:.4f}",
                bd="Y" if r.get("bh_significant_dsr") else "·",
                rob="**YES**" if r.get("would_survive_binom_fdr") else "·",
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
        "- **`robust_edge` is always False here (P5-1)** — this campaign family is "
        "everything gate-v2 has ever screened, which grows with every new run and "
        "was never pre-registered, so a family-wide BH line over it cannot honestly "
        "certify anything. It can only rank candidates and report the honest "
        "survivor count, never authorize. The pre-registered family "
        "(`candidate_registry.json`'s active set) is checked separately in "
        "`forward_test.py`, and only that path can set an edge robust.",
        "- With only 5–19 non-overlapping OOS windows per strategy the binomial "
        "sign-test is deliberately conservative; a strict BH line over a "
        f"{report['n_family']}-member family can reject strong-PF strategies on "
        "window count alone. The ranking (lowest `p_binom` first) shows which "
        "strategies are *closest* to (diagnostically) significant — but read it "
        "together with `adq`.",
        f"- **`adq` = sample adequacy** (total OOS trades >= {MIN_OOS_TRADES}). An "
        "`adq=n` row is a small-sample mirage: its p_binom/PF can look strong while "
        "resting on a handful of OOS trades (PF inflated by 2-trade windows). Such a "
        "row can rank high on p_binom yet is **not** where durable edge lives, and it "
        "can never be `CLOSEST-TO-ROBUST` regardless of the BH line. Treat the "
        "lowest-p_binom `adq=Y` row as the genuine lead.",
        f"- **`pwadq` = per-window adequacy** (MEDIAN window >= "
        f"{MIN_OOS_TRADES_PER_WINDOW} OOS trades; `med_tr/win` and `thin` = count of "
        "windows below that floor). The aggregate `adq` floor is necessary but NOT "
        "sufficient: a strategy can clear 30 aggregate trades while most windows are "
        "1-4 trades with degenerate PFs (inf/666/295) — `pwadq=n` flags exactly that. "
        "A `pwadq=n` row can never be `CLOSEST-TO-ROBUST` even if `adq=Y` (e.g. `trend_rank4`: 67 "
        "aggregate trades, median 4/window, 14 of 19 windows thin). `pwadq=?` means no "
        "per-window data (fails open — the aggregate floor still applies).",
        "- This correction can only SHRINK the validated set. A NO survivor result "
        "is the honest outcome of screening many candidates with few OOS windows, "
        "not proof that no edge exists.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Family-wide BH-FDR over gate-v2 verdicts")
    parser.add_argument("--q", type=float, default=DEFAULT_Q, help="FDR level (default 0.10)")
    parser.add_argument("--json", action="store_true", help="print full JSON report")
    parser.add_argument(
        "--history",
        action="store_true",
        help="append a compact record of this run to family_fdr_history.jsonl",
    )
    parser.add_argument(
        "--history-path",
        default=_HISTORY_PATH,
        help="override the history-ledger path (default data/family_fdr_history.jsonl)",
    )
    args = parser.parse_args()

    report = run(q=args.q)
    md_path = os.path.join(_REPORT_DIR, "family_fdr_report.md")
    json_path = os.path.join(_REPORT_DIR, "family_fdr_report.json")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(_markdown(report))
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)

    if args.history:
        rec = append_history(report, path=args.history_path)
        print(f"[history] n_robust_edge={rec['n_robust_edge']} -> {args.history_path}")

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(_markdown(report))
    print(f"\n[written] {md_path}\n[written] {json_path}")


if __name__ == "__main__":
    main()
