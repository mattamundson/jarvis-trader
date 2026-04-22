"""Search strategy for MES experiment parameter selection."""

from __future__ import annotations

import random
from typing import Any

from strategies.experiment_log import ExperimentLog


def _load_search_space(config_path: str) -> dict[str, list[Any]]:
    import json

    with open(config_path) as f:
        return json.load(f)


def select_next_config(
    log: ExperimentLog,
    config_path: str,
    seed: int | None = None,
) -> dict[str, Any]:
    """Select next parameter config using exploit/explore strategy."""
    rng = random.Random(seed)
    space = _load_search_space(config_path)
    records = log.all()

    if len(records) < 5:
        # Pure exploration: random sample covering the space
        return {k: rng.choice(v) for k, v in space.items()}

    # Exploit: 70% chance to sample near best config
    best = log.best_by_wfe()
    if best and rng.random() < 0.70:
        config: dict[str, Any] = {}
        for k, options in space.items():
            best_val = best.get("config_used", {}).get(k)
            if best_val in options:
                idx = options.index(best_val)
                # Sample +/-1 around best
                lo = max(0, idx - 1)
                hi = min(len(options) - 1, idx + 1)
                config[k] = options[rng.randint(lo, hi)]
            else:
                config[k] = rng.choice(options)
        return config

    # Explore: random
    return {k: rng.choice(v) for k, v in space.items()}
