"""Strategy validator — Tier A statistical battery over research-script results.

Loads a per-combo result (by rank) from a research-script JSON (e.g.,
`mes_trend_search_results.json`), extracts the per-trade PnL list, and runs
the full Tier A validation battery:

  * bootstrap_pf (IID resampling with replacement)
  * moving_block_bootstrap (serial-correlation-aware, block = ceil(sqrt(N)))
  * bootstrap_sharpe
  * permute_max_dd (permutation-based, path-dependent)
  * deflated_sharpe_from_returns (multiple-testing correction across N grid
    combinations)

Output: a JSON report with a revised gate-v2 verdict and reason list.

Revised gate v2 — dual-pathway rule (memo 2026-04-21 03:48 CT + addendum 04:30 CT):

    CORE_GATE (rich samples):
        moving_block_pf_ci_95_lower >= 1.10
        AND p_positive_edge         >= 0.95
        AND mc_95th_max_dd_pct      <= 6.0
        AND dsr                     >= 0.10

    ALT_EVIDENCE_GATE (sparse samples, multi-lens confirmed):
        dsr                          >= 0.30
        AND rolling_wfo_verdict       in {STRONG, MODERATE}
        AND fixed_params_min_pf       >= 1.20
        AND cost_survives_through     >= realistic (2x commission, 2x slippage)
        AND mc_95th_max_dd_pct        <= 7.0

    A strategy PASSES if core OR alt holds. DSR is the load-bearing criterion
    for both paths — sample-size mechanics can relax, signal-quality cannot.

Usage (from engine/):
    .venv/Scripts/python -m scripts.validate_strategy \\
        --results-file scripts/mes_trend_search_results.json \\
        --rank 1 \\
        --rolling-wfo validation_reports/MES_trend_rank1_rolling_wfo.json \\
        --fixed-params validation_reports/MES_trend_fixed_params_temporal.json \\
        --cost-sweep validation_reports/MES_trend_rank1_cost_sweep.json \\
        --output validation_reports/mes_rank1.json

If any aux-input flag is omitted the alt-evidence path is scored as UNSCORED
and the overall verdict is driven by the core gate alone.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
_ENGINE = _HERE.parent
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from backtest._gate_v2_helpers import GATE_MC_DD_ALT, GATE_MC_DD_CORE  # noqa: E402
from backtest.deflated_sharpe import deflated_sharpe_from_returns  # noqa: E402
from backtest.monte_carlo import (  # noqa: E402
    bootstrap_pf,
    bootstrap_sharpe,
    moving_block_bootstrap,
    permute_max_dd,
)
from backtest.stationarity_gate import h1_h2_split  # noqa: E402

# Revised gate v2 thresholds — see memo project_gate_v2_proposal.md (2026-04-21)
CORE_GATE = {
    # Moving-block bootstrap lower bound. Addendum 2026-04-21 04:30 CT swapped
    # IID → MBB because trend strategies exhibit serial correlation that IID
    # overstates CI width against.
    "pf_ci_lower_min": 1.10,
    "p_positive_edge_min": 0.95,
    # Imported from _gate_v2_helpers (single source of truth) rather than a
    # local hardcoded 6.0 -- that local copy drifted out of sync when the live
    # gate's ceiling was tightened 6%->5% and was never updated here (found
    # 2026-07-10). GATE_MC_DD_CORE is a fraction (0.05); this dict's convention
    # is a percentage.
    "max_dd_95th_pct_max": GATE_MC_DD_CORE * 100,
    # Bailey-convention floor for core path. Selection-bias-indistinguishable below.
    "dsr_min": 0.10,
}

ALT_EVIDENCE_GATE = {
    # Tighter than core — relaxing sample-size demands tighter signal-quality.
    "dsr_min": 0.30,
    "fixed_params_min_pf_min": 1.20,
    # Imported from _gate_v2_helpers -- was a local hardcoded 7.0 that drifted
    # out of sync when the live ALT ceiling was tightened 7%->4% (found
    # 2026-07-10). GATE_MC_DD_ALT is a fraction (0.04); this dict's convention
    # is a percentage.
    "max_dd_95th_pct_max": GATE_MC_DD_ALT * 100,
    # rolling_wfo_verdict must be in ROLLING_WFO_QUALIFYING below.
    # cost_survives_through must rank >= "realistic" in COST_SURVIVAL_LEVELS.
}

# ── Strategy-class drawdown ceilings ────────────────────────────────────────
# The MC-95th DD ceiling is the ONE gate criterion that is class-dependent: an
# intraday futures book is judged against the tight core/alt bar (tied to the
# $5K/instrument 60% kill-switch), but a long-biased equity-swing strategy holds
# through equity bear markets and is correctly judged against a much wider
# equity-class bar. All OTHER criteria (PF-CI, p_edge, DSR) are class-INDEPENDENT
# — signal quality does not get a class discount.
#
# ``intraday_futures`` values are byte-identical to CORE_GATE / ALT_EVIDENCE_GATE
# so the default path is unchanged. An UNKNOWN class falls back to the STRICTEST
# (intraday_futures) ceiling — a class map must never accidentally LOOSEN a gate.
#
# CORRECTION (2026-07-10): this dict was still hardcoded to the OLDER 6.0/7.0
# ceiling from a "Phase A MC" relaxation, even after the live routing ceiling in
# `_gate_v2_helpers.py` was tightened back down to GATE_MC_DD_CORE=0.05/
# GATE_MC_DD_ALT=0.04 on 2026-05-09 -- silently reopening the "byte-identical"
# invariant this comment claims. Now imported directly so the two can't drift
# again. This DID matter for live routing despite the SCOPE note below: the
# weekly `gate_v2_orchestrator.py` cron calls this validator for one of MES's
# candidates (trend rank 7) and persists the verdict into the same
# `gate_v2_verdicts/` directory that `gate_v2_policy.is_ungate_eligible()` reads
# to help decide whether MES-the-symbol stays authorized to paper trade.
#
# SCOPE (2026-07-02): this governs only how a verdict SCORES in this validator.
# Capital routing is gated separately by engine/backtest/_gate_v2_helpers.py
# (GATE_MC_DD_CORE/ALT) and engine/gate_v2_policy.py — a class ceiling that ever
# affects what can route MUST be applied there too. This PR deliberately does NOT
# touch either; equity-class verdicts score on the wider bar for VISIBILITY only
# and cannot authorize trading.
STRATEGY_CLASS_DD: dict[str, dict[str, float]] = {
    "intraday_futures": {"core": GATE_MC_DD_CORE * 100, "alt": GATE_MC_DD_ALT * 100},
    "equity_swing": {"core": 25.0, "alt": 30.0},
}
DEFAULT_STRATEGY_CLASS = "intraday_futures"


def _dd_ceiling(strategy_class: str, path: str) -> float:
    """Return the MC-95th DD ceiling for a class/path, strict-fallback on unknown."""
    cls = STRATEGY_CLASS_DD.get(strategy_class)
    if cls is None:
        cls = STRATEGY_CLASS_DD[DEFAULT_STRATEGY_CLASS]
    return cls[path]


def _is_nondefault_class(strategy_class: str) -> bool:
    """True only for a KNOWN class whose ceiling differs from the default. Used to
    annotate reason strings — default/unknown/futures spellings stay byte-identical
    to the historical (unannotated) output."""
    return strategy_class in STRATEGY_CLASS_DD and strategy_class != DEFAULT_STRATEGY_CLASS

# Ordinal ladder from cost_sensitivity_sweep.py. Alt-path requires that edge
# survives through at least "realistic" (2x commission, 2x slippage).
COST_SURVIVAL_LEVELS = (
    "optimistic",
    "baseline",
    "realistic",
    "stressed",
    "catastrophic",
)

# Rolling-WFO verdicts that qualify for the alt-evidence path. "WEAK" and
# "FAIL" signal a bimodal / inconsistent temporal pattern (e.g. MNQ trend's
# 50% profitable windows).
ROLLING_WFO_QUALIFYING = frozenset({"STRONG", "MODERATE"})

# Keys that must ALL be present in aux_evidence for the alt path to score.
_ALT_AUX_REQUIRED = ("rolling_wfo_verdict", "fixed_params_min_pf", "cost_survives_through")

# --- H1/H2 chronological stationarity gate (the campaign's #1 lesson) ---------
# A pooled bootstrap PF-CI is blind to WHEN an edge occurred and passes
# back-loaded non-stationary edges (ES-NQ: H1 PF 0.91 / H2 7.96). When enforced,
# a strategy is FAILED on POSITIVE evidence of non-stationarity only: the H1/H2
# split has enough trades to judge (sample_adequate) AND a half is unprofitable
# (not both_profitable). It is deliberately NOT failed on a merely-sparse sample
# (absence of evidence) — the DSR / p_edge / MC criteria already carry small-N.
# Default ON; set GATE_H1H2_ENFORCE=0 to revert to record-only.
_H1H2_ENFORCE_DEFAULT = os.getenv("GATE_H1H2_ENFORCE", "1") == "1"

# --- Beta-harvest p_edge relaxation (PR #141 policy, ported into this gate) ----
# A low-frequency long-beta-harvest edge (e.g. turn-of-month, pre-holiday) cannot
# win 95% of years, so p_edge>=0.95 structurally penalizes it. When the strategy
# is tagged `beta_harvest` AND enforcement is on, a CORE failure whose SOLE failing
# criterion is p_edge is rescued to PASS iff p_edge >= 0.60 AND the H1/H2 split is
# consistent. Every other criterion (pf_ci, dsr, mc_dd) still binds — the relaxation
# can only ever de-authorize less, never bypass selection-bias or risk. Default OFF
# (matches BETA_HARVEST_GATE_ENFORCE=0 in .env.example); opt in per run.
_BETA_HARVEST_ENFORCE_DEFAULT = os.getenv("BETA_HARVEST_GATE_ENFORCE", "0") == "1"
_BETA_HARVEST_P_EDGE_MIN = 0.60
_BETA_HARVEST_CLASS = "beta_harvest"
# Index of the p_edge criterion in _score_core_gate's pass list (pf_ci, p_edge,
# mc_dd, dsr) — asserted in tests so a reordering can't silently mis-target it.
_CORE_P_EDGE_IDX = 1


def _load_result(results_file: Path, rank: int) -> dict:
    """Load rank-th result from a research-script JSON.

    Research scripts sort results[] by PF descending, so rank=1 is best.
    """
    with open(results_file, "r") as f:
        doc = json.load(f)
    results = doc.get("results", [])
    if not results:
        raise ValueError(f"No results in {results_file}")
    if rank < 1 or rank > len(results):
        raise ValueError(f"rank={rank} out of range (1..{len(results)})")
    entry = results[rank - 1]
    return {
        "symbol": doc.get("symbol", "UNKNOWN"),
        "n_grid_trials": doc.get("n_combos", len(results)),
        "start": doc.get("start"),
        "end": doc.get("end"),
        "interval": doc.get("interval"),
        "combo": entry,
    }


def _load_result_from_wfo(results_file: Path, symbol: str, rank: int, window: str = "test") -> dict:
    """Load rank-th result from multi_symbol_trend_wfo output (nested shape)."""
    with open(results_file, "r") as f:
        doc = json.load(f)
    summary = doc.get("summary", {})
    key = f"{symbol.upper()}_wfo"
    if key not in summary:
        raise KeyError(f"{key} not in WFO summary. Available: {list(summary.keys())}")
    top = summary[key].get("top_5", [])
    if rank < 1 or rank > len(top):
        raise ValueError(f"rank={rank} out of top_5 range")
    return {
        "symbol": symbol.upper(),
        "n_grid_trials": len(summary[key].get("top_5", [])),
        "start": doc.get("train" if window == "train" else "test", [None, None])[0],
        "end": doc.get("train" if window == "train" else "test", [None, None])[1],
        "interval": "1h",
        "combo": top[rank - 1],
        "window": window,
    }


def _extract_pnls(combo: dict, window: str | None = None) -> list[float]:
    """Pull per-trade PnLs out of a research result entry.

    Shapes supported:
        {"trades": [{"pnl": ...}, ...]}                  — flat research scripts
        {"train": {..., "trades": [...]}, "test": {...}} — WFO shape
    """
    if window and window in combo:
        window_obj = combo[window]
        trades = window_obj.get("trades", [])
    else:
        trades = combo.get("trades", [])

    if not trades:
        raise ValueError(
            "No 'trades' field in result. Re-run research script to "
            "regenerate JSON — per-trade emission was added in A2."
        )
    return [float(t["pnl"]) for t in trades]


def _score_core_gate(
    report: dict, strategy_class: str = DEFAULT_STRATEGY_CLASS
) -> tuple[list[bool], list[str]]:
    """Evaluate the 4 core-gate criteria. MBB (not IID) is the CI stat per
    the 2026-04-21 04:30 CT addendum — trend strategies have serial
    correlation that IID overstates against.

    Only the MC-95th DD ceiling is class-dependent (``strategy_class``); all
    other criteria are class-independent. Default class reproduces the current
    intraday-futures ceiling (``GATE_MC_DD_CORE``) exactly."""
    passes: list[bool] = []
    reasons: list[str] = []
    dd_max = _dd_ceiling(strategy_class, "core")

    block_lo = report["bootstrap_block"]["pf_ci_95_low"]
    if block_lo >= CORE_GATE["pf_ci_lower_min"]:
        passes.append(True)
        reasons.append(f"mbb_pf_ci_lower={block_lo} >= {CORE_GATE['pf_ci_lower_min']}")
    else:
        passes.append(False)
        reasons.append(f"FAIL mbb_pf_ci_lower={block_lo} < {CORE_GATE['pf_ci_lower_min']}")

    p_edge = report["bootstrap_iid"]["p_positive_edge"]
    if p_edge >= CORE_GATE["p_positive_edge_min"]:
        passes.append(True)
        reasons.append(f"p_positive_edge={p_edge} >= {CORE_GATE['p_positive_edge_min']}")
    else:
        passes.append(False)
        reasons.append(f"FAIL p_positive_edge={p_edge} < {CORE_GATE['p_positive_edge_min']}")

    mc_95 = report["drawdown_mc"]["mc_95th"]
    _cls_suffix = f" ({strategy_class} class)" if _is_nondefault_class(strategy_class) else ""
    if mc_95 <= dd_max:
        passes.append(True)
        reasons.append(f"mc_95th_dd_pct={mc_95} <= {dd_max}{_cls_suffix}")
    else:
        passes.append(False)
        reasons.append(f"FAIL mc_95th_dd_pct={mc_95} > {dd_max}{_cls_suffix}")

    dsr = report["deflated_sharpe"]["dsr"]
    if dsr >= CORE_GATE["dsr_min"]:
        passes.append(True)
        reasons.append(f"dsr={dsr} >= {CORE_GATE['dsr_min']} (not selection-bias)")
    else:
        passes.append(False)
        reasons.append(f"FAIL dsr={dsr} < {CORE_GATE['dsr_min']} (selection bias)")

    return passes, reasons


def _score_alt_gate(
    report: dict, aux: dict, strategy_class: str = DEFAULT_STRATEGY_CLASS
) -> tuple[list[bool], list[str]]:
    """Evaluate the 5 alt-evidence criteria. Assumes the aux dict has already
    been validated for completeness. Only the MC-95th DD ceiling is
    class-dependent; default class reproduces the current intraday-futures
    ceiling (``GATE_MC_DD_ALT``) exactly."""
    passes: list[bool] = []
    reasons: list[str] = []
    dd_max = _dd_ceiling(strategy_class, "alt")

    # (1) DSR — tighter than core's 0.10.
    dsr = report["deflated_sharpe"]["dsr"]
    if dsr >= ALT_EVIDENCE_GATE["dsr_min"]:
        passes.append(True)
        reasons.append(f"dsr={dsr} >= {ALT_EVIDENCE_GATE['dsr_min']} (alt floor)")
    else:
        passes.append(False)
        reasons.append(f"FAIL dsr={dsr} < {ALT_EVIDENCE_GATE['dsr_min']} (alt floor)")

    # (2) Rolling WFO verdict must be STRONG or MODERATE.
    wfo = aux["rolling_wfo_verdict"]
    if wfo in ROLLING_WFO_QUALIFYING:
        passes.append(True)
        reasons.append(f"rolling_wfo={wfo} in {sorted(ROLLING_WFO_QUALIFYING)}")
    else:
        passes.append(False)
        reasons.append(f"FAIL rolling_wfo={wfo} not in {sorted(ROLLING_WFO_QUALIFYING)}")

    # (3) Fixed-params segments must maintain PF >= 1.20 on the weakest segment.
    min_pf = aux["fixed_params_min_pf"]
    if min_pf >= ALT_EVIDENCE_GATE["fixed_params_min_pf_min"]:
        passes.append(True)
        reasons.append(
            f"fixed_params_min_pf={min_pf} >= {ALT_EVIDENCE_GATE['fixed_params_min_pf_min']}"
        )
    else:
        passes.append(False)
        reasons.append(
            f"FAIL fixed_params_min_pf={min_pf} < {ALT_EVIDENCE_GATE['fixed_params_min_pf_min']}"
        )

    # (4) Cost sensitivity — edge must survive through at least "realistic".
    survives = aux["cost_survives_through"]
    floor_idx = COST_SURVIVAL_LEVELS.index("realistic")
    try:
        survives_idx = COST_SURVIVAL_LEVELS.index(survives)
    except ValueError:
        survives_idx = -1
    if survives_idx >= floor_idx:
        passes.append(True)
        reasons.append(f"cost_survives_through={survives} >= realistic")
    else:
        passes.append(False)
        reasons.append(f"FAIL cost_survives_through={survives} < realistic")

    # (5) MC 95th DD — for intraday_futures this is TIGHTER than core
    # (GATE_MC_DD_ALT=4% vs GATE_MC_DD_CORE=5%), since alt relaxes
    # sample-size requirements and compensates with a stricter DD bar, not a
    # looser one (corrected 2026-07-10 -- this comment previously said
    # "looser than core"). The ceiling is class-dependent (equity_swing rides
    # a wider bar in both directions).
    mc_95 = report["drawdown_mc"]["mc_95th"]
    _cls_suffix = f", {strategy_class} class" if _is_nondefault_class(strategy_class) else ""
    if mc_95 <= dd_max:
        passes.append(True)
        reasons.append(
            f"mc_95th_dd_pct={mc_95} <= {dd_max} (alt ceiling{_cls_suffix})"
        )
    else:
        passes.append(False)
        reasons.append(
            f"FAIL mc_95th_dd_pct={mc_95} > {dd_max} (alt ceiling{_cls_suffix})"
        )

    return passes, reasons


def _evaluate_gate_v2(
    report: dict,
    aux_evidence: dict | None = None,
    *,
    stationarity: dict | None = None,
    strategy_class: str = "",
    enforce_h1h2: bool | None = None,
    beta_harvest_enforce: bool | None = None,
) -> dict:
    """Apply revised gate v2 — dual-pathway rule.

    A strategy PASSES if CORE_GATE (4/4) OR ALT_EVIDENCE_GATE (5/5) holds.
    DSR is load-bearing in both paths so selection-bias can never be bypassed.

    Two policy layers, both behavior-neutral unless their inputs are supplied:

    * **Beta-harvest p_edge relaxation** — when ``strategy_class == "beta_harvest"``
      and enforcement is on, a CORE failure whose SOLE failing criterion is p_edge
      is rescued iff ``p_edge >= 0.60`` and the H1/H2 split is consistent.

    ``strategy_class`` ALSO selects the MC-95th DD ceiling via ``STRATEGY_CLASS_DD``:
    ``""``/``"intraday_futures"``/``"beta_harvest"`` → ``GATE_MC_DD_CORE``/``GATE_MC_DD_ALT``
    (synced from ``_gate_v2_helpers.py``); ``"equity_swing"``
    → 25%/30% (long-biased equity rides equity bear DDs). Unknown classes fall back to
    the STRICTEST ceiling. This affects only how a verdict SCORES here — capital routing
    is gated separately (``_gate_v2_helpers.py`` / ``gate_v2_policy.py``), untouched by
    this class map, so an equity-class PASS scores for visibility but cannot route.
    * **H1/H2 stationarity enforcement** — when on and ``stationarity`` shows
      positive non-stationarity evidence (adequate sample, a losing half), the
      verdict is overridden to FAIL regardless of core/alt.

    ``stationarity`` is the ``stationarity_gate.h1_h2_split`` dict (or None to skip
    both layers — preserving the original behavior for legacy callers/tests).

    Parameters
    ----------
    report : dict
        Output of `validate()` — must contain bootstrap_iid, bootstrap_block,
        drawdown_mc, and deflated_sharpe sub-dicts.
    aux_evidence : dict | None
        Optional dict with keys `rolling_wfo_verdict` (str), `fixed_params_min_pf`
        (float), `cost_survives_through` (str). All three must be present or
        the alt path scores as UNSCORED.

    Returns
    -------
    dict with keys: verdict, passed_via, core_verdict, alt_verdict,
    n_core_passed, n_core_criteria, n_alt_passed, n_alt_criteria,
    core_reasons, alt_reasons, and backward-compat `reasons` / `n_passed` /
    `n_criteria`.
    """
    if enforce_h1h2 is None:
        enforce_h1h2 = _H1H2_ENFORCE_DEFAULT
    if beta_harvest_enforce is None:
        beta_harvest_enforce = _BETA_HARVEST_ENFORCE_DEFAULT

    core_passes, core_reasons = _score_core_gate(report, strategy_class=strategy_class)
    n_core_passed = sum(core_passes)

    # Beta-harvest p_edge relaxation: rescue a core FAIL whose ONLY failing
    # criterion is p_edge, when tagged beta_harvest + H1/H2 consistent.
    beta_harvest_applied = False
    h1h2_consistent = bool(stationarity and stationarity.get("consistent"))
    if (
        beta_harvest_enforce
        and strategy_class == _BETA_HARVEST_CLASS
        and h1h2_consistent
        and sum(1 for p in core_passes if not p) == 1
        and not core_passes[_CORE_P_EDGE_IDX]
    ):
        p_edge_val = report["bootstrap_iid"]["p_positive_edge"]
        if p_edge_val >= _BETA_HARVEST_P_EDGE_MIN:
            beta_harvest_applied = True
            core_reasons.append(
                f"BETA-HARVEST RESCUE: p_edge={p_edge_val} >= {_BETA_HARVEST_P_EDGE_MIN} "
                "(sole core failure) AND H1/H2 consistent — p_edge floor relaxed"
            )

    core_verdict = "PASS" if (n_core_passed == len(core_passes) or beta_harvest_applied) else "FAIL"

    aux_ready = bool(aux_evidence) and all(k in aux_evidence for k in _ALT_AUX_REQUIRED)
    if aux_ready:
        alt_passes, alt_reasons = _score_alt_gate(
            report, aux_evidence, strategy_class=strategy_class
        )
        n_alt_passed = sum(alt_passes)
        n_alt_criteria = len(alt_passes)
        alt_verdict = "PASS" if n_alt_passed == n_alt_criteria else "FAIL"
    else:
        alt_passes = []
        alt_reasons = []
        n_alt_passed = 0
        n_alt_criteria = 5
        alt_verdict = "UNSCORED"

    if core_verdict == "PASS":
        verdict = "PASS"
        passed_via = "core" if not beta_harvest_applied else "core(beta_harvest)"
    elif alt_verdict == "PASS":
        verdict = "PASS"
        passed_via = "alt"
    else:
        verdict = "FAIL"
        passed_via = None

    # H1/H2 stationarity enforcement — overrides a PASS on POSITIVE evidence of
    # non-stationarity (adequate sample AND a losing half). Absence of evidence
    # (sparse/UNSCORED) does NOT block; the other criteria carry small-N.
    stationarity_verdict = "UNSCORED"
    stationarity_block = False
    if stationarity is not None:
        adequate = bool(stationarity.get("sample_adequate"))
        both_profitable = bool(stationarity.get("both_profitable"))
        if not adequate:
            stationarity_verdict = "INSUFFICIENT_SAMPLE"
        else:
            stationarity_verdict = "CONSISTENT" if both_profitable else "NON_STATIONARY"
        if enforce_h1h2 and adequate and not both_profitable:
            stationarity_block = True
            core_reasons.append(
                "H1/H2 ENFORCE: FAIL — non-stationary "
                f"(h1_pf={stationarity.get('h1_pf')} h2_pf={stationarity.get('h2_pf')}; "
                "a half is unprofitable) overrides the gate verdict"
            )
            verdict = "FAIL"
            passed_via = None

    return {
        "verdict": verdict,
        "passed_via": passed_via,
        "beta_harvest_applied": beta_harvest_applied,
        "stationarity_verdict": stationarity_verdict,
        "stationarity_block": stationarity_block,
        "core_verdict": core_verdict,
        "alt_verdict": alt_verdict,
        "n_core_passed": n_core_passed,
        "n_core_criteria": len(core_passes),
        "n_alt_passed": n_alt_passed,
        "n_alt_criteria": n_alt_criteria,
        "core_reasons": core_reasons,
        "alt_reasons": alt_reasons,
        # Backward-compat surface for older callers that expected the old
        # single-path schema (engine/scripts/validation_reports/*_report.json
        # was written with these keys — keep them stable for bisect tooling).
        "reasons": core_reasons + alt_reasons,
        "n_passed": n_core_passed,
        "n_criteria": len(core_passes),
    }


def _load_aux_evidence(
    rolling_wfo_path: Path | None,
    fixed_params_path: Path | None,
    cost_sweep_path: Path | None,
) -> dict | None:
    """Extract the 3 alt-evidence signals from their respective validator JSONs.

    Returns None if any path is missing — the caller then runs core-only. The
    shape keys read are locked to what those scripts actually emit; see the
    four example reports in `engine/scripts/validation_reports/` for the
    contract.
    """
    if not (rolling_wfo_path and fixed_params_path and cost_sweep_path):
        return None

    aux: dict = {}
    with open(rolling_wfo_path) as f:
        wfo = json.load(f)
    aux["rolling_wfo_verdict"] = wfo.get("verdict")

    with open(fixed_params_path) as f:
        fp = json.load(f)
    stats = fp.get("stats") or {}
    aux["fixed_params_min_pf"] = stats.get("min_pf")

    with open(cost_sweep_path) as f:
        cs = json.load(f)
    aux["cost_survives_through"] = cs.get("edge_survives_through")

    missing = [k for k, v in aux.items() if v is None]
    if missing:
        print(
            f"[WARN] aux evidence incomplete — missing {missing} — alt path will be UNSCORED",
            flush=True,
        )
        return None
    return aux


def validate(
    pnls: list[float],
    n_grid_trials: int,
    initial_capital: float = 10_000.0,
    n_resamples: int = 10_000,
    seed: int = 42,
) -> dict:
    """Run the full validation battery on a PnL list.

    Returns the report dict without the gate-evaluation wrapper — useful for
    programmatic callers (tests, notebooks, bulk sweeps).
    """
    pnls_arr = np.asarray(pnls, dtype=float)
    raw_pf = (
        float(pnls_arr[pnls_arr > 0].sum() / max(abs(pnls_arr[pnls_arr < 0].sum()), 1e-12))
        if len(pnls_arr) > 0
        else 0.0
    )

    # Returns-as-fraction-of-capital for Sharpe computation (per-trade basis)
    returns = pnls_arr / initial_capital

    return {
        "raw": {
            "n_trades": int(len(pnls_arr)),
            "net_pnl": round(float(pnls_arr.sum()), 2),
            "pf": round(raw_pf, 4),
            "ret_pct": round(float(pnls_arr.sum() / initial_capital * 100), 2),
        },
        "bootstrap_iid": bootstrap_pf(pnls_arr, n_resamples=n_resamples, seed=seed),
        "bootstrap_block": moving_block_bootstrap(pnls_arr, n_resamples=n_resamples, seed=seed),
        "sharpe_ci": bootstrap_sharpe(
            pnls_arr, initial_capital=initial_capital, n_resamples=n_resamples, seed=seed
        ),
        "drawdown_mc": permute_max_dd(
            pnls_arr, initial_capital=initial_capital, n_resamples=n_resamples, seed=seed
        ),
        "deflated_sharpe": deflated_sharpe_from_returns(
            returns=returns.tolist(),
            n_trials=n_grid_trials,
            ann_factor=252.0,
        ),
    }


def main():
    ap = argparse.ArgumentParser(description="Tier A strategy validator")
    ap.add_argument("--results-file", required=True, help="Path to research-script results JSON")
    ap.add_argument(
        "--rank", type=int, default=1, help="1-indexed rank within results[] (1 = best PF)"
    )
    ap.add_argument(
        "--symbol", default=None, help="Required for WFO-shaped JSONs (multi_symbol_trend_wfo)"
    )
    ap.add_argument(
        "--window",
        default="test",
        choices=["train", "test"],
        help="For WFO-shaped JSONs: which window to validate",
    )
    ap.add_argument(
        "--output", default=None, help="Output report JSON path (default: derived from input)"
    )
    ap.add_argument("--initial-capital", type=float, default=10_000.0)
    ap.add_argument("--n-resamples", type=int, default=10_000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument(
        "--rolling-wfo",
        default=None,
        help="Path to rolling_wfo_validator report JSON (alt-path input)",
    )
    ap.add_argument(
        "--fixed-params",
        default=None,
        help="Path to fixed_params_temporal_validator report JSON " "(alt-path input)",
    )
    ap.add_argument(
        "--cost-sweep",
        default=None,
        help="Path to cost_sensitivity_sweep report JSON (alt-path input)",
    )
    ap.add_argument(
        "--strategy-class",
        default="",
        help="Strategy class tag. '' / 'intraday_futures' → GATE_MC_DD_CORE/ALT ceiling "
        "(synced from _gate_v2_helpers.py; 5%/4% as of 2026-07-10, default). "
        "'equity_swing' → 25%/30% ceiling (long-biased equity rides equity bear DDs; "
        "SCORING/visibility only — does NOT authorize routing). 'beta_harvest' (with "
        "BETA_HARVEST_GATE_ENFORCE=1) relaxes the p_edge floor for low-frequency long-beta "
        "edges (TOM, pre-holiday). All non-DD criteria stay class-independent.",
    )
    args = ap.parse_args()

    results_file = Path(args.results_file).resolve()
    if not results_file.exists():
        print(f"[ERROR] results file not found: {results_file}", flush=True)
        return 1

    t0 = time.time()

    # Detect shape: WFO has summary.{SYM}_wfo; flat scripts have top-level results[]
    with open(results_file) as f:
        doc_peek = json.load(f)
    is_wfo = "summary" in doc_peek and any(k.endswith("_wfo") for k in doc_peek["summary"])

    if is_wfo:
        if not args.symbol:
            print("[ERROR] --symbol is required for WFO-shaped JSONs", flush=True)
            return 1
        loaded = _load_result_from_wfo(results_file, args.symbol, args.rank, args.window)
        pnls = _extract_pnls(loaded["combo"], window=args.window)
        params_str = json.dumps(loaded["combo"].get("params", {}))
    else:
        loaded = _load_result(results_file, args.rank)
        pnls = _extract_pnls(loaded["combo"])
        params_str = json.dumps(loaded["combo"].get("params", {}))

    print(f"Validating: {loaded['symbol']} rank={args.rank} params={params_str}", flush=True)
    print(f"  n_trades={len(pnls)} n_grid_trials={loaded['n_grid_trials']}", flush=True)

    report = validate(
        pnls,
        n_grid_trials=loaded["n_grid_trials"],
        initial_capital=args.initial_capital,
        n_resamples=args.n_resamples,
        seed=args.seed,
    )

    aux = _load_aux_evidence(
        rolling_wfo_path=Path(args.rolling_wfo).resolve() if args.rolling_wfo else None,
        fixed_params_path=Path(args.fixed_params).resolve() if args.fixed_params else None,
        cost_sweep_path=Path(args.cost_sweep).resolve() if args.cost_sweep else None,
    )
    # H1/H2 chronological stationarity (the campaign's #1 lesson: a pooled
    # bootstrap PF-CI passes back-loaded non-stationary edges, ES-NQ H1 0.91 /
    # H2 7.96). `pnls` is the per-trade series in execution order. Recorded on the
    # report AND fed to the gate, which enforces it on positive non-stationarity
    # evidence (GATE_H1H2_ENFORCE, default ON). See backtest/stationarity_gate.py.
    stationarity = h1_h2_split(pnls)
    report["stationarity"] = stationarity
    gate = _evaluate_gate_v2(
        report,
        aux_evidence=aux,
        stationarity=stationarity,
        strategy_class=args.strategy_class,
    )
    report["gate_v2"] = gate
    if aux is not None:
        report["aux_evidence"] = aux
    report["strategy"] = {
        "symbol": loaded["symbol"],
        "interval": loaded.get("interval"),
        "params": loaded["combo"].get("params"),
        "start": loaded.get("start"),
        "end": loaded.get("end"),
        "rank_in_grid": args.rank,
    }
    report["elapsed_sec"] = round(time.time() - t0, 2)

    # Print summary
    print("\n=== TIER A VALIDATION REPORT ===", flush=True)
    print(
        f"Raw:        PF={report['raw']['pf']:.3f}  net_pnl=${report['raw']['net_pnl']}  n={report['raw']['n_trades']}",
        flush=True,
    )
    print(
        f"Bootstrap:  PF median={report['bootstrap_iid']['median_pf']:.3f}  "
        f"CI=[{report['bootstrap_iid']['pf_ci_95_low']:.3f}, "
        f"{report['bootstrap_iid']['pf_ci_95_high']:.3f}]  "
        f"p_edge={report['bootstrap_iid']['p_positive_edge']:.3f}",
        flush=True,
    )
    print(
        f"Block-bs:   PF median={report['bootstrap_block']['median_pf']:.3f}  "
        f"CI=[{report['bootstrap_block']['pf_ci_95_low']:.3f}, "
        f"{report['bootstrap_block']['pf_ci_95_high']:.3f}]  "
        f"block={report['bootstrap_block']['block_size']}",
        flush=True,
    )
    print(
        f"Sharpe:     median={report['sharpe_ci']['median_sharpe']:.3f}  "
        f"CI=[{report['sharpe_ci']['sharpe_ci_95_low']:.3f}, "
        f"{report['sharpe_ci']['sharpe_ci_95_high']:.3f}]",
        flush=True,
    )
    print(
        f"MaxDD MC:   obs={report['drawdown_mc']['observed_max_dd_pct']:.2f}%  "
        f"95th={report['drawdown_mc']['mc_95th']:.2f}%  99th={report['drawdown_mc']['mc_99th']:.2f}%",
        flush=True,
    )
    print(
        f"DSR:        raw_sr={report['deflated_sharpe']['raw_sharpe']:.3f}  "
        f"E[max|N]={report['deflated_sharpe']['expected_max_sharpe']:.3f}  "
        f"dsr={report['deflated_sharpe']['dsr']:.3f}  "
        f"passes_10pct={report['deflated_sharpe']['passes_at_10pct']}",
        flush=True,
    )
    passed_via = gate["passed_via"] or "—"
    print(
        f"\nGate v2 verdict: {gate['verdict']} (via {passed_via})",
        flush=True,
    )
    _st = report["stationarity"]
    _enforced = " [BLOCKING]" if gate.get("stationarity_block") else ""
    print(
        f"  H1/H2: {gate['stationarity_verdict']}{_enforced} "
        f"h1_pf={_st['h1_pf']} h2_pf={_st['h2_pf']} "
        f"(n {_st['h1_n']}/{_st['h2_n']})",
        flush=True,
    )
    if gate.get("beta_harvest_applied"):
        print(
            "  beta-harvest: p_edge floor relaxed (sole core failure, H1/H2 consistent)", flush=True
        )
    print(
        f"  core: {gate['core_verdict']} ({gate['n_core_passed']}/{gate['n_core_criteria']})",
        flush=True,
    )
    for reason in gate["core_reasons"]:
        print(f"    - {reason}", flush=True)
    print(
        f"  alt : {gate['alt_verdict']} ({gate['n_alt_passed']}/{gate['n_alt_criteria']})",
        flush=True,
    )
    if gate["alt_reasons"]:
        for reason in gate["alt_reasons"]:
            print(f"    - {reason}", flush=True)
    else:
        print(
            "    - (alt path UNSCORED: pass --rolling-wfo --fixed-params --cost-sweep "
            "to score it)",
            flush=True,
        )

    if args.output:
        out_path = Path(args.output).resolve()
    else:
        out_path = (
            results_file.parent
            / "validation_reports"
            / f"{loaded['symbol']}_rank{args.rank}_report.json"
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nSaved report to {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
