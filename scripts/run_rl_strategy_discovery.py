#!/usr/bin/env python
"""
JARVIS TRADER — RL Strategy Discovery Runner
=============================================

Entry point for running the PPO strategy discovery pipeline.

Usage:
    # Quick smoke (100 steps, synthetic data, CPU-friendly, ~10 seconds)
    python scripts/run_rl_strategy_discovery.py --symbol MES --quick-smoke

    # Full training (multi-hour on CPU; GPU recommended)
    python scripts/run_rl_strategy_discovery.py --symbol MES --n-steps 500000

    # Save to a specific directory
    python scripts/run_rl_strategy_discovery.py --symbol MCL --n-steps 100000 \\
        --policy-dir engine/data/rl_policies

Output:
    Training log     -> stdout
    Policy           -> engine/data/rl_policies/<symbol>-<timestamp>.zip
    Hypothesis JSON  -> engine/data/research_hypotheses/<YYYY-MM-DD>/rl-<symbol>-<n>.json

Environment variables:
    ENABLE_RL_STRATEGY_DISCOVERY=1   (REQUIRED — default 0 / OFF)
    See engine/.env.example for the full list.

See also:
    docs/runbooks/RL_STRATEGY_DISCOVERY_RUNBOOK.md
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Path bootstrap ────────────────────────────────────────────────────────────
# Allow running from the repo root: python scripts/run_rl_strategy_discovery.py
# The engine/ directory must be on sys.path so relative imports work.

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ENGINE_DIR = _REPO_ROOT / "engine"
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("rl_discovery")


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="JARVIS TRADER — RL Strategy Discovery (PPO)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--symbol",
        default="MES",
        help="Futures symbol to train on (default: MES)",
    )
    parser.add_argument(
        "--n-steps",
        type=int,
        default=10_000,
        help="Training timesteps for full run (default: 10000; ignored with --quick-smoke)",
    )
    parser.add_argument(
        "--quick-smoke",
        action="store_true",
        help=(
            "Run only 100 timesteps on synthetic data (~10 seconds, CPU-friendly). "
            "Validates the full pipeline without real data or GPU. "
            "Default: True when n-steps <= 100."
        ),
    )
    parser.add_argument(
        "--policy-dir",
        default=None,
        help="Directory to save policy zip (default: engine/data/rl_policies/)",
    )
    parser.add_argument(
        "--skip-hypothesis",
        action="store_true",
        help="Skip policy_to_hypothesis conversion and JSON export.",
    )
    parser.add_argument(
        "--force-enable",
        action="store_true",
        help=(
            "Bypass ENABLE_RL_STRATEGY_DISCOVERY feature flag check. "
            "Useful for manual one-off runs without editing .env."
        ),
    )
    args = parser.parse_args()

    # ── Feature flag check ────────────────────────────────────────────────
    from strategies.rl_train import is_rl_discovery_enabled

    if args.force_enable:
        os.environ["ENABLE_RL_STRATEGY_DISCOVERY"] = "1"
        logger.info("[rl_discovery] --force-enable set: ENABLE_RL_STRATEGY_DISCOVERY=1")

    if not is_rl_discovery_enabled():
        logger.error(
            "[rl_discovery] ENABLE_RL_STRATEGY_DISCOVERY is not set to '1'.  "
            "Add it to engine/.env or pass --force-enable to bypass."
        )
        return 1

    quick_smoke = args.quick_smoke or args.n_steps <= 100

    logger.info(
        "[rl_discovery] Starting | symbol=%s n_steps=%d quick_smoke=%s",
        args.symbol,
        args.n_steps,
        quick_smoke,
    )

    # ── Train ─────────────────────────────────────────────────────────────
    from strategies.rl_train import policy_to_hypothesis, train_ppo

    try:
        train_result = train_ppo(
            symbol=args.symbol,
            n_steps=args.n_steps,
            save_path=args.policy_dir,
            quick_smoke=quick_smoke,
            _bypass_flag=True,  # flag already checked above
        )
    except ImportError as exc:
        logger.error("[rl_discovery] %s", exc)
        logger.error(
            "[rl_discovery] Install stable-baselines3: "
            "engine/.venv/Scripts/pip install stable-baselines3"
        )
        return 1

    logger.info(
        "[rl_discovery] Training complete | steps=%d mean_reward=%.4f time=%.1fs",
        train_result["n_steps"],
        train_result["mean_reward"],
        train_result["training_time_s"],
    )
    logger.info("[rl_discovery] Policy saved: %s", train_result["policy_path"])
    print(json.dumps(train_result, indent=2))

    if args.skip_hypothesis:
        logger.info(
            "[rl_discovery] --skip-hypothesis: skipping policy_to_hypothesis step"
        )
        return 0

    # ── Convert policy to hypothesis ──────────────────────────────────────
    logger.info("[rl_discovery] Converting policy to StrategyHypothesis ...")

    try:
        hyp = policy_to_hypothesis(
            policy_path=train_result["policy_path"],
            symbol=args.symbol,
            _bypass_flag=True,
        )
    except ImportError as exc:
        logger.warning("[rl_discovery] policy_to_hypothesis skipped: %s", exc)
        return 0

    logger.info(
        "[rl_discovery] Hypothesis generated | name=%s symbol=%s confidence=%.2f",
        hyp.name,
        hyp.symbol,
        hyp.confidence,
    )

    # ── Save hypothesis JSON ──────────────────────────────────────────────
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    hyp_dir = _ENGINE_DIR / "data" / "research_hypotheses" / date_str
    hyp_dir.mkdir(parents=True, exist_ok=True)

    # Count existing RL hypotheses for today to build a unique filename
    existing = list(hyp_dir.glob(f"rl-{args.symbol.lower()}-*.json"))
    n = len(existing) + 1
    hyp_path = hyp_dir / f"rl-{args.symbol.lower()}-{n:03d}.json"

    hyp_dict = hyp.model_dump()
    with open(hyp_path, "w") as fh:
        json.dump(hyp_dict, fh, indent=2)

    logger.info("[rl_discovery] Hypothesis JSON saved: %s", hyp_path)
    print(json.dumps(hyp_dict, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
