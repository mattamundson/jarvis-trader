"""
JARVIS TRADER — Strategy Ledger Router
======================================
Surfaces the gate-v2 backtest verdict ledger to the dashboard.

The gate-v2 sweep persists one JSON verdict per strategy/symbol/family under
``engine/data/gate_v2_verdicts/`` (top level only — ``archive/`` holds retired
verdicts). Those files are the source of truth for "has this strategy been
validated and is its edge real." Until now they lived only on disk; this router
reads them (no recompute) so the dashboard can render the PASS/FAIL ledger and
so the per-trade review surface can join a trade's strategy to its verdict.

Provides:
  GET /strategy/ledger              - All gate-v2 verdicts as a flat ledger
  GET /strategy/ledger/{symbol}/{family} - One verdict (used by full-review)

Read-only. No DB, no recompute — pure verdict-file reads.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger("jarvis_trader.routers.strategy_ledger")

router = APIRouter(prefix="/strategy", tags=["strategy"])


def _verdicts_dir() -> Path:
    """Canonical gate_v2_verdicts directory, relative to the engine package.

    Router lives in engine/routers/, so parent.parent is the engine root.
    Mirrors analytics.gate_v2_calibrator and discord.digest_generator.
    """
    return Path(__file__).resolve().parent.parent / "data" / "gate_v2_verdicts"


# ── Models ─────────────────────────────────────────────────────────────────────


class LedgerEntry(BaseModel):
    """One gate-v2 verdict, flattened for the dashboard table."""

    symbol: Optional[str] = None
    family: Optional[str] = None
    rank: Optional[int] = None
    verdict: Optional[str] = None  # PASS | FAIL
    passed_via: Optional[str] = None  # core | alt | None
    core_verdict: Optional[str] = None
    alt_verdict: Optional[str] = None
    created_at: Optional[str] = None
    # metrics (gate_v2_metrics)
    pf_ci_lower: Optional[float] = None
    p_edge: Optional[float] = None
    mc_95th_dd_pct: Optional[float] = None
    dsr: Optional[float] = None
    wfo_consistency: Optional[str] = None
    fixed_params_min_pf: Optional[float] = None
    cost_survives_through: Optional[str] = None
    oos_trades: Optional[int] = None
    # provenance
    source_file: Optional[str] = None


class LedgerResponse(BaseModel):
    entries: List[LedgerEntry]
    total: int
    n_pass: int
    n_fail: int
    generated_at: str


# ── Parsing ────────────────────────────────────────────────────────────────────


def _parse_verdict(path: Path) -> Optional[Dict[str, Any]]:
    """Parse one verdict JSON into a flat ledger row. Returns None if malformed
    (never raise — a bad file must not take down the whole ledger)."""
    try:
        body = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError, TypeError):
        return None

    metrics = body.get("gate_v2_metrics", {}) or {}
    windows = body.get("windows", []) or []
    # oos_trades is not stored at metrics level — sum it from the WFO windows.
    oos_trades = metrics.get("n_oos_trades")
    if oos_trades is None:
        try:
            oos_trades = sum(int(w.get("oos_trades", 0) or 0) for w in windows)
        except (TypeError, ValueError):
            oos_trades = None

    return {
        "symbol": body.get("symbol"),
        "family": body.get("family"),
        "rank": body.get("rank"),
        "verdict": body.get("verdict"),
        "passed_via": body.get("passed_via"),
        "core_verdict": body.get("core_verdict"),
        "alt_verdict": body.get("alt_verdict"),
        "created_at": body.get("created_at"),
        "pf_ci_lower": metrics.get("pf_ci_lower"),
        "p_edge": metrics.get("p_edge"),
        "mc_95th_dd_pct": metrics.get("mc_95th_dd_pct"),
        "dsr": metrics.get("dsr"),
        "win_rate_ci_lower": metrics.get("win_rate_ci_lower"),
        "wfo_consistency": metrics.get("wfo_consistency"),
        "fixed_params_min_pf": metrics.get("fixed_params_min_pf"),
        "cost_survives_through": metrics.get("cost_survives_through"),
        "oos_trades": oos_trades,
        "source_file": path.name,
    }


def load_ledger(verdict_dir: "Path | None" = None) -> List[Dict[str, Any]]:
    """Read all top-level verdict JSONs into flat ledger rows.

    Exposed as a module function so the trades full-review endpoint can reuse it
    to look up a strategy's verdict without going back through HTTP.
    """
    vd = verdict_dir or _verdicts_dir()
    rows: List[Dict[str, Any]] = []
    if not vd.exists():
        return rows
    for path in sorted(vd.glob("*.json")):
        row = _parse_verdict(path)
        if row is not None:
            rows.append(row)
    return rows


def find_verdict(symbol: str, family: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Best-effort lookup of a verdict for a (symbol, family). When family is
    unknown or absent, returns the highest-rank (rank==1 preferred) PASS for the
    symbol if one exists, else the most recently created verdict for the symbol.
    Used by the per-trade full-review join where a trade only knows its symbol
    and (sometimes) its strategy family.
    """
    rows = [r for r in load_ledger() if r.get("symbol") == symbol]
    if not rows:
        return None
    if family:
        fam_rows = [r for r in rows if (r.get("family") or "") == family]
        if fam_rows:
            rows = fam_rows

    def _rank_key(r: Dict[str, Any]) -> Any:
        rank = r.get("rank")
        rank = rank if isinstance(rank, (int, float)) else 9999
        is_pass = 0 if r.get("verdict") == "PASS" else 1
        return (is_pass, rank, str(r.get("created_at") or ""))

    return sorted(rows, key=_rank_key)[0]


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.get(
    "/ledger",
    response_model=LedgerResponse,
    summary="Gate-v2 backtest verdict ledger (all strategies/symbols)",
)
def get_strategy_ledger(
    symbol: Optional[str] = Query(None, description="Filter by symbol, e.g. MES"),
    verdict: Optional[str] = Query(None, description="Filter: PASS | FAIL"),
) -> LedgerResponse:
    rows = load_ledger()
    if symbol:
        rows = [r for r in rows if r.get("symbol") == symbol]
    if verdict:
        rows = [r for r in rows if (r.get("verdict") or "").upper() == verdict.upper()]

    entries = [LedgerEntry(**r) for r in rows]
    n_pass = sum(1 for r in rows if r.get("verdict") == "PASS")
    return LedgerResponse(
        entries=entries,
        total=len(entries),
        n_pass=n_pass,
        n_fail=len(entries) - n_pass,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


@router.get(
    "/ledger/{symbol}/{family}",
    response_model=LedgerEntry,
    summary="Single gate-v2 verdict for a symbol/family",
)
def get_strategy_verdict(symbol: str, family: str) -> LedgerEntry:
    row = find_verdict(symbol, family)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No verdict for {symbol}/{family}")
    return LedgerEntry(**row)


# ── Production-gate scorecard ────────────────────────────────────────────────


class GateResult(BaseModel):
    """One of the gate-v2 production gates, judged against its canonical threshold."""

    key: str
    label: str
    value: Optional[float] = None
    threshold: Optional[float] = None
    comparator: str  # ">=" | "<="
    unit: Optional[str] = None  # e.g. "%"
    passed: Optional[bool] = None  # None => not evaluable (missing value or shadow gate)
    enforced: bool = True
    note: Optional[str] = None


class GatesResponse(BaseModel):
    symbol: str
    family: Optional[str] = None
    verdict: Optional[str] = None
    created_at: Optional[str] = None
    n_pass: int
    n_evaluated: int
    n_total: int
    gates: List[GateResult]
    generated_at: str


def build_gate_scorecard(symbol: str, family: Optional[str] = None) -> GatesResponse:
    """Build the 6-gate production scorecard for a symbol from its gate-v2 verdict.

    Reads metrics via ``find_verdict`` and thresholds from
    ``backtest._gate_v2_helpers`` (the single source of truth) — no recompute,
    no new thresholds. A missing verdict yields every gate ``value=None``,
    ``passed=None`` (not "fail" — absence is unknown, not a failure).
    """
    from backtest._gate_v2_helpers import (
        GATE_DSR,
        GATE_MC_DD_CORE,
        GATE_P_EDGE,
        GATE_PF_CI_LOWER,
        GATE_WIN_RATE_CI_LOWER,
        MIN_OOS_TRADES_TOTAL,
        sample_adequacy_enforced,
    )

    row = find_verdict(symbol, family) or {}

    def _f(key: str) -> Optional[float]:
        v = row.get(key)
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    def _ge(value: Optional[float], thr: Optional[float]) -> Optional[bool]:
        if value is None or thr is None:
            return None
        return value >= thr

    def _le(value: Optional[float], thr: Optional[float]) -> Optional[bool]:
        if value is None or thr is None:
            return None
        return value <= thr

    # MC drawdown is stored in PERCENT units (mc_95th_dd_pct, e.g. 0.81 = 0.81%);
    # the helper threshold is a fraction (0.05) — convert to percent to compare.
    dd_value = _f("mc_95th_dd_pct")
    dd_threshold_pct = GATE_MC_DD_CORE * 100.0
    oos = _f("oos_trades")
    win_ci = _f("win_rate_ci_lower")
    sample_enforced = sample_adequacy_enforced()

    gates = [
        GateResult(
            key="pf_ci_lower", label="PF CI lower bound",
            value=_f("pf_ci_lower"), threshold=GATE_PF_CI_LOWER, comparator=">=",
            passed=_ge(_f("pf_ci_lower"), GATE_PF_CI_LOWER),
        ),
        GateResult(
            key="p_edge", label="P(edge)",
            value=_f("p_edge"), threshold=GATE_P_EDGE, comparator=">=",
            passed=_ge(_f("p_edge"), GATE_P_EDGE),
        ),
        GateResult(
            key="mc_95th_dd", label="MC 95th DD", unit="%",
            value=dd_value, threshold=dd_threshold_pct, comparator="<=",
            passed=_le(dd_value, dd_threshold_pct),
        ),
        GateResult(
            key="dsr", label="Deflated Sharpe",
            value=_f("dsr"), threshold=GATE_DSR, comparator=">=",
            passed=_ge(_f("dsr"), GATE_DSR),
        ),
        GateResult(
            key="sample", label="OOS trades",
            value=oos, threshold=float(MIN_OOS_TRADES_TOTAL), comparator=">=",
            enforced=sample_enforced,
            passed=_ge(oos, float(MIN_OOS_TRADES_TOTAL)),
            note=None if sample_enforced else "shadow (not enforced)",
        ),
        GateResult(
            key="win_rate_ci_lower", label="Win-rate CI lower",
            value=win_ci, threshold=GATE_WIN_RATE_CI_LOWER, comparator=">=",
            enforced=GATE_WIN_RATE_CI_LOWER is not None,
            passed=_ge(win_ci, GATE_WIN_RATE_CI_LOWER),
            note="shadow — threshold not yet calibrated" if GATE_WIN_RATE_CI_LOWER is None else None,
        ),
    ]

    n_pass = sum(1 for g in gates if g.passed is True)
    n_evaluated = sum(1 for g in gates if g.passed is not None)
    return GatesResponse(
        symbol=symbol.upper(),
        family=row.get("family"),
        verdict=row.get("verdict"),
        created_at=row.get("created_at"),
        n_pass=n_pass,
        n_evaluated=n_evaluated,
        n_total=len(gates),
        gates=gates,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


@router.get(
    "/gates/{symbol}",
    response_model=GatesResponse,
    summary="Gate-v2 production scorecard (6 gates, pass/fail + values) for a symbol",
)
def get_strategy_gates(symbol: str, family: Optional[str] = Query(None)) -> GatesResponse:
    return build_gate_scorecard(symbol, family)


# ── Research candidates (X-bookmark edge scan; NON-authorizing namespace) ─────
#
# Research verdicts live in engine/data/research_verdicts/ — deliberately SEPARATE
# from gate_v2_verdicts/. gate_v2_policy.is_strategy_authorized reads ONLY
# gate_v2_verdicts/, so a research verdict (even a spurious PASS) can never
# authorize routing. This surface is read-only visibility for the edge pipeline.


def _research_dir() -> Path:
    """Research-verdicts dir, separate from the production authorization dir."""
    return Path(__file__).resolve().parent.parent / "data" / "research_verdicts"


class ResearchCandidate(BaseModel):
    """One X-bookmark edge-scan candidate + its research gate-v2 verdict."""

    strategy: Optional[str] = None
    symbol: Optional[str] = None
    family: Optional[str] = None
    strategy_class: Optional[str] = None
    verdict: Optional[str] = None
    passed_via: Optional[str] = None
    pf_ci_lower: Optional[float] = None
    p_edge: Optional[float] = None
    mc_95th_dd_pct: Optional[float] = None
    dsr: Optional[float] = None
    source_bookmark_url: Optional[str] = None
    author: Optional[str] = None
    scan_date: Optional[str] = None
    class_note: Optional[str] = None
    created_at: Optional[str] = None
    source_file: Optional[str] = None


class ResearchCandidatesResponse(BaseModel):
    candidates: List[ResearchCandidate]
    total: int
    generated_at: str


def _parse_research_verdict(path: Path) -> Optional[Dict[str, Any]]:
    """Flatten one research verdict JSON. Returns None if malformed (never raise)."""
    try:
        body = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError, TypeError):
        return None

    # Only real research verdicts count — skip any stray file lacking the research
    # markers so a mis-dropped verbose report can't surface as a junk candidate.
    if "strategy_class" not in body and "provenance" not in body:
        return None

    metrics = body.get("gate_v2_metrics", {}) or {}
    prov = body.get("provenance", {}) or {}
    return {
        "strategy": body.get("strategy"),
        "symbol": body.get("symbol"),
        "family": body.get("family"),
        "strategy_class": body.get("strategy_class"),
        "verdict": body.get("verdict"),
        "passed_via": body.get("passed_via"),
        "pf_ci_lower": metrics.get("pf_ci_lower"),
        "p_edge": metrics.get("p_edge"),
        "mc_95th_dd_pct": metrics.get("mc_95th_dd_pct"),
        "dsr": metrics.get("dsr"),
        "source_bookmark_url": prov.get("source_bookmark_url"),
        "author": prov.get("author"),
        "scan_date": prov.get("scan_date"),
        "class_note": body.get("class_note"),
        "created_at": body.get("created_at"),
        "source_file": path.name,
    }


def load_research_candidates(research_dir: "Path | None" = None) -> List[Dict[str, Any]]:
    """Read all research verdict JSONs into flat candidate rows."""
    rd = research_dir or _research_dir()
    rows: List[Dict[str, Any]] = []
    if not rd.exists():
        return rows
    for path in sorted(rd.glob("*.json")):
        row = _parse_research_verdict(path)
        if row is not None:
            rows.append(row)
    return rows


@router.get(
    "/research-candidates",
    response_model=ResearchCandidatesResponse,
    summary="X-bookmark edge-scan research candidates (non-authorizing)",
)
def get_research_candidates() -> ResearchCandidatesResponse:
    rows = load_research_candidates()
    return ResearchCandidatesResponse(
        candidates=[ResearchCandidate(**r) for r in rows],
        total=len(rows),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
<<<<<<< HEAD
=======


# ── Equity SMA-trend certification + forward evidence (non-authorizing) ──────
#
# Equity daily SMA-trend WFO certs (engine/backtest/run_equity_sma_cert.py)
# write verdicts named <SYM>_sma_cert_<fast>_<slow>_<atr>.json into
# gate_v2_verdicts/. They share the production verdict directory with futures
# verdicts, but EQUITY verdicts are a separate research lineage: they certify
# a daily-bar equity trend edge (SPY/QQQ PASS, 113 windows) and NEVER route
# capital through the futures gate. This endpoint surfaces them plus the
# closed-trades forward-evidence report so the dashboard can show (a) which
# equity params survived WFO certification and (b) what the live closed-trades
# ledger says about forward (post-cert) performance.

class EquityCertRow(BaseModel):
    """One equity daily SMA-trend WFO certification verdict."""

    symbol: Optional[str] = None
    fast: Optional[int] = None
    slow: Optional[int] = None
    atr_mult: Optional[float] = None
    verdict: Optional[str] = None  # PASS | FAIL
    passed_via: Optional[str] = None
    n_windows: Optional[int] = None
    pf_ci_lower: Optional[float] = None
    p_edge: Optional[float] = None
    dsr: Optional[float] = None
    mc_95th_dd_pct: Optional[float] = None
    total_oos_trades: Optional[int] = None
    created_at: Optional[str] = None
    source_file: Optional[str] = None
    note: Optional[str] = None


class ForwardCandidateRow(BaseModel):
    """One candidate's forward-evidence block from forward_test_report.json."""

    id: Optional[str] = None
    symbol: Optional[str] = None
    graduated: Optional[bool] = None
    forward_n_windows: Optional[int] = None
    forward_p_edge: Optional[float] = None
    forward_pf_ci_lower: Optional[float] = None
    forward_total_trades: Optional[int] = None
    forward_total_pnl: Optional[float] = None
    shuffle_p_value: Optional[float] = None
    shuffle_passes: Optional[bool] = None
    dsr: Optional[float] = None
    stat_gate: Optional[Any] = None  # dict {enforced, ab..., passes, reasons} in the report
    survives_family_fdr: Optional[bool] = None
    reason: Optional[str] = None


class EquityResearchResponse(BaseModel):
    equity_certs: List[EquityCertRow]
    forward_evidence: List[ForwardCandidateRow]
    forward_generated_at: Optional[str] = None
    forward_window_days: Optional[int] = None
    forward_graduation_rule: Optional[Dict[str, Any]] = None
    total: int
    generated_at: str


_EQUITY_CERT_SYMBOLS = {"SPY", "QQQ", "AAPL", "TSLA"}


def _finite(v: Any) -> Optional[float]:
    """Coerce to float; JSON cannot serialize inf/nan, so map them to None."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _parse_equity_cert(path: Path) -> Optional[Dict[str, Any]]:
    """Parse one <SYM>_sma_cert_<f>_<s>_<a>.json into an EquityCertRow dict.

    Only DAILY-bar certs count: the stem must be exactly
    ``<SYM>_sma_cert_<fast>_<slow>_<atr>`` (6 underscore-parts). Suffix variants
    (e.g. ``_daily_PRE_1h_cert``) are stale lineage files and are skipped.
    """
    name = path.stem  # e.g. SPY_sma_cert_10_40_2.0
    parts = name.split("_")
    if len(parts) != 6 or parts[1] != "sma" or parts[2] != "cert":
        return None
    sym = parts[0].upper()
    if sym not in _EQUITY_CERT_SYMBOLS:
        return None
    try:
        fast = int(parts[3])
        slow = int(parts[4])
        atr = float(parts[5])
    except (ValueError, IndexError):
        return None
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    m = d.get("gate_v2_metrics", {}) or {}
    wfo = d.get("wfo_config", {}) or {}
    return {
        "symbol": sym,
        "fast": fast,
        "slow": slow,
        "atr_mult": atr,
        "verdict": d.get("verdict"),
        "passed_via": d.get("passed_via") or d.get("core_verdict"),
        "n_windows": (wfo or {}).get("n_windows"),
        "pf_ci_lower": _finite(m.get("pf_ci_lower")),
        "p_edge": _finite(m.get("p_edge")),
        "dsr": _finite(m.get("dsr")),
        "mc_95th_dd_pct": _finite(m.get("mc_95th_dd_pct")),
        "total_oos_trades": m.get("total_oos_trades"),
        "created_at": d.get("created_at"),
        "source_file": path.name,
        "note": d.get("note") or d.get("class_note"),
    }


def _forward_report_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "forward_test_report.json"


def load_equity_research() -> Dict[str, Any]:
    """Read equity cert verdicts + forward evidence (pure file reads)."""
    certs: List[Dict[str, Any]] = []
    vdir = _verdicts_dir()
    if vdir.exists():
        for path in sorted(vdir.glob("*_sma_cert_*.json")):
            row = _parse_equity_cert(path)
            if row is not None:
                certs.append(row)

    fwd_rows: List[Dict[str, Any]] = []
    fwd_meta: Dict[str, Any] = {}
    fp = _forward_report_path()
    if fp.exists():
        try:
            fr = json.loads(fp.read_text(encoding="utf-8"))
            fwd_meta = {
                "forward_generated_at": fr.get("generated_at"),
                "forward_window_days": fr.get("window_days"),
                "forward_graduation_rule": fr.get("graduation_rule"),
            }
            for c in fr.get("candidates", []) or []:
                fwd = c.get("forward", {}) or {}
                shuf = c.get("trade_shuffle", {}) or {}
                dsr = c.get("dsr", {}) or {}
                fwd_rows.append({
                    "id": c.get("id"),
                    "symbol": c.get("symbol"),
                    "graduated": c.get("graduated"),
                    "forward_n_windows": fwd.get("n_oos_windows"),
                    "forward_p_edge": fwd.get("p_edge"),
                    "forward_pf_ci_lower": fwd.get("pf_ci_lower"),
                    "forward_total_trades": fwd.get("total_trades"),
                    "forward_total_pnl": fwd.get("total_pnl"),
                    "shuffle_p_value": shuf.get("p_value"),
                    "shuffle_passes": shuf.get("passes"),
                    "dsr": dsr.get("dsr"),
                    "stat_gate": c.get("stat_gate"),
                    "survives_family_fdr": c.get("survives_family_fdr"),
                    "reason": c.get("reason"),
                })
        except Exception as e:  # noqa: BLE001
            logger.warning("forward_test_report parse failed: %s", e)

    return {
        "equity_certs": certs,
        "forward_evidence": fwd_rows,
        **fwd_meta,
    }


@router.get(
    "/equity-research",
    response_model=EquityResearchResponse,
    summary="Equity SMA-trend WFO certs + forward evidence (non-authorizing)",
)
def get_equity_research() -> EquityResearchResponse:
    data = load_equity_research()
    certs = data["equity_certs"]
    fwd = data["forward_evidence"]
    return EquityResearchResponse(
        equity_certs=[EquityCertRow(**r) for r in certs],
        forward_evidence=[ForwardCandidateRow(**r) for r in fwd],
        forward_generated_at=data.get("forward_generated_at"),
        forward_window_days=data.get("forward_window_days"),
        forward_graduation_rule=data.get("forward_graduation_rule"),
        total=len(certs) + len(fwd),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
