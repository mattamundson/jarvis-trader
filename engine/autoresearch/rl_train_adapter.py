"""RL train adapter — bridges jarvis-trader RL metrics to n-autoresearch val_bpb format.

PLUMBING ONLY — reads rl_overrides.json, runs a minimal training stub, prints val_bpb line.
Not wired to RLTrainer yet (requires paper trading validation of composite_score).

Usage: python engine/autoresearch/rl_train_adapter.py [--baseline]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def load_overrides() -> dict:
    path = Path(__file__).parent / "rl_overrides.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception as e:
            logger.warning("Failed to load overrides: %s", e)
    return {}


def compute_baseline_val_bpb() -> float:
    """Placeholder: return negated best-known MES composite as baseline val_bpb."""
    # MES best: composite_score(5.27, 4.16, 0.82, 0.0179) = 0.8537
    return -0.8537


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", action="store_true", help="Use baseline metric without training")
    parser.add_argument("--timesteps", type=int, default=10000)
    args = parser.parse_args()

    overrides = load_overrides()
    if overrides:
        logger.info("Loaded overrides: %s", list(overrides.keys()))

    if args.baseline:
        val_bpb = compute_baseline_val_bpb()
    else:
        # TODO: wire to RLTrainer().train_walkforward() after paper validation
        val_bpb = compute_baseline_val_bpb()

    # n-autoresearch expects this exact line format on stdout
    print(f"val_bpb={val_bpb:.4f} peak_vram_gb=0.0 mfu=0.0 total_tokens={args.timesteps} param_count=1000000")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
