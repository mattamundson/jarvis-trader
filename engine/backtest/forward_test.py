"""Forward-test loop for the pre-registered candidate set (north-star ROI #2).

In-sample backtesting cannot prove edge -- the family-wide BH-FDR finds 0 of 34
gate-v2 verdicts survive whole-campaign correction (see ``family_fdr.py``). The
only honest path to a *new* validated edge is to forward-test the frozen
candidates (``candidate_registry.py``) on **independent paper out-of-sample
windows** and graduate a candidate only when its forward record clears the
registry's fail-closed graduation rule.

This module is the loop: for each active candidate it gathers the paper trades
attributable to it, buckets them into non-overlapping forward OOS windows,
computes the same statistics the gate uses (per-window PF, bootstrap PF-CI
lower, p_edge), runs a family-wide BH-FDR across the candidate set, and asks
``candidate_registry.meets_graduation()``.

Attribution -- how a paper trade maps to a candidate -- uses the most precise
signal available, in order:
  1. ``candidate_id``   strategy_params carries an explicit candidate_id tag
                        (stamp it via ``tag_strategy_params`` when a registry
                        candidate fires; this is the only level that can GRADUATE
                        a candidate).
  2. ``params``         strategy_params contains every locked param of the
                        candidate with equal values.
  3. ``symbol``         same instrument -- a *context* fallback for liveness when
                        trades are untagged. It cannot disambiguate candidates
                        that share a symbol, so it never graduates one.

Today's live paper trades are scanner-sourced and untagged, so the loop reports
symbol-level context now and becomes per-candidate the moment trades are tagged.
Graduation is necessary, not sufficient, for live sizing -- gate-v2 still routes.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from backtest._gate_v2_helpers import bootstrap_pf_ci_lower
from backtest.candidate_registry import (
    get_active_candidates,
    load_registry,
    meets_graduation,
)
from backtest.family_fdr import bh_fdr, binomial_oos_pvalue

DEFAULT_WINDOW_DAYS = 30
_PRECISE_LEVELS = ("candidate_id", "params")
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPORT_JSON = os.path.normpath(os.path.join(_HERE, "..", "data", "forward_test_report.json"))
_REPORT_MD = os.path.normpath(os.path.join(_HERE, "..", "data", "forward_test_report.md"))


# ── attribution ───────────────────────────────────────────────────────────────

def _parse_params(raw: Any) -> dict:
    """strategy_params may be a dict, a JSON string, or None -> always a dict."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            val = json.loads(raw)
            return val if isinstance(val, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def attribution_level(trade: dict, candidate: dict) -> Optional[str]:
    """Most precise level at which ``trade`` is attributable to ``candidate``."""
    sp = _parse_params(trade.get("strategy_params"))
    if sp.get("candidate_id") == candidate["id"]:
        return "candidate_id"
    locked = candidate.get("params") or {}
    # params match only counts when the locked params are concrete values (not the
    # "note"-only placeholder used for id-locked MES candidates).
    concrete = {k: v for k, v in locked.items() if k != "note"}
    if concrete and all(sp.get(k) == v for k, v in concrete.items()):
        return "params"
    if str(trade.get("symbol", "")).upper() == str(candidate.get("symbol", "")).upper():
        return "symbol"
    return None


def attributable_trades(trades: list[dict], candidate: dict) -> tuple[Optional[str], list[dict]]:
    """Return (best_level, trades) -- the most precise level that yields any trades."""
    buckets: dict[str, list[dict]] = {"candidate_id": [], "params": [], "symbol": []}
    for t in trades:
        lvl = attribution_level(t, candidate)
        if lvl:
            buckets[lvl].append(t)
    for level in ("candidate_id", "params", "symbol"):
        if buckets[level]:
            return level, buckets[level]
    return None, []


# ── decision-lineage attribution (P4) ───────────────────────────────────────────
#
# The live entry path is LLM-driven, not mechanical, so registry candidates never
# fire live and only ever attribute at symbol level (never graduate). P2 stamps a
# ``decision_identity`` onto each live paper entry; this track groups trades by that
# identity's per-symbol ``lineage`` -- the unit that actually trades -- and graduates
# it against the decision_registry on the same statistical bar.

def trade_lineage(trade: dict) -> Optional[str]:
    """The per-symbol decision lineage stamped on a paper trade (P2), or None."""
    sp = _parse_params(trade.get("strategy_params"))
    did = sp.get("decision_identity")
    if isinstance(did, dict):
        lin = did.get("lineage")
        return str(lin) if lin else None
    return None


def lineage_buckets(trades: list[dict]) -> dict[str, list[dict]]:
    """Group closed trades by their stamped decision lineage (untagged dropped)."""
    out: dict[str, list[dict]] = {}
    for t in trades:
        lin = trade_lineage(t)
        if lin:
            out.setdefault(lin, []).append(t)
    return out


# ── windows + stats ────────────────────────────────────────────────────────────

def _window_pf(gross_win: float, gross_loss: float) -> float:
    if gross_loss > 0:
        return gross_win / gross_loss
    if gross_win > 0:
        return float("inf")  # bootstrap_pf_ci_lower caps inf at 5.0
    return 1.0  # no wins and no losses -> neutral


def build_windows(trades: list[dict], window_days: int = DEFAULT_WINDOW_DAYS) -> list[dict]:
    """Bucket closed trades into non-overlapping forward OOS windows by exit date.

    Windows are anchored at the first exit and are ``window_days`` wide. Empty
    windows (no trades) are dropped -- a window with no trades is no signal.
    """
    dated = []
    for t in trades:
        et = t.get("exit_time")
        pnl = t.get("pnl")
        if not et or pnl is None:
            continue
        try:
            d = datetime.fromisoformat(str(et).replace("Z", "+00:00"))
        except ValueError:
            continue
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        dated.append((d, float(pnl)))
    if not dated:
        return []
    dated.sort(key=lambda x: x[0])
    anchor = dated[0][0]
    width = timedelta(days=window_days)
    windows: dict[int, dict] = {}
    for d, pnl in dated:
        idx = int((d - anchor) // width)
        w = windows.setdefault(idx, {"idx": idx, "n_trades": 0, "pnl": 0.0,
                                     "gross_win": 0.0, "gross_loss": 0.0})
        w["n_trades"] += 1
        w["pnl"] += pnl
        if pnl > 0:
            w["gross_win"] += pnl
        else:
            w["gross_loss"] += abs(pnl)
    out = []
    for idx in sorted(windows):
        w = windows[idx]
        w["pf"] = _window_pf(w["gross_win"], w["gross_loss"])
        w["profitable"] = w["pnl"] > 0
        w["start"] = (anchor + idx * width).date().isoformat()
        w["end"] = (anchor + (idx + 1) * width).date().isoformat()
        out.append(w)
    return out


def forward_stats(windows: list[dict]) -> dict[str, Any]:
    """Compute the forward OOS statistics the graduation rule consumes."""
    n = len(windows)
    if n == 0:
        return {
            "n_oos_windows": 0,
            "p_edge": 0.0,
            "pf_ci_lower": 0.0,
            "binom_p": 1.0,
            "total_trades": 0,
            "total_pnl": 0.0,
        }
    profitable = sum(1 for w in windows if w["profitable"])
    p_edge = profitable / n
    pfs = [w["pf"] for w in windows]
    pf_ci_lower = bootstrap_pf_ci_lower(pfs)
    return {
        "n_oos_windows": n,
        "p_edge": round(p_edge, 4),
        "pf_ci_lower": round(float(pf_ci_lower), 4),
        "binom_p": round(binomial_oos_pvalue(p_edge, n), 6),
        "total_trades": sum(w["n_trades"] for w in windows),
        "total_pnl": round(sum(w["pnl"] for w in windows), 4),
    }


# ── trade-sign permutation diagnostic (Aronson) — REPORT ONLY ───────────────────
#
# NON-BLOCKING. This computes the trade-sign permutation p-value over a unit's realized
# P&L (the right null for a forward record: the live entry path is LLM-driven, not a
# mechanical optimizer). It is attached to the REPORT for observation only and is NOT
# consumed by ``meets_graduation`` — graduation inputs (``forward_stats`` + family FDR)
# are deliberately untouched. Promoting this to a blocking gate is a separate
# [safety-review] change, to be made only after the p-values are observed on the live
# MES/MGC series (16 / 67 trades -> low power today).

def trade_shuffle_diag(trades: list[dict], n_iters: int = 500, metric: str = "mean") -> dict[str, Any]:
    """Trade-sign permutation p-value over a unit's realized P&L. Report-only diagnostic.

    Returns ``{p_value, n_trades, passes, metric}``. Fail-closed (p=1.0) under ~2 trades.
    Lazy-imports the analytics module so forward_test stays cheap to import.
    """
    from analytics.permutation_test import permute_and_score  # noqa: PLC0415

    pnls = [float(t["pnl"]) for t in trades if t.get("pnl") is not None]
    res = permute_and_score(pnls, n_iters=n_iters, metric=metric)
    return {
        "p_value": res["p_value"],
        "n_trades": res["n_trades"],
        "passes": res["passes"],
        "metric": metric,
    }


def dsr_diag(trades: list[dict], n_trials: int) -> dict[str, Any]:
    """Deflated Sharpe over a unit's realized P&L, corrected for ``n_trials``. Report-only.

    DSR (Bailey & Lopez de Prado) discounts the Sharpe for the multiple-testing inflation
    that comes from having evaluated ``n_trials`` units -- here the family size (number of
    lineages / candidates) tested this run. Uses per-trade P&L as the return proxy: the
    Sharpe and skew/kurt the DSR depends on are scale-invariant, so dollar P&L gives the
    same statistic as fractional returns (same convention as gate-v2 ``trade_level_dsr``).

    NON-BLOCKING. Returned as a separate field; NOT consumed by ``meets_graduation``.
    Lazy-imports the analytics module so forward_test stays cheap to import.
    """
    from backtest.deflated_sharpe import deflated_sharpe_from_returns  # noqa: PLC0415

    pnls = [float(t["pnl"]) for t in trades if t.get("pnl") is not None]
    res = deflated_sharpe_from_returns(pnls, n_trials=max(int(n_trials), 1))
    return {
        "dsr": round(float(res["dsr"]), 4),
        "passes_at_10pct": bool(res["passes_at_10pct"]),
        "raw_sharpe": round(float(res["raw_sharpe"]), 4),
        "n_obs": int(res["n_obs"]),
        "n_trials": int(res["n_trials"]),
    }


# ── the loop ───────────────────────────────────────────────────────────────────

def tag_strategy_params(strategy_params: Any, candidate_id: str) -> dict:
    """Stamp a candidate_id into a trade's strategy_params so it is attributable.

    The scanner / executor should call this when a registry candidate fires, so
    that future paper trades can be mapped to the candidate (the only attribution
    level that can graduate one). Pure -- returns a new dict, never mutates.
    """
    sp = dict(_parse_params(strategy_params))
    sp["candidate_id"] = candidate_id
    return sp


def run_lineage_track(
    closed: list[dict],
    decision_registry: Optional[dict] = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> list[dict[str, Any]]:
    """Forward-test the LLM decision lineages stamped on live paper trades (P4).

    Mirrors the candidate loop: per-lineage windows + stats, a family-wide BH-FDR
    across every lineage with >=1 window, then graduation against the decision
    registry rule -- but only ``pre_registered`` lineages are eligible to graduate
    (default-material ``unregistered:*`` singletons can clear the stats yet never
    graduate, by design). One bar, both tracks.
    """
    from backtest import decision_registry as dr

    reg = decision_registry or dr.load_registry()
    buckets = lineage_buckets(closed)

    rows: list[dict] = []
    for lineage in sorted(buckets):
        windows = build_windows(buckets[lineage], window_days)
        rows.append({"lineage": lineage, "stats": forward_stats(windows)})

    # Family-wide BH-FDR across all lineages with >=1 forward window.
    fdr_inputs = [(i, r["stats"]["binom_p"]) for i, r in enumerate(rows)
                  if r["stats"]["n_oos_windows"] > 0]
    survives = dict.fromkeys(range(len(rows)), False)
    if fdr_inputs:
        flags = bh_fdr([p for _, p in fdr_inputs])
        for (i, _), ok in zip(fdr_inputs, flags, strict=True):
            survives[i] = bool(ok)

    out: list[dict] = []
    for i, r in enumerate(rows):
        lineage, stats = r["lineage"], r["stats"]
        pre_reg = dr.is_pre_registered(lineage)
        grad_stats = {**stats, "survives_family_fdr": survives[i]}
        graduated = pre_reg and dr.meets_graduation(grad_stats, reg)
        if not pre_reg:
            reason = (
                "default-material (unregistered) lineage -- pre-register it before "
                "its forward window is counted to enable graduation"
            )
        elif graduated:
            reason = "graduated: forward OOS record clears the decision-registry rule"
        else:
            reason = "not yet graduated: forward record does not clear the rule"
        out.append({
            "lineage": lineage,
            "pre_registered": pre_reg,
            "forward": stats,
            "trade_shuffle": trade_shuffle_diag(buckets[lineage]),  # report-only; not in graduation
            "dsr": dsr_diag(buckets[lineage], n_trials=len(rows)),  # report-only; not in graduation
            "survives_family_fdr": survives[i],
            "graduated": graduated,
            "reason": reason,
        })
    return out


def run_forward_test(
    registry: Optional[dict] = None,
    db: Any = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
    persist: bool = False,
) -> dict[str, Any]:
    """Run the forward-test loop over the active candidate set.

    ``db`` must expose ``get_closed_trades(limit=...)`` returning row dicts with
    symbol / pnl / exit_time / strategy_params. If None, the default SQLite
    manager is used.
    """
    reg = registry or load_registry()
    active = get_active_candidates(reg)

    if db is None:  # pragma: no cover - exercised live, not in unit tests
        from database.db_manager import get_db_manager
        db = get_db_manager()
    closed = db.get_closed_trades(limit=100_000)

    # First pass: per-candidate attributable windows + raw stats.
    rows: list[dict] = []
    for cand in active:
        level, trs = attributable_trades(closed, cand)
        windows = build_windows(trs, window_days)
        stats = forward_stats(windows)
        rows.append({"cand": cand, "level": level, "stats": stats, "trades": trs})

    # Family-wide BH-FDR across candidates that have >=1 forward window.
    fdr_inputs = [(i, r["stats"]["binom_p"]) for i, r in enumerate(rows)
                  if r["stats"]["n_oos_windows"] > 0]
    survives = dict.fromkeys(range(len(rows)), False)
    if fdr_inputs:
        flags = bh_fdr([p for _, p in fdr_inputs])
        for (i, _), ok in zip(fdr_inputs, flags, strict=True):
            survives[i] = bool(ok)

    candidates_out = []
    for i, r in enumerate(rows):
        cand, level, stats = r["cand"], r["level"], r["stats"]
        precise = level in _PRECISE_LEVELS
        grad_stats = {**stats, "survives_family_fdr": survives[i]}
        graduated = precise and meets_graduation(grad_stats, reg)
        if not precise:
            reason = (
                f"attribution is '{level or 'none'}' -- tag trades with candidate_id "
                "to enable graduation (symbol level cannot disambiguate same-symbol candidates)"
            )
        elif graduated:
            reason = "graduated: forward OOS record clears the registry rule"
        else:
            reason = "not yet graduated: forward record does not clear the rule"
        candidates_out.append({
            "id": cand["id"],
            "symbol": cand["symbol"],
            "attribution_level": level,
            "precise_attribution": precise,
            "forward": stats,
            "trade_shuffle": trade_shuffle_diag(r["trades"]),  # report-only; not in graduation
            "dsr": dsr_diag(r["trades"], n_trials=len(rows)),  # report-only; not in graduation
            "survives_family_fdr": survives[i],
            "graduated": graduated,
            "reason": reason,
        })

    # Symbol-level context (liveness even when untagged): forward stats over ALL
    # closed trades per symbol that appears in the active set.
    symbols = sorted({c["symbol"] for c in active})
    symbol_context = {}
    for sym in symbols:
        sym_trs = [t for t in closed if str(t.get("symbol", "")).upper() == sym.upper()]
        symbol_context[sym] = forward_stats(build_windows(sym_trs, window_days))

    # Decision-lineage track (P4): graduates the LLM path that actually trades live.
    try:
        lineages_out = run_lineage_track(closed, window_days=window_days)
    except Exception:  # pragma: no cover - never let the lineage track break the report
        lineages_out = []

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": window_days,
        "graduation_rule": reg.get("graduation_rule"),
        "n_active_candidates": len(active),
        "n_graduated": sum(1 for c in candidates_out if c["graduated"]),
        "candidates": candidates_out,
        "lineages": lineages_out,
        "n_lineages": len(lineages_out),
        "n_lineages_graduated": sum(1 for lin in lineages_out if lin["graduated"]),
        "symbol_context": symbol_context,
        "note": (
            "Two tracks. CANDIDATES are mechanical gate-v2 strategies; the live entry "
            "path is LLM-driven so they never fire live and attribute at symbol level "
            "(context only, never graduates). LINEAGES are the LLM decision identities "
            "stamped on live paper entries (P2) -- the unit that actually trades; they "
            "graduate against the decision_registry. Default-material (unregistered:*) "
            "lineages can clear the stats but never graduate -- pre-register a lineage "
            "before its forward window counts. ts_p (trade_shuffle p-value) and dsr "
            "(deflated Sharpe, n_trials=family size) are REPORT-ONLY diagnostics; "
            "neither affects graduation."
        ),
    }
    if persist:  # pragma: no cover - file IO exercised live
        os.makedirs(os.path.dirname(_REPORT_JSON), exist_ok=True)
        with open(_REPORT_JSON, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
        with open(_REPORT_MD, "w", encoding="utf-8") as fh:
            fh.write(_markdown(report))
    return report


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Forward-test report",
        "",
        f"- generated: {report['generated_at']}  |  window: {report['window_days']}d",
        f"- active candidates: {report['n_active_candidates']}  |  "
        f"graduated: **{report['n_graduated']}**",
        "",
        "| candidate | sym | attribution | n_oos | p_edge | pf_ci_lo | ts_p | dsr | fdr | graduated |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in report["candidates"]:
        f = c["forward"]
        ts = c.get("trade_shuffle", {})
        dsr = c.get("dsr", {})
        lines.append(
            f"| {c['id']} | {c['symbol']} | {c['attribution_level'] or '-'} | "
            f"{f['n_oos_windows']} | {f['p_edge']} | {f['pf_ci_lower']} | "
            f"{ts.get('p_value', '-')} | {dsr.get('dsr', '-')} | "
            f"{'Y' if c['survives_family_fdr'] else '.'} | "
            f"{'YES' if c['graduated'] else 'no'} |"
        )
    lineages = report.get("lineages") or []
    lines += ["", "## Decision lineages (LLM path -- the unit that trades live)", "",
              f"- lineages: {report.get('n_lineages', 0)}  |  "
              f"graduated: **{report.get('n_lineages_graduated', 0)}**", "",
              "| lineage | pre-reg | n_oos | p_edge | pf_ci_lo | ts_p | dsr | fdr | graduated |",
              "|---|---|---|---|---|---|---|---|---|"]
    for lin in lineages:
        f = lin["forward"]
        ts = lin.get("trade_shuffle", {})
        dsr = lin.get("dsr", {})
        lines.append(
            f"| {lin['lineage']} | {'Y' if lin['pre_registered'] else '.'} | "
            f"{f['n_oos_windows']} | {f['p_edge']} | {f['pf_ci_lower']} | "
            f"{ts.get('p_value', '-')} | {dsr.get('dsr', '-')} | "
            f"{'Y' if lin['survives_family_fdr'] else '.'} | "
            f"{'YES' if lin['graduated'] else 'no'} |"
        )
    if not lineages:
        lines.append("| _(no live trades carry a decision_identity yet)_ |  |  |  |  |  |  |  |  |")
    lines += ["", "## Symbol context (all closed trades per symbol)", "",
              "| symbol | n_oos | p_edge | pf_ci_lo | trades | pnl |",
              "|---|---|---|---|---|---|"]
    for sym, s in report["symbol_context"].items():
        lines.append(
            f"| {sym} | {s['n_oos_windows']} | {s['p_edge']} | {s['pf_ci_lower']} | "
            f"{s['total_trades']} | {s['total_pnl']} |"
        )
    lines += ["", "> " + report["note"]]
    return "\n".join(lines)


def main() -> None:  # pragma: no cover - thin CLI wrapper
    report = run_forward_test(persist=True)
    print(_markdown(report))


if __name__ == "__main__":  # pragma: no cover
    main()
