"""
JARVIS TRADER — Experiment CLI Runner
======================================
Implements the full 11-step n-autoresearch loop for a single RL experiment.

Steps
-----
1.  READ  rl_config.py run history + current best from ExperimentLog
2.  THINK Hypothesis already supplied via --hypothesis
3.  EDIT  reward_config override supplied via --config (applied at runtime, no file edit)
4.  COMMIT (manual — this script prints the recommended git message)
5.  REGISTER experiment category recorded
6.  TRAIN  train_walkforward with reward_config override
7.  MEASURE WFE + PF + Sharpe from trainer output
8.  SCORE  compute_experiment_score()
9.  COMPARE against best from ExperimentLog
10. LOG    log to ExperimentLog (kept=False by default; use --keep to mark kept)
11. PRINT  clear summary with exit code 0=keep / 1=reset

Usage::

    cd engine
    .venv/Scripts/python -m strategies.run_experiment \\
        --symbol MCL \\
        --category reward_shape \\
        --hypothesis "Lower hold_cost reduces over-trading" \\
        --config '{"hold_cost": -0.008}' \\
        --timesteps 100000 \\
        --windows 8

Exit codes
----------
0 — composite score >= best × 0.95  → KEEP recommendation
1 — composite score <  best × 0.95  → RESET recommendation

IMPORTANT: This script does NOT touch git. Keep/reset is manual.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from typing import Optional

logging.basicConfig(
    level=logging.WARNING,  # suppress noisy trainer logs; show only KEEP_THRESHOLD warnings
    format="%(levelname)s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)

# Quieten stable-baselines + gymnasium noise so the summary is readable
for noisy_pkg in (
    "stable_baselines3",
    "gymnasium",
    "strategies.rl_agent",
    "strategies.rl_environment",
):
    logging.getLogger(noisy_pkg).setLevel(logging.ERROR)

# ── Constants ─────────────────────────────────────────────────────────────────

KEEP_THRESHOLD: float = 0.95  # score must be >= best × 0.95 to recommend KEEP
EXIT_KEEP: int = 0
EXIT_RESET: int = 1

# ── CLI ───────────────────────────────────────────────────────────────────────


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="JARVIS RL Experiment Runner — n-autoresearch single-loop",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--symbol",
        required=True,
        help="Instrument symbol, e.g. MCL or MNQ",
    )
    parser.add_argument(
        "--category",
        required=True,
        choices=[
            "reward_shape",
            "episode_config",
            "signal_params",
            "regime_filter",
            "rl_hyperparams",
            "feature_engineering",
            "ablation",
            "combine",
        ],
        help="Experiment category",
    )
    parser.add_argument(
        "--hypothesis",
        required=True,
        help="One-sentence description of the hypothesis being tested",
    )
    parser.add_argument(
        "--config",
        default="{}",
        help="JSON dict of reward_config overrides, e.g. '{\"hold_cost\": -0.008}'",
    )
    parser.add_argument(
        "--timesteps",
        type=int,
        default=100_000,
        help="PPO timesteps per walk-forward window (default: 100 000)",
    )
    parser.add_argument(
        "--windows",
        type=int,
        default=8,
        help="Number of walk-forward windows (default: 8)",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        default=False,
        help="Mark this experiment as kept in the log (default: False — requires manual git keep)",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional explicit run ID (auto-generated if omitted)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Show full trainer log output",
    )
    return parser.parse_args(argv)


# ── Runner ────────────────────────────────────────────────────────────────────


async def run_experiment(args: argparse.Namespace) -> int:
    """Execute the full experiment loop. Returns exit code."""
    if args.verbose:
        logging.getLogger().setLevel(logging.INFO)

    # ── Parse config delta ────────────────────────────────────────────────
    try:
        reward_config_delta: dict = json.loads(args.config)
    except json.JSONDecodeError as exc:
        print(f"ERROR: --config is not valid JSON: {exc}", file=sys.stderr)
        return EXIT_RESET

    # ── Load experiment log ───────────────────────────────────────────────
    from strategies.experiment_log import ExperimentLog, compute_experiment_score

    log = ExperimentLog()
    best = log.get_best(args.symbol)
    best_score: float = best["composite_score"] if best else 0.0
    n_prior = len(log.list_all(args.symbol))

    # ── Train ─────────────────────────────────────────────────────────────
    print(f"\n{'='*64}")
    print("  JARVIS EXPERIMENT RUN")
    print(f"{'='*64}")
    print(f"  Symbol    : {args.symbol.upper()}")
    print(f"  Category  : {args.category}")
    print(f"  Hypothesis: {args.hypothesis}")
    print(f"  Config Δ  : {json.dumps(reward_config_delta)}")
    print(f"  Timesteps : {args.timesteps:,} × {args.windows} windows")
    print(f"  Prior runs: {n_prior}")
    print(f"  Best score: {best_score:.4f}" + (f"  ({best['run_id']})" if best else "  (none yet)"))
    print(f"{'='*64}")
    print("  Training ... (this may take several minutes)")
    print()

    from strategies.rl_trainer import RLTrainer

    trainer = RLTrainer()
    result = await trainer.train_walkforward(
        symbol=args.symbol,
        timesteps_per_window=args.timesteps,
        n_windows=args.windows,
        reward_config=reward_config_delta if reward_config_delta else None,
    )

    if result.get("status") == "error":
        print(f"ERROR: Training failed — {result.get('error')}", file=sys.stderr)
        return EXIT_RESET

    # ── Extract metrics ───────────────────────────────────────────────────
    agg = result.get("aggregate_metrics", {})
    wfe: float = float(result.get("wfe", 0.0))
    pf: float = float(agg.get("profit_factor", 0.0))
    sharpe: float = float(agg.get("sharpe", 0.0))
    n_trades: int = int(agg.get("n_trades", 0))
    pass_rate: float = float(result.get("pass_rate", 0.0))
    recommendation: str = result.get("recommendation", "unknown")

    metrics = {
        "pf": pf,
        "wfe": wfe,
        "sharpe": sharpe,
        "n_trades": n_trades,
        "pass_rate": pass_rate,
        "recommendation": recommendation,
    }

    # ── Score ─────────────────────────────────────────────────────────────
    score: float = compute_experiment_score(wfe=wfe, pf=pf, sharpe=sharpe, n_trades=n_trades)

    # ── Compare ───────────────────────────────────────────────────────────
    threshold = best_score * KEEP_THRESHOLD
    is_keep = score >= threshold

    # ── Log ───────────────────────────────────────────────────────────────
    run_id = log.log_experiment(
        symbol=args.symbol,
        category=args.category,
        hypothesis=args.hypothesis,
        reward_config_delta=reward_config_delta,
        metrics=metrics,
        composite_score=score,
        kept=args.keep or is_keep,
        run_id=args.run_id,
    )

    # ── Summary ───────────────────────────────────────────────────────────
    verdict = "KEEP  ✓" if is_keep else "RESET ✗"
    vs_best = f"+{score - best_score:+.4f}" if best_score > 0 else "N/A (first)"
    n_windows_pass = sum(1 for w in result.get("windows", []) if w.get("window_pass"))
    n_windows_total = len(result.get("windows", []))

    print(f"\n{'='*64}")
    print(f"  EXPERIMENT RESULT — Run #{n_prior + 1}  [{run_id}]")
    print(f"{'='*64}")
    print(f"  WFE       : {wfe:.4f}")
    print(f"  PF        : {pf:.4f}")
    print(f"  Sharpe    : {sharpe:.4f}")
    print(f"  Trades    : {n_trades}  (avg across windows)")
    print(f"  WF Pass   : {n_windows_pass}/{n_windows_total} windows")
    print(f"  Pass rate : {pass_rate:.1%}")
    print(f"  Recommend : {recommendation.upper()}")
    print(f"{'─'*64}")
    print(f"  SCORE     : {score:.4f}  (vs best {best_score:.4f}  Δ {vs_best})")
    print(f"  THRESHOLD : {threshold:.4f}  ({KEEP_THRESHOLD:.0%} of best)")
    print(f"{'─'*64}")
    print(f"  VERDICT   : {verdict}")
    print(f"{'='*64}")

    if is_keep:
        print("\n  Suggested git commit:")
        print(f'    git commit -m "rl-exp: [{run_id}] {args.category} — {args.hypothesis[:60]}"')
        print("\n  To mark this run as kept in the experiment log:")
        print("    re-run with --keep flag")
    else:
        print("\n  Suggested git command:")
        print("    git reset --hard HEAD  # revert rl_config.py changes")
        print(f"\n  Score {score:.4f} < threshold {threshold:.4f} — RESET recommended.")

    print()
    return EXIT_KEEP if is_keep else EXIT_RESET


# ── Entry point ───────────────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    return asyncio.run(run_experiment(args))


if __name__ == "__main__":
    sys.exit(main())
