"""
Funnel Gate — Tier A/B/C decision engine
========================================

Independent reimplementation of the gating logic per references/thresholds.md.
Does NOT inherit from engine/backtest/gate_v2_policy.py — instead, runs in
parallel and flags disagreements for review.

Inputs (per strategy):
  - strategy card (JSONL line)
  - backtest results directory containing:
      - returns.parquet (timestamped strategy returns)
      - trades.parquet (individual trade records)
      - wfo_folds.json (WFO output)
      - cpcv_paths.json (CPCV output)
      - regime_breakdown.json (per-regime metrics)
      - permutation_test.json (permutation test output)
      - monte_carlo.json (bootstrap output)

Outputs:
  - verdict.json per strategy (Tier A/B/C + gate-by-gate results)
  - Disagreement flag if gate_v2 reached a different verdict

Run:
    python -m jarvis_funnel.funnel_gate \
        --card strategies_v2.jsonl \
        --results-dir results/ \
        --out-dir verdicts/
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("jarvis_funnel.gate")

# ── Thresholds (mirror of references/thresholds.md) ──────────────────────────

THRESHOLDS = {
    "gate_1_dsr_min": 0.80,
    "gate_2_pbo_max": 0.40,
    "gate_3_pf_ci_lower_min": 1.15,
    "gate_4_oos_is_degradation_max": 0.40,
    "gate_5_min_oos_trades": 40,
    "gate_6_min_regimes_above_dsr_floor": 2,
    "gate_6_regime_dsr_floor": 0.50,
    "gate_6_specialist_dsr_floor": 1.20,
    "gate_7_max_dd_to_avg_trade_max": 25.0,
    "gate_8_stress_slippage_multiplier": 2.0,
    "gate_8_stressed_dsr_min": 0.50,
    "gate_9_permutation_p_max": 0.05,
    # Tier B fallback rules
    "tier_b_dsr_min": 1.0,
    "tier_b_max_failed_gates": 2,
}


# ── Result Data Models ───────────────────────────────────────────────────────


@dataclass
class GateResult:
    gate_number: int
    gate_name: str
    passed: bool
    actual_value: Optional[float]
    threshold: Optional[float]
    reason: str = ""


@dataclass
class Verdict:
    hypothesis_id: str
    verdict_timestamp: str
    funnel_gate_version: str  # git sha of this file at time of run
    tier: str  # "A" | "B" | "C"
    gate_results: list = field(default_factory=list)
    failed_gates: list[int] = field(default_factory=list)
    overall_dsr: Optional[float] = None
    improvement_hypotheses: list[str] = field(default_factory=list)
    kill_reason: str = ""
    gate_v2_verdict_at_time: Optional[str] = None
    gate_v2_disagreement: bool = False
    manual_override: bool = False
    manual_override_reason: str = ""
    notes: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["gate_results"] = [asdict(g) for g in self.gate_results]
        return d


# ── Gate Implementations ─────────────────────────────────────────────────────


def gate_1_deflated_sharpe(results: dict) -> GateResult:
    dsr = results.get("deflated_sharpe", {}).get("dsr")
    if dsr is None:
        return GateResult(1, "Deflated Sharpe Ratio", False, None, THRESHOLDS["gate_1_dsr_min"],
                          "DSR not computed — required input missing")
    passed = dsr >= THRESHOLDS["gate_1_dsr_min"]
    return GateResult(1, "Deflated Sharpe Ratio", passed, dsr, THRESHOLDS["gate_1_dsr_min"],
                      f"DSR={dsr:.3f} {'≥' if passed else '<'} {THRESHOLDS['gate_1_dsr_min']}")


def gate_2_pbo(results: dict) -> GateResult:
    pbo = results.get("pbo")
    if pbo is None:
        return GateResult(2, "Probability of Backtest Overfit", False, None, THRESHOLDS["gate_2_pbo_max"],
                          "PBO not computed")
    passed = pbo < THRESHOLDS["gate_2_pbo_max"]
    return GateResult(2, "Probability of Backtest Overfit", passed, pbo, THRESHOLDS["gate_2_pbo_max"],
                      f"PBO={pbo:.3f} {'<' if passed else '≥'} {THRESHOLDS['gate_2_pbo_max']}")


def gate_3_pf_ci(results: dict) -> GateResult:
    pf_ci_lower = results.get("monte_carlo", {}).get("pf_95ci_lower")
    if pf_ci_lower is None:
        return GateResult(3, "Profit Factor 95% CI Lower", False, None, THRESHOLDS["gate_3_pf_ci_lower_min"],
                          "PF CI not computed")
    passed = pf_ci_lower > THRESHOLDS["gate_3_pf_ci_lower_min"]
    return GateResult(3, "Profit Factor 95% CI Lower", passed, pf_ci_lower, THRESHOLDS["gate_3_pf_ci_lower_min"],
                      f"PF CI lower={pf_ci_lower:.3f} {'>' if passed else '≤'} {THRESHOLDS['gate_3_pf_ci_lower_min']}")


def gate_4_degradation(results: dict) -> GateResult:
    sr_is = results.get("sharpe_in_sample")
    sr_oos = results.get("sharpe_out_of_sample")
    if sr_is is None or sr_oos is None or sr_is <= 0:
        return GateResult(4, "OOS/IS Sharpe Degradation", False, None, THRESHOLDS["gate_4_oos_is_degradation_max"],
                          "IS or OOS Sharpe missing or non-positive")
    degradation = 1 - (sr_oos / sr_is)
    passed = degradation < THRESHOLDS["gate_4_oos_is_degradation_max"]
    return GateResult(4, "OOS/IS Sharpe Degradation", passed, degradation, THRESHOLDS["gate_4_oos_is_degradation_max"],
                      f"Degradation={degradation:.1%} (IS={sr_is:.2f}, OOS={sr_oos:.2f})")


def gate_5_min_trades(results: dict) -> GateResult:
    n_trades = results.get("n_oos_trades")
    if n_trades is None:
        return GateResult(5, "Minimum OOS Trades", False, None, THRESHOLDS["gate_5_min_oos_trades"],
                          "Trade count missing")
    passed = n_trades >= THRESHOLDS["gate_5_min_oos_trades"]
    return GateResult(5, "Minimum OOS Trades", passed, float(n_trades), float(THRESHOLDS["gate_5_min_oos_trades"]),
                      f"N OOS trades={n_trades} {'≥' if passed else '<'} {THRESHOLDS['gate_5_min_oos_trades']}")


def gate_6_regime_breadth(results: dict) -> GateResult:
    regimes = results.get("regime_breakdown", {})
    if not regimes:
        return GateResult(6, "Regime Breadth", False, None, None, "Regime breakdown missing")

    # Count regimes where DSR >= floor
    above_floor = sum(1 for r in regimes.values() if r.get("dsr", 0) >= THRESHOLDS["gate_6_regime_dsr_floor"])
    # Or any single regime with DSR >= specialist floor
    has_specialist = any(r.get("dsr", 0) >= THRESHOLDS["gate_6_specialist_dsr_floor"] for r in regimes.values())

    passed = above_floor >= THRESHOLDS["gate_6_min_regimes_above_dsr_floor"] or has_specialist
    return GateResult(6, "Regime Breadth", passed, float(above_floor), float(THRESHOLDS["gate_6_min_regimes_above_dsr_floor"]),
                      f"{above_floor} regime(s) ≥ DSR {THRESHOLDS['gate_6_regime_dsr_floor']}; specialist={has_specialist}")


def gate_7_max_dd_ratio(results: dict) -> GateResult:
    max_dd = results.get("max_drawdown")
    avg_trade = results.get("avg_trade_pnl")
    if max_dd is None or avg_trade is None or avg_trade <= 0:
        return GateResult(7, "Max DD / Avg Trade", False, None, THRESHOLDS["gate_7_max_dd_to_avg_trade_max"],
                          "Max DD or avg trade missing/non-positive")
    ratio = abs(max_dd) / avg_trade
    passed = ratio < THRESHOLDS["gate_7_max_dd_to_avg_trade_max"]
    return GateResult(7, "Max DD / Avg Trade Ratio", passed, ratio, THRESHOLDS["gate_7_max_dd_to_avg_trade_max"],
                      f"Ratio={ratio:.1f}× {'<' if passed else '≥'} {THRESHOLDS['gate_7_max_dd_to_avg_trade_max']}×")


def gate_8_slippage_stress(results: dict) -> GateResult:
    stressed_dsr = results.get("slippage_stress", {}).get("dsr_at_2x_slippage")
    if stressed_dsr is None:
        return GateResult(8, "Slippage Stress", False, None, THRESHOLDS["gate_8_stressed_dsr_min"],
                          "Stressed backtest not run")
    passed = stressed_dsr >= THRESHOLDS["gate_8_stressed_dsr_min"]
    return GateResult(8, "Slippage Stress (2× slippage)", passed, stressed_dsr, THRESHOLDS["gate_8_stressed_dsr_min"],
                      f"Stressed DSR={stressed_dsr:.3f} {'≥' if passed else '<'} {THRESHOLDS['gate_8_stressed_dsr_min']}")


def gate_9_permutation(results: dict) -> GateResult:
    p_value = results.get("permutation_test", {}).get("p_value")
    if p_value is None:
        return GateResult(9, "Permutation Test", False, None, THRESHOLDS["gate_9_permutation_p_max"],
                          "Permutation test not run")
    passed = p_value < THRESHOLDS["gate_9_permutation_p_max"]
    return GateResult(9, "Permutation Test p-value", passed, p_value, THRESHOLDS["gate_9_permutation_p_max"],
                      f"p={p_value:.4f} {'<' if passed else '≥'} {THRESHOLDS['gate_9_permutation_p_max']}")


def gate_10_contamination(results: dict) -> GateResult:
    contamination = results.get("bar_contamination_check", {})
    has_sentinels = contamination.get("sentinel_100_5_rows", 0) > 0
    has_anomalies = contamination.get("anomalous_jumps", 0) > 0
    passed = not (has_sentinels or has_anomalies)
    reason = "Clean" if passed else (
        f"FAIL: sentinel rows={contamination.get('sentinel_100_5_rows', 0)}, "
        f"anomalous jumps={contamination.get('anomalous_jumps', 0)}"
    )
    return GateResult(10, "Bar Contamination Check", passed, None, None, reason)


ALL_GATES = [
    gate_1_deflated_sharpe,
    gate_2_pbo,
    gate_3_pf_ci,
    gate_4_degradation,
    gate_5_min_trades,
    gate_6_regime_breadth,
    gate_7_max_dd_ratio,
    gate_8_slippage_stress,
    gate_9_permutation,
    gate_10_contamination,
]


# ── Decision Engine ──────────────────────────────────────────────────────────


def adjudicate(strategy_card: dict, results: dict, gate_v2_verdict: Optional[str] = None) -> Verdict:
    gate_results = [gate(results) for gate in ALL_GATES]
    failed = [g.gate_number for g in gate_results if not g.passed]

    dsr = results.get("deflated_sharpe", {}).get("dsr")

    # Determine tier
    if not failed:
        tier = "A"
    elif (
        9 not in failed
        and 10 not in failed
        and len(failed) <= THRESHOLDS["tier_b_max_failed_gates"]
        and dsr is not None
        and dsr >= THRESHOLDS["tier_b_dsr_min"]
    ):
        tier = "B"
    else:
        tier = "C"

    # Build improvement hypotheses for Tier B
    improvements = []
    if tier == "B":
        improvements = _generate_improvements(failed, gate_results, strategy_card)

    kill_reason = ""
    if tier == "C":
        failure_summaries = [f"Gate {g.gate_number} ({g.gate_name}): {g.reason}" for g in gate_results if not g.passed]
        kill_reason = "; ".join(failure_summaries)

    # Disagreement flag
    disagreement = False
    if gate_v2_verdict:
        if (tier == "A" and gate_v2_verdict.upper() == "FAIL") or (tier == "C" and gate_v2_verdict.upper() == "PASS"):
            disagreement = True

    funnel_gate_sha = _get_self_git_sha()

    return Verdict(
        hypothesis_id=strategy_card["hypothesis_id"],
        verdict_timestamp=datetime.now(timezone.utc).isoformat(),
        funnel_gate_version=funnel_gate_sha,
        tier=tier,
        gate_results=gate_results,
        failed_gates=failed,
        overall_dsr=dsr,
        improvement_hypotheses=improvements,
        kill_reason=kill_reason,
        gate_v2_verdict_at_time=gate_v2_verdict,
        gate_v2_disagreement=disagreement,
    )


def _generate_improvements(failed_gates: list[int], gate_results: list[GateResult], strategy_card: dict) -> list[str]:
    """Auto-generate 2–3 improvement hypotheses based on which gates failed."""
    suggestions = []

    for gnum in failed_gates:
        gate = next((g for g in gate_results if g.gate_number == gnum), None)
        if not gate:
            continue

        if gnum == 1:  # DSR
            suggestions.append("Reduce number of trials per strategy family (lower N) by collapsing redundant parameter sweeps")
        elif gnum == 2:  # PBO
            suggestions.append("Reduce parameter count; PBO scales with how many ways the strategy can be tuned")
        elif gnum == 3:  # PF CI
            suggestions.append("Tighten stops or improve entry timing to push average winner / average loser ratio higher")
        elif gnum == 4:  # Degradation
            suggestions.append("Replace optimized parameters with broader defaults; current params are likely IS-overfit")
        elif gnum == 5:  # Min trades
            suggestions.append(f"Relax entry criteria to generate more signals (current OOS trades likely < 40 over 24mo)")
        elif gnum == 6:  # Regime breadth
            suggestions.append("Add regime filter — only trade in the regime where strategy showed DSR ≥ 0.5")
        elif gnum == 7:  # Max DD
            suggestions.append("Add max-loss-per-day or trailing equity stop to cap the bad-period damage")
        elif gnum == 8:  # Slippage stress
            suggestions.append("Strategy is execution-sensitive; consider widening entry trigger or limiting to liquid hours only")

    return suggestions[:3]


def _get_self_git_sha() -> str:
    """Get git sha of this file for audit trail."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=Path(__file__).parent,
        )
        if result.returncode == 0:
            return result.stdout.strip()[:12]
    except Exception:
        pass
    return "unknown"


# ── I/O Helpers ──────────────────────────────────────────────────────────────


def load_strategy_cards(jsonl_path: Path) -> list[dict]:
    cards = []
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cards.append(json.loads(line))
    return cards


def load_results_for_strategy(results_dir: Path, hypothesis_id: str) -> Optional[dict]:
    """Aggregate all result files for one strategy into a single dict."""
    strategy_dir = results_dir / hypothesis_id
    if not strategy_dir.exists():
        logger.warning(f"No results directory for {hypothesis_id}")
        return None

    aggregated = {}
    file_to_key = {
        "deflated_sharpe.json": "deflated_sharpe",
        "pbo.json": "pbo_full",
        "monte_carlo.json": "monte_carlo",
        "regime_breakdown.json": "regime_breakdown",
        "permutation_test.json": "permutation_test",
        "slippage_stress.json": "slippage_stress",
        "bar_contamination.json": "bar_contamination_check",
        "summary.json": "_summary",
    }

    for fname, key in file_to_key.items():
        fpath = strategy_dir / fname
        if fpath.exists():
            try:
                aggregated[key] = json.loads(fpath.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Failed to parse {fpath}: {e}")

    # Pull rollup fields from summary if present
    summary = aggregated.pop("_summary", {})
    for k in ["sharpe_in_sample", "sharpe_out_of_sample", "n_oos_trades", "max_drawdown", "avg_trade_pnl", "pbo", "gate_v2_verdict"]:
        if k in summary:
            aggregated[k] = summary[k]

    return aggregated if aggregated else None


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Funnel gate Tier A/B/C adjudicator")
    parser.add_argument("--cards", type=Path, required=True, help="Strategy cards JSONL")
    parser.add_argument("--results-dir", type=Path, required=True, help="Per-strategy results directory")
    parser.add_argument("--out-dir", type=Path, required=True, help="Where to write verdicts/")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    args.out_dir.mkdir(parents=True, exist_ok=True)

    cards = load_strategy_cards(args.cards)
    logger.info(f"Loaded {len(cards)} cards")

    counts = {"A": 0, "B": 0, "C": 0, "SKIPPED": 0}
    disagreements = []

    for card in cards:
        hid = card["hypothesis_id"]
        results = load_results_for_strategy(args.results_dir, hid)
        if results is None:
            counts["SKIPPED"] += 1
            continue

        gate_v2_verdict = results.get("gate_v2_verdict")
        verdict = adjudicate(card, results, gate_v2_verdict)
        counts[verdict.tier] += 1
        if verdict.gate_v2_disagreement:
            disagreements.append({"hypothesis_id": hid, "funnel_tier": verdict.tier, "gate_v2": gate_v2_verdict})

        (args.out_dir / f"{hid}__verdict.json").write_text(
            json.dumps(verdict.to_dict(), indent=2), encoding="utf-8"
        )

    logger.info("=== Funnel Gate Summary ===")
    for tier, n in counts.items():
        logger.info(f"  Tier {tier}: {n}")
    logger.info(f"  Disagreements with gate_v2: {len(disagreements)}")
    if disagreements:
        (args.out_dir / "_disagreements.json").write_text(json.dumps(disagreements, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
