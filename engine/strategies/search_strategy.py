"""
JARVIS TRADER — Search Strategy Advisor
=========================================
Reads the experiment log and recommends the next experiment to run.

Decision logic (pure Python, no ML):

  EXPLORE   → any category has < 3 experiments
  EXPLOIT   → refine around the best-performing category
  COMBINE   → two near-miss experiments from different categories
  ABLATION  → no improvement in last 5 experiments

Usage::

    from strategies.search_strategy import suggest_next_experiment

    suggestion = suggest_next_experiment("MCL")
    print(suggestion["mode"])       # "explore" | "exploit" | "combine" | "ablation"
    print(suggestion["category"])   # e.g. "reward_shape"
    print(suggestion["rationale"])  # human-readable explanation
    print(suggestion["suggested_delta"])  # dict of suggested config changes

CLI::

    cd engine
    .venv/Scripts/python -m strategies.search_strategy --symbol MCL
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional

# ── Constants ─────────────────────────────────────────────────────────────────

ALL_CATEGORIES: list[str] = [
    "reward_shape",
    "episode_config",
    "signal_params",
    "regime_filter",
    "rl_hyperparams",
    "feature_engineering",
    "ablation",
    "combine",
]

EXPLORE_THRESHOLD: int = 3   # categories with fewer than this many runs → explore
STAGNATION_WINDOW: int = 5   # look back this many runs to detect stagnation


# ── Suggestion helpers ────────────────────────────────────────────────────────


def _suggest_explore(
    symbol: str,
    counts: dict[str, int],
) -> dict:
    """Pick the least-explored category."""
    candidate = min(
        (cat for cat in ALL_CATEGORIES if cat not in ("ablation", "combine")),
        key=lambda c: counts.get(c, 0),
    )
    n = counts.get(candidate, 0)
    return {
        "mode": "explore",
        "category": candidate,
        "rationale": (
            f"Category '{candidate}' has only {n} experiment(s) for {symbol.upper()}. "
            f"Explore phase: cover all categories before exploiting."
        ),
        "suggested_delta": _default_delta(candidate),
    }


def _suggest_exploit(
    symbol: str,
    best: dict,
    counts: dict[str, int],
) -> dict:
    """Suggest a tighter variation around the best-performing experiment."""
    best_cat = best.get("category", "reward_shape")
    best_delta = best.get("reward_config_delta", {})
    bm = best.get("metrics", {})

    # Suggest a 20% tighter version of the best delta
    tighter: dict = {}
    for k, v in best_delta.items():
        if isinstance(v, (int, float)):
            # Nudge: if negative (penalty), make slightly less negative; if positive, slightly higher
            tighter[k] = round(v * 1.1 if v < 0 else v * 0.9, 6)

    if not tighter:
        tighter = _default_delta(best_cat)

    return {
        "mode": "exploit",
        "category": best_cat,
        "rationale": (
            f"Best run ({best['run_id']}) is in '{best_cat}' "
            f"with score {best['composite_score']:.4f} "
            f"(WFE={bm.get('wfe', 0):.2f} PF={bm.get('pf', 0):.2f}). "
            f"Exploit: try a tighter variation around this config."
        ),
        "suggested_delta": tighter,
    }


def _suggest_combine(
    symbol: str,
    near_misses: list[dict],
) -> dict:
    """Combine two near-miss experiments from different categories."""
    # Find two near-misses from different categories
    pair: list[dict] = []
    seen_cats: set[str] = set()
    for nm in near_misses:
        cat = nm.get("category", "")
        if cat not in seen_cats:
            pair.append(nm)
            seen_cats.add(cat)
        if len(pair) == 2:
            break

    if len(pair) < 2:
        # Fall back to exploit
        return {
            "mode": "combine",
            "category": "combine",
            "rationale": "Near-misses found but from same category — combine not possible yet.",
            "suggested_delta": {},
        }

    # Merge deltas from both near-misses
    merged: dict = {}
    for nm in pair:
        merged.update(nm.get("reward_config_delta", {}))

    cat_names = " + ".join(p.get("category", "?") for p in pair)
    run_ids = " + ".join(p.get("run_id", "?") for p in pair)

    return {
        "mode": "combine",
        "category": "combine",
        "rationale": (
            f"Two near-miss experiments from different categories ({cat_names}) — "
            f"runs [{run_ids}]. Merge their config deltas to test combined effect."
        ),
        "suggested_delta": merged,
    }


def _suggest_ablation(
    symbol: str,
    best: Optional[dict],
) -> dict:
    """Suggest removing one reward component to check if it's load-bearing."""
    if best is None:
        best_delta: dict = {}
    else:
        best_delta = best.get("reward_config_delta", {})

    # Find the first non-zero key in best_delta to ablate
    ablate_key: Optional[str] = None
    ablate_val: float = 0.0
    for k, v in best_delta.items():
        if isinstance(v, (int, float)) and v != 0:
            ablate_key = k
            ablate_val = float(v)
            break

    if ablate_key:
        suggested: dict = {ablate_key: 0.0}
        rationale = (
            f"No improvement in last {STAGNATION_WINDOW} experiments. "
            f"Ablation: set {ablate_key}=0.0 (was {ablate_val}) to verify it's load-bearing."
        )
    else:
        suggested = {}
        rationale = (
            f"No improvement in last {STAGNATION_WINDOW} experiments. "
            f"Ablation: no obvious component to remove — try removing regime_filter."
        )
        suggested = {"regime_filter_weight": 0.0}

    return {
        "mode": "ablation",
        "category": "ablation",
        "rationale": rationale,
        "suggested_delta": suggested,
    }


def _default_delta(category: str) -> dict:
    """Provide a sensible default starting delta for each category."""
    defaults: dict[str, dict] = {
        "reward_shape": {"hold_cost": -0.008},
        "episode_config": {"max_bars_in_trade": 40},
        "signal_params": {"stc_oversold": 12},
        "regime_filter": {"min_layers_aligned": 4},
        "rl_hyperparams": {"learning_rate": 0.0002},
        "feature_engineering": {"add_vol_regime": True},
        "ablation": {},
        "combine": {},
    }
    return defaults.get(category, {})


# ── Core function ─────────────────────────────────────────────────────────────


def suggest_next_experiment(
    symbol: str,
    explore_threshold: int = EXPLORE_THRESHOLD,
    stagnation_window: int = STAGNATION_WINDOW,
) -> dict:
    """
    Recommend the next experiment category and mode for the given symbol.

    Returns
    -------
    dict with keys:
      mode             : "explore" | "exploit" | "combine" | "ablation"
      category         : one of the 8 experiment categories
      rationale        : human-readable explanation
      suggested_delta  : dict of suggested reward_config changes

    Decision priority:
      1. ABLATION  if no improvement in last `stagnation_window` runs
      2. COMBINE   if 2+ near-misses from different categories exist
      3. EXPLORE   if any non-ablation/combine category has < explore_threshold runs
      4. EXPLOIT   otherwise (refine around best)
    """
    from strategies.experiment_log import ExperimentLog

    log = ExperimentLog()
    all_records = log.list_all(symbol=symbol)  # newest-first
    best = log.get_best(symbol=symbol)
    near_misses = log.get_near_misses(symbol=symbol)
    counts = log.category_counts(symbol=symbol)

    # ── 1. Ablation — stagnation detection ───────────────────────────────
    if len(all_records) >= stagnation_window:
        recent = all_records[:stagnation_window]  # newest-first already
        best_recent_score = max(r.get("composite_score", -999.0) for r in recent)
        if best is not None and best_recent_score <= best.get("composite_score", 0.0):
            # No improvement in last N runs → ablation
            return _suggest_ablation(symbol=symbol, best=best)

    # ── 2. Combine — two near-misses from different categories ───────────
    near_miss_cats = {nm.get("category") for nm in near_misses}
    if len(near_miss_cats) >= 2:
        return _suggest_combine(symbol=symbol, near_misses=near_misses)

    # ── 3. Explore — under-explored categories ───────────────────────────
    under_explored = [
        cat
        for cat in ALL_CATEGORIES
        if cat not in ("ablation", "combine")
        and counts.get(cat, 0) < explore_threshold
    ]
    if under_explored:
        return _suggest_explore(symbol=symbol, counts=counts)

    # ── 4. Exploit — refine best ──────────────────────────────────────────
    if best is not None:
        return _suggest_exploit(symbol=symbol, best=best, counts=counts)

    # Fallback: explore first category
    return _suggest_explore(symbol=symbol, counts=counts)


# ── Printable summary ─────────────────────────────────────────────────────────


def print_suggestion(symbol: str) -> None:
    """Print a human-readable search strategy suggestion."""
    suggestion = suggest_next_experiment(symbol)

    from strategies.experiment_log import ExperimentLog

    log = ExperimentLog()
    counts = log.category_counts(symbol=symbol)
    total = sum(counts.values())
    best = log.get_best(symbol=symbol)

    print(f"\n{'='*60}")
    print(f"  SEARCH STRATEGY — {symbol.upper()}  ({total} total runs)")
    print(f"{'='*60}")
    print(f"  Mode      : {suggestion['mode'].upper()}")
    print(f"  Category  : {suggestion['category']}")
    print(f"  Rationale : {suggestion['rationale']}")
    if suggestion["suggested_delta"]:
        print(f"  Suggest Δ : {suggestion['suggested_delta']}")

    if best:
        bm = best["metrics"]
        print(f"\n  Current best: [{best['run_id']}] score={best['composite_score']:.4f}"
              f"  WFE={bm.get('wfe', 0):.2f}  PF={bm.get('pf', 0):.2f}")

    print(f"\n  Category coverage:")
    for cat in ALL_CATEGORIES:
        n = counts.get(cat, 0)
        status = "✓" if n >= EXPLORE_THRESHOLD else "·"
        bar = "█" * n
        print(f"    {status} {cat:<22} {bar} ({n})")

    print(f"\n  Run command:")
    delta_str = repr(suggestion["suggested_delta"]).replace("'", '"') if suggestion["suggested_delta"] else "{}"
    print(
        f"    python -m strategies.run_experiment "
        f"--symbol {symbol.upper()} "
        f"--category {suggestion['category']} "
        f"--hypothesis \"...\" "
        f"--config '{delta_str}'"
    )
    print()


# ── CLI ───────────────────────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="JARVIS search strategy advisor — recommends next experiment"
    )
    parser.add_argument("--symbol", required=True, help="Instrument symbol, e.g. MCL")
    args = parser.parse_args(argv)
    print_suggestion(args.symbol)
    return 0


if __name__ == "__main__":
    sys.exit(main())
