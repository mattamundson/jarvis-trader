"""
JARVIS TRADER — Two-Layer Institutional Evaluation Harness
Inspired by rv64m/autotrade's institutional screening process.

This is FIXED evaluation code — the discovery loop's LLM cannot modify it.

Layer 1: Statistical Validity (checked first — if fails, Layer 2 is meaningless)
Layer 2: Risk-Adjusted Return (only meaningful when Layer 1 passes)

Verdict: ELIGIBLE | DISCARD_RISK | DISCARD_PROFIT | CRASH
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import List

from backtest.trade_manager import BacktestResult


class Verdict(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    DISCARD_RISK = "DISCARD_RISK"
    DISCARD_PROFIT = "DISCARD_PROFIT"
    CRASH = "CRASH"


@dataclass
class EvaluationResult:
    verdict: Verdict
    layer1_passed: bool
    layer2_passed: bool
    violations: List[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)

    def summary(self) -> str:
        status = "PASS" if self.verdict == Verdict.ELIGIBLE else "FAIL"
        parts = [f"[{self.verdict.value}] {status}"]
        if self.violations:
            parts.append(" | ".join(self.violations))
        return " — ".join(parts)


# ─── Configurable gates (discovery-friendly, more lenient than paper validation) ───

# Layer 1: Statistical Validity
MIN_TRADES = 30
MIN_EXPOSURE_PCT = 5.0

# Layer 2: Risk-Adjusted Return
MIN_SHARPE = 1.0
MIN_CALMAR = 1.0
MIN_PROFIT_FACTOR = 1.5
MAX_DRAWDOWN_PCT = 20.0


def _safe_float(val: float) -> float:
    if val is None or math.isnan(val) or math.isinf(val):
        return 0.0
    return val


def evaluate(result: BacktestResult) -> EvaluationResult:
    """
    Two-layer institutional screening of a backtest result.

    Returns EvaluationResult with verdict and detailed breakdown.
    """
    violations: List[str] = []
    details: dict = {}

    # ─── CRASH detection ───
    if result.total_trades == 0:
        return EvaluationResult(
            verdict=Verdict.CRASH,
            layer1_passed=False,
            layer2_passed=False,
            violations=["zero trades — no signals fired"],
            details={"total_trades": 0},
        )

    pf = _safe_float(result.profit_factor)
    if pf == 0.0 and result.total_trades > 0:
        return EvaluationResult(
            verdict=Verdict.CRASH,
            layer1_passed=False,
            layer2_passed=False,
            violations=["degenerate result — profit factor is zero or NaN"],
            details={"total_trades": result.total_trades, "profit_factor": pf},
        )

    # ─── Layer 1: Statistical Validity ───
    trades_ok = result.total_trades >= MIN_TRADES
    exposure_ok = result.exposure_time_pct >= MIN_EXPOSURE_PCT

    if not trades_ok:
        violations.append(
            f"{result.total_trades} trades < min {MIN_TRADES} — sample too small"
        )
    if not exposure_ok:
        violations.append(
            f"exposure {result.exposure_time_pct:.1f}% < min {MIN_EXPOSURE_PCT}% — rarely in market"
        )

    layer1_passed = trades_ok and exposure_ok

    details["layer1"] = {
        "total_trades": result.total_trades,
        "min_trades": MIN_TRADES,
        "trades_ok": trades_ok,
        "exposure_time_pct": result.exposure_time_pct,
        "min_exposure_pct": MIN_EXPOSURE_PCT,
        "exposure_ok": exposure_ok,
    }

    # ─── Layer 2: Risk-Adjusted Return ───
    sharpe = _safe_float(result.sharpe_ratio)
    calmar = _safe_float(result.calmar_ratio)
    profit_factor = _safe_float(result.profit_factor)
    max_dd = _safe_float(result.max_drawdown_pct) * 100  # Convert to %

    sharpe_ok = sharpe >= MIN_SHARPE
    calmar_ok = calmar >= MIN_CALMAR
    pf_ok = profit_factor >= MIN_PROFIT_FACTOR
    dd_ok = max_dd <= MAX_DRAWDOWN_PCT

    if not sharpe_ok:
        violations.append(f"Sharpe {sharpe:.2f} < min {MIN_SHARPE}")
    if not calmar_ok:
        violations.append(f"Calmar {calmar:.2f} < min {MIN_CALMAR}")
    if not pf_ok:
        violations.append(f"PF {profit_factor:.2f} < min {MIN_PROFIT_FACTOR}")
    if not dd_ok:
        violations.append(f"MaxDD {max_dd:.1f}% > max {MAX_DRAWDOWN_PCT}%")

    layer2_passed = sharpe_ok and calmar_ok and pf_ok and dd_ok

    details["layer2"] = {
        "sharpe": sharpe,
        "min_sharpe": MIN_SHARPE,
        "sharpe_ok": sharpe_ok,
        "calmar": calmar,
        "min_calmar": MIN_CALMAR,
        "calmar_ok": calmar_ok,
        "profit_factor": profit_factor,
        "min_profit_factor": MIN_PROFIT_FACTOR,
        "pf_ok": pf_ok,
        "max_drawdown_pct": max_dd,
        "max_drawdown_limit": MAX_DRAWDOWN_PCT,
        "dd_ok": dd_ok,
    }

    # ─── Verdict ───
    if not layer1_passed:
        verdict = Verdict.DISCARD_RISK
    elif not layer2_passed:
        verdict = Verdict.DISCARD_PROFIT
    else:
        verdict = Verdict.ELIGIBLE

    return EvaluationResult(
        verdict=verdict,
        layer1_passed=layer1_passed,
        layer2_passed=layer2_passed,
        violations=violations,
        details=details,
    )
