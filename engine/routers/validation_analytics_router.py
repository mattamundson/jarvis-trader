"""
JARVIS TRADER — Validation Analytics Router
===========================================
Live replacements for three dashboard tables that were previously hardcoded
static blocks on ``/validation`` (Monte Carlo, parameter sensitivity, and
statistical significance). All three are sourced from the gate-v2 verdict JSONs
under ``engine/data/gate_v2_verdicts/`` — the same source of truth the strategy
ledger uses — so the numbers are real, current, and cover every validated
strategy (not the 2-5 frozen rows the static blocks showed).

Provides (all GET, read-only, no recompute):
  GET /analytics/significance  - per-strategy p_edge / DSR / PF-CI / t-stat
  GET /analytics/sensitivity   - per-strategy per-parameter PF sensitivity
  GET /analytics/monte-carlo   - per-strategy MC 95th-pct drawdown (+ return
                                 percentiles where a non-degenerate MC artifact
                                 exists on disk)

Sourcing rationale:
  * significance + sensitivity: every gate-v2 verdict carries the raw material
    (``windows[].oos_pf`` for the t-stat; ``gate_v2_metrics.combo_results`` for
    the param grid; ``p_edge`` / ``dsr`` / ``pf_ci_lower`` directly). 38 rows.
  * monte-carlo: the standalone ``*_monte_carlo.json`` artifacts proved stale
    (collapsed percentiles), so the canonical MC signal is the gate's own
    ``mc_95th_dd_pct``. Artifact return-percentiles are layered in ONLY when the
    artifact is non-degenerate (p5 != p95), and flagged ``degenerate`` otherwise.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

# Reuse the canonical verdict directory + parser plumbing from the ledger router
# so there is exactly one definition of "where the verdicts live."
from routers.strategy_ledger_router import _verdicts_dir

logger = logging.getLogger("jarvis_trader.routers.validation_analytics")

router = APIRouter(prefix="/analytics", tags=["analytics", "validation"])


def _results_dir() -> Path:
    """engine/backtest/results — where MC / sensitivity artifacts are persisted."""
    return Path(__file__).resolve().parent.parent / "backtest" / "results"


def _load_verdict_bodies() -> List[Dict[str, Any]]:
    """Read full verdict JSON bodies (NOT the flattened ledger rows — we need
    ``windows`` and ``combo_results`` which the flat parser drops). Never raises
    on a single bad file."""
    vd = _verdicts_dir()
    bodies: List[Dict[str, Any]] = []
    if not vd.exists():
        return bodies
    for path in sorted(vd.glob("*.json")):
        try:
            body = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError, TypeError):
            continue
        if isinstance(body, dict):
            body["_source_file"] = path.name
            bodies.append(body)
    return bodies


# ── Models ───────────────────────────────────────────────────────────────────


class SignificanceEntry(BaseModel):
    symbol: Optional[str] = None
    family: Optional[str] = None
    verdict: Optional[str] = None
    p_edge: Optional[float] = None
    dsr: Optional[float] = None
    pf_ci_lower: Optional[float] = None
    n_oos_trades: Optional[int] = None
    n_windows: Optional[int] = None
    mean_oos_pf: Optional[float] = None
    t_stat: Optional[float] = None
    significant: bool = False
    source_file: Optional[str] = None


class SignificanceResponse(BaseModel):
    entries: List[SignificanceEntry]
    total: int
    n_significant: int
    p_edge_threshold: float
    generated_at: str


class SensitivityParam(BaseModel):
    parameter: str
    pf_min: float
    pf_max: float
    pf_spread: float          # max - min across the param's values
    half_spread: float        # the "+/-" figure (spread / 2)
    best_value: Any = None    # param value with the highest mean PF
    level: str                # LOW | MEDIUM | HIGH


class SensitivityEntry(BaseModel):
    symbol: Optional[str] = None
    family: Optional[str] = None
    verdict: Optional[str] = None
    n_combos: Optional[int] = None
    fixed_params_min_pf: Optional[float] = None
    fixed_params_mean_pf: Optional[float] = None
    fixed_params_max_pf: Optional[float] = None
    params: List[SensitivityParam] = []
    source_file: Optional[str] = None


class SensitivityResponse(BaseModel):
    entries: List[SensitivityEntry]
    total: int
    generated_at: str


class MonteCarloEntry(BaseModel):
    symbol: Optional[str] = None
    family: Optional[str] = None
    timeframe: Optional[str] = None
    verdict: Optional[str] = None
    mc_95th_dd_pct: Optional[float] = None   # gate's own MC drawdown — always real
    # return percentiles, present only when a non-degenerate MC artifact exists
    n_simulations: Optional[int] = None
    n_trades: Optional[int] = None
    return_p5: Optional[float] = None
    return_median: Optional[float] = None
    return_p95: Optional[float] = None
    capital_at_risk_95: Optional[float] = None
    artifact_verdict: Optional[str] = None
    degenerate: Optional[bool] = None        # True if artifact percentiles collapsed
    source: str = "gate_v2"                   # gate_v2 | gate_v2+artifact
    source_file: Optional[str] = None


class MonteCarloResponse(BaseModel):
    entries: List[MonteCarloEntry]
    total: int
    n_with_artifact: int
    generated_at: str


# ── Helpers ──────────────────────────────────────────────────────────────────

P_EDGE_THRESHOLD = 0.95  # gate-v2 edge threshold (see rules/jarvis-trader.md)


def _sensitivity_level(half_spread: float) -> str:
    """Map a parameter's PF half-spread to LOW/MEDIUM/HIGH, calibrated to the
    bands the old static block used (LOW ~±0.08, MEDIUM ~±0.18, HIGH ~±0.31)."""
    if half_spread < 0.15:
        return "LOW"
    if half_spread < 0.30:
        return "MEDIUM"
    return "HIGH"


def _params_from_combos(combos: List[Dict[str, Any]]) -> List[SensitivityParam]:
    """Compute marginal per-parameter PF sensitivity from a gate-v2 combo grid.

    Each combo is e.g. {"fast": 20, "slow": 80, "atr_trail_mult": 1.0,
    "pf": 1.36, "trades": 39}. For each tunable parameter we group combos by that
    param's value, take the mean PF per value, and report the spread of those
    per-value means — i.e. how much PF moves as you slide that one knob.
    """
    if not combos:
        return []
    non_param = {"pf", "trades"}
    param_names = [k for k in combos[0] if k not in non_param]
    out: List[SensitivityParam] = []
    for p in param_names:
        # mean PF per distinct value of this param
        by_val: Dict[Any, List[float]] = {}
        for c in combos:
            v = c.get(p)
            pf = c.get("pf")
            if v is None or pf is None:
                continue
            try:
                by_val.setdefault(v, []).append(float(pf))
            except (TypeError, ValueError):
                continue
        means = {v: (sum(x) / len(x)) for v, x in by_val.items() if x}
        if len(means) < 2:
            continue
        pf_min = min(means.values())
        pf_max = max(means.values())
        spread = pf_max - pf_min
        best_value = max(means, key=lambda k: means[k])
        out.append(
            SensitivityParam(
                parameter=p,
                pf_min=round(pf_min, 4),
                pf_max=round(pf_max, 4),
                pf_spread=round(spread, 4),
                half_spread=round(spread / 2.0, 4),
                best_value=best_value,
                level=_sensitivity_level(spread / 2.0),
            )
        )
    # most-sensitive parameter first
    out.sort(key=lambda sp: sp.pf_spread, reverse=True)
    return out


def _timeframe_from_name(stem: str) -> Optional[str]:
    """Pull a timeframe token (e.g. 1h, 1d, 15m) from a results filename stem."""
    for tok in stem.split("_"):
        if tok and tok[0].isdigit() and tok[-1].isalpha():
            return tok
    return None


def _canonical_mc_artifacts() -> Dict[str, Dict[str, Any]]:
    """Map symbol -> parsed MC artifact for the *canonical* runs only (skip
    _slip / _test / _raw variants). Returns the artifact body keyed by symbol."""
    rd = _results_dir()
    out: Dict[str, Dict[str, Any]] = {}
    if not rd.exists():
        return out
    for path in sorted(rd.glob("*_monte_carlo.json")):
        stem = path.stem  # e.g. MGC_1d_monte_carlo
        # canonical = <SYMBOL>_<TF>_monte_carlo, exactly 3 tokens
        core = stem[: -len("_monte_carlo")] if stem.endswith("_monte_carlo") else stem
        parts = core.split("_")
        if len(parts) != 2:
            continue  # skip slip/test/raw variants
        symbol = parts[0]
        try:
            body = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError, TypeError):
            continue
        body["_timeframe"] = parts[1]
        body["_source_file"] = path.name
        out[symbol] = body
    return out


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get(
    "/significance",
    response_model=SignificanceResponse,
    summary="Statistical significance per strategy (p_edge, DSR, PF-CI, t-stat)",
)
def get_significance(
    symbol: Optional[str] = Query(None, description="Filter by symbol, e.g. MGC"),
    significant_only: bool = Query(False, description="Only rows meeting p_edge threshold"),
) -> SignificanceResponse:
    bodies = _load_verdict_bodies()
    entries: List[SignificanceEntry] = []
    for b in bodies:
        if symbol and b.get("symbol") != symbol:
            continue
        m = b.get("gate_v2_metrics", {}) or {}
        windows = b.get("windows", []) or []
        oos_pfs: List[float] = []
        n_oos = 0
        for w in windows:
            pf = w.get("oos_pf")
            if pf is not None:
                try:
                    pf_f = float(pf)
                    # drop non-finite PFs (a zero-loss window yields inf and would
                    # poison the mean / t-stat) — keep only real, finite values
                    if math.isfinite(pf_f):
                        oos_pfs.append(pf_f)
                except (TypeError, ValueError):
                    pass
            try:
                n_oos += int(w.get("oos_trades", 0) or 0)
            except (TypeError, ValueError):
                pass
        mean_pf = sum(oos_pfs) / len(oos_pfs) if oos_pfs else None
        t_stat = None
        if len(oos_pfs) > 1:
            n = len(oos_pfs)
            # manual sample stdev (statistics.stdev is flaky on floats in this build)
            sd = (sum((x - mean_pf) ** 2 for x in oos_pfs) / (n - 1)) ** 0.5
            if sd > 0:
                # t-stat of OOS PF vs the break-even null (PF == 1.0)
                t_stat = (mean_pf - 1.0) / (sd / math.sqrt(n))
        p_edge = m.get("p_edge")
        significant = p_edge is not None and float(p_edge) >= P_EDGE_THRESHOLD
        entries.append(
            SignificanceEntry(
                symbol=b.get("symbol"),
                family=b.get("family"),
                verdict=b.get("verdict"),
                p_edge=p_edge,
                dsr=m.get("dsr"),
                pf_ci_lower=m.get("pf_ci_lower"),
                n_oos_trades=n_oos or None,
                n_windows=len(windows) or None,
                mean_oos_pf=round(mean_pf, 4) if mean_pf is not None else None,
                t_stat=round(t_stat, 4) if t_stat is not None else None,
                significant=significant,
                source_file=b.get("_source_file"),
            )
        )
    if significant_only:
        entries = [e for e in entries if e.significant]
    entries.sort(key=lambda e: (e.p_edge if e.p_edge is not None else -1), reverse=True)
    return SignificanceResponse(
        entries=entries,
        total=len(entries),
        n_significant=sum(1 for e in entries if e.significant),
        p_edge_threshold=P_EDGE_THRESHOLD,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


@router.get(
    "/sensitivity",
    response_model=SensitivityResponse,
    summary="Per-parameter PF sensitivity per strategy (from gate-v2 combo grid)",
)
def get_sensitivity(
    symbol: Optional[str] = Query(None, description="Filter by symbol, e.g. MGC"),
) -> SensitivityResponse:
    bodies = _load_verdict_bodies()
    entries: List[SensitivityEntry] = []
    for b in bodies:
        if symbol and b.get("symbol") != symbol:
            continue
        m = b.get("gate_v2_metrics", {}) or {}
        combos = m.get("combo_results", []) or []
        params = _params_from_combos(combos)
        if not params:
            continue  # nothing tunable to report for this strategy
        entries.append(
            SensitivityEntry(
                symbol=b.get("symbol"),
                family=b.get("family"),
                verdict=b.get("verdict"),
                n_combos=m.get("n_combos_with_trades") or (len(combos) or None),
                fixed_params_min_pf=m.get("fixed_params_min_pf"),
                fixed_params_mean_pf=m.get("fixed_params_mean_pf"),
                fixed_params_max_pf=m.get("fixed_params_max_pf"),
                params=params,
                source_file=b.get("_source_file"),
            )
        )
    entries.sort(key=lambda e: (e.symbol or "", e.family or ""))
    return SensitivityResponse(
        entries=entries,
        total=len(entries),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


@router.get(
    "/monte-carlo",
    response_model=MonteCarloResponse,
    summary="Monte Carlo risk per strategy (gate MC drawdown + artifact percentiles)",
)
def get_monte_carlo(
    symbol: Optional[str] = Query(None, description="Filter by symbol, e.g. MGC"),
) -> MonteCarloResponse:
    bodies = _load_verdict_bodies()
    artifacts = _canonical_mc_artifacts()
    entries: List[MonteCarloEntry] = []
    n_with_artifact = 0
    for b in bodies:
        sym = b.get("symbol")
        if symbol and sym != symbol:
            continue
        m = b.get("gate_v2_metrics", {}) or {}
        entry = MonteCarloEntry(
            symbol=sym,
            family=b.get("family"),
            verdict=b.get("verdict"),
            mc_95th_dd_pct=m.get("mc_95th_dd_pct"),
            source="gate_v2",
            source_file=b.get("_source_file"),
        )
        art = artifacts.get(sym) if sym else None
        if art:
            dist = art.get("distribution", {}) or {}
            fc = dist.get("final_capital", {}) or {}
            orig = art.get("original", {}) or {}
            final_cap = orig.get("final_capital")
            ret_pct = orig.get("total_return_pct")
            initial = None
            if final_cap and ret_pct is not None:
                try:
                    initial = float(final_cap) / (1.0 + float(ret_pct) / 100.0)
                except (TypeError, ValueError, ZeroDivisionError):
                    initial = None
            p5, med, p95 = fc.get("p5"), fc.get("median"), fc.get("p95")
            degenerate = (p5 is not None and p95 is not None and p5 == p95)
            if initial and not degenerate:
                def _ret(cap: Any, _initial: float = initial) -> Optional[float]:
                    if cap is None:
                        return None
                    try:
                        return round((float(cap) - _initial) / _initial * 100.0, 2)
                    except (TypeError, ValueError):
                        return None
                entry.return_p5 = _ret(p5)
                entry.return_median = _ret(med)
                entry.return_p95 = _ret(p95)
                car = art.get("confidence", {}).get("value_at_risk_5pct")
                entry.capital_at_risk_95 = round(float(car), 2) if car is not None else None
            entry.timeframe = art.get("_timeframe")
            entry.n_simulations = art.get("n_simulations")
            entry.n_trades = art.get("n_trades")
            entry.artifact_verdict = art.get("verdict")
            entry.degenerate = degenerate
            entry.source = "gate_v2+artifact"
            n_with_artifact += 1
        entries.append(entry)
    entries.sort(key=lambda e: (e.symbol or "", e.family or ""))
    return MonteCarloResponse(
        entries=entries,
        total=len(entries),
        n_with_artifact=n_with_artifact,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
