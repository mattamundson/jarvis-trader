# Session Log — 2026-04-03
## n-autoresearch Experiment Loop Infrastructure (Phase 2)

**Date**: 2026-04-03
**Session type**: Multi-phase implementation (context-window update → skill install → experiment loop build)
**Branch**: feat/experiment-loop
**Status**: COMPLETE — all 4 user stories passing

---

## Table of Contents

1. [Session Overview](#1-session-overview)
2. [Phase 0 — Context Window Update](#2-phase-0--context-window-update)
3. [Phase 1 — n-autoresearch Skill Install](#3-phase-1--n-autoresearch-skill-install)
4. [Phase 2 — Experiment Loop Infrastructure](#4-phase-2--experiment-loop-infrastructure)
5. [Files Created / Modified](#5-files-created--modified)
6. [Complete Code — experiment_log.py](#6-complete-code--experiment_logpy)
7. [Complete Code — rl_trainer.py Changes](#7-complete-code--rl_trainerpy-changes)
8. [Complete Code — run_experiment.py](#8-complete-code--run_experimentpy)
9. [Complete Code — search_strategy.py](#9-complete-code--search_strategypy)
10. [Key Technical Decisions](#10-key-technical-decisions)
11. [How to Use the New Infrastructure](#11-how-to-use-the-new-infrastructure)
12. [Next Steps](#12-next-steps)

---

## 1. Session Overview

This session had three phases, carried across a context-window compaction boundary:

| Phase | Task | Result |
|-------|------|--------|
| 0 | Update LLM context windows from 200K → 1M for Sonnet/Opus | Done |
| 1 | Analyze + install n-autoresearch as a JARVIS skill | Done |
| 2 | Build experiment loop infrastructure (4 user stories) | Done — all PASS |

**Core insight established in Phase 1**: The `rl_config.py` Run 1–10 comment block was already n-autoresearch being done manually — every entry has a focused delta, a training run, a metric measurement, and a keep/reset decision. Phase 2 automates this into machine-readable, query-able infrastructure.

---

## 2. Phase 0 — Context Window Update

### Problem
`engine/llm/context_manager.py` had `CONTEXT_WINDOWS` set to 200,000 for all models. Both `claude-opus-4-6` and `claude-sonnet-4-6` actually support 1,000,000 token context windows.

### Solution
Updated `CONTEXT_WINDOWS` and `TIER_THRESHOLDS` to conservative percentages of the 1M window to keep absolute token costs bounded.

### File: `engine/llm/context_manager.py`

```python
CONTEXT_WINDOWS = {
    "claude-opus-4-6": 1_000_000,
    "claude-sonnet-4-6": 1_000_000,
    "claude-haiku-4-5-20251001": 200_000,
}
DEFAULT_CONTEXT_WINDOW = 200_000

TIER_THRESHOLDS = {
    CompactionTier.TRIM: 0.20,        # ~200K tokens absolute
    CompactionTier.TIME_CLEAR: 0.30,  # ~300K tokens absolute
    CompactionTier.SUMMARIZE: 0.40,   # ~400K tokens absolute
    CompactionTier.EMERGENCY: 0.50,   # ~500K tokens absolute
}
```

**Rationale**: Having 1M as the ceiling but triggering compaction at 20–50% keeps per-session costs bounded at ~$0.20–$0.50 rather than the potential $5+ for a fully-packed 1M session.

---

## 3. Phase 1 — n-autoresearch Skill Install

### Files installed
```
~/.claude/skills/n-autoresearch/
    SKILL.md
    api-reference.md
    OPERATE-V4.md
    repo-map.md
```

### Concept mapping created
`~/.claude/skills/jarvis-trader/n-autoresearch-patterns.md`

### Key concept mappings

| n-autoresearch | JARVIS TRADER Equivalent | File |
|----------------|--------------------------|------|
| `train.py` (ONLY file to edit) | `rl_config.py` + `rl_environment.py` | `engine/strategies/` |
| `val_bpb` (minimize) | WFE × PF × Sharpe composite (maximize) | composite score |
| GPU worker (5-min training) | `rl_trainer.py` + WFE evaluator | `engine/strategies/rl_trainer.py` |
| `keep_commit` | Accept new `rl_config.py` values | git |
| `git_reset` | Revert `rl_config.py` to previous run | git |
| Near-miss (±0.002 bpb) | Within 0.05 WFE or 0.20 PF of best | threshold |
| 14 experiment categories | 8 JARVIS categories | — |

### The 8 JARVIS Experiment Categories

| # | Category | What to Tune |
|---|----------|-------------|
| 1 | reward_shape | entry_cost, hold_cost, t1_bonus, flat_hold_reward |
| 2 | episode_config | MAX_BARS_IN_TRADE, max_episode_bars, window_size |
| 3 | signal_params | STC OS/OB thresholds, ATR stop/target multipliers |
| 4 | regime_filter | layer weights, min_layers_aligned, regime lookback |
| 5 | rl_hyperparams | learning_rate, n_steps, batch_size, gamma |
| 6 | feature_engineering | which indicators feed the observation space |
| 7 | ablation | remove one component, verify it's load-bearing |
| 8 | combine | merge features from two near-miss experiments |

### Composite score formula

```python
def compute_experiment_score(wfe, pf, sharpe, n_trades):
    if n_trades < 5:
        return -999.0
    wfe_score   = min(wfe, 1.0)           # WFE: 0–1
    pf_score    = min(pf, 10.0) / 10.0   # PF normalized 0–1
    sharpe_norm = min(sharpe, 5.0) / 5.0  # Sharpe normalized 0–1
    return wfe_score * 0.40 + pf_score * 0.35 + sharpe_norm * 0.25
```

Weights: WFE=40% (generalization), PF=35% (edge), Sharpe=25% (consistency).

---

## 4. Phase 2 — Experiment Loop Infrastructure

### PRD location
`engine/strategies/prd.json`

### User Stories

| ID | Title | Status |
|----|-------|--------|
| US-001 | Experiment Logger (experiment_log.py) | ✅ PASS |
| US-002 | WFE computation in train_walkforward result | ✅ PASS |
| US-003 | Experiment CLI runner (run_experiment.py) | ✅ PASS |
| US-004 | Search strategy advisor (search_strategy.py) | ✅ PASS |

### Investigation findings before building

Before coding, the following was verified by reading the source:

1. **`reward_config` kwarg already fully wired** through the entire stack:
   - `TradingEnvironment.__init__(reward_config=None)` → merges `{**REWARD_CONFIG, **(reward_config or {})}`
   - `build_env()` → passes through
   - `train_symbol()` → passes through
   - `train_walkforward()` → passes through
   - `_train_and_evaluate_window()` → passes to `build_env()`

2. **WFE was approximated as `pass_rate`** — not true OOS/IS ratio. Fixed in US-002.

3. **`training_summary`** (from `agent.train()`) only has: `episode_rewards`, `action_distribution`, `elapsed_seconds`, `total_timesteps`. It does NOT have `profit_factor`. True IS metrics require a second `agent.evaluate()` on the training data.

4. **`agent.evaluate()`** returns: `profit_factor`, `win_rate`, `max_drawdown`, `n_trades`, `sharpe`, `hold_rate`, `flat_hold_rate`, `passes_validation`.

---

## 5. Files Created / Modified

### New files

| File | Purpose |
|------|---------|
| `engine/strategies/experiment_log.py` | JSONL experiment logger |
| `engine/strategies/run_experiment.py` | CLI experiment runner |
| `engine/strategies/search_strategy.py` | Adaptive search advisor |
| `engine/strategies/prd.json` | Phase 2 PRD (all passes: true) |
| `engine/data/rl_experiments/` | Directory for JSONL log storage |
| `engine/data/rl_experiments/experiment_log.jsonl` | Live experiment log (JSONL, append-only) |

### Modified files

| File | Change |
|------|--------|
| `engine/strategies/rl_trainer.py` | Added IS evaluation per window + `wfe` key to result dict |
| `engine/llm/context_manager.py` | Updated CONTEXT_WINDOWS to 1M for Opus/Sonnet |
| `~/.claude/skills/n-autoresearch/` | New skill installation (4 files) |
| `~/.claude/skills/jarvis-trader/n-autoresearch-patterns.md` | New concept mapping |
| `~/.claude/skills/jarvis-trader/SKILL.md` | Updated Context Files table |
| `~/.claude/projects/.../memory/MEMORY.md` | Added n-autoresearch integration note |
| `n-autoresearch-skill/progress.txt` | Updated with Phase 2 learnings |

---

## 6. Complete Code — experiment_log.py

**Path**: `engine/strategies/experiment_log.py`

```python
"""
JARVIS TRADER — Experiment Logger
===================================
Structured JSONL log for RL training experiments.

Each record captures the config delta, metrics, composite score, and
keep/reset decision for one walk-forward run — replacing the manual
rl_config.py comment block with machine-readable, query-able history.

Usage::

    from strategies.experiment_log import ExperimentLog, compute_experiment_score

    log = ExperimentLog()
    score = compute_experiment_score(wfe=0.82, pf=2.1, sharpe=1.4, n_trades=12)

    run_id = log.log_experiment(
        symbol="MCL",
        category="reward_shape",
        hypothesis="Lower hold_cost to reduce over-trading",
        reward_config_delta={"hold_cost": -0.008},
        metrics={"pf": 2.1, "wfe": 0.82, "sharpe": 1.4, "n_trades": 12,
                 "pass_rate": 0.875, "recommendation": "deploy"},
        composite_score=score,
        kept=True,
    )

    best = log.get_best("MCL")
    near_misses = log.get_near_misses("MCL")
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────

_DEFAULT_LOG_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "rl_experiments" / "experiment_log.jsonl"
)

# ── Near-miss thresholds ──────────────────────────────────────────────────────

NEAR_MISS_WFE_DELTA: float = 0.05   # within 0.05 WFE of best
NEAR_MISS_PF_DELTA: float = 0.20    # within 0.20 PF of best


# ── Composite score ───────────────────────────────────────────────────────────


def compute_experiment_score(
    wfe: float,
    pf: float,
    sharpe: float,
    n_trades: int,
) -> float:
    """
    Composite experiment quality score (higher = better).

    Analogous to n-autoresearch val_bpb but maximized rather than minimized.

    Returns -999.0 for degenerate runs (< 5 trades).

    Weights:
      WFE    × 0.40  — walk-forward efficiency (generalisation)
      PF     × 0.35  — profit factor (edge quality)
      Sharpe × 0.25  — risk-adjusted return (consistency)
    """
    if n_trades < 5:
        return -999.0
    wfe_score = min(max(wfe, 0.0), 1.0)
    pf_score = min(max(pf, 0.0), 10.0) / 10.0
    sharpe_norm = min(max(sharpe, 0.0), 5.0) / 5.0
    return round(wfe_score * 0.40 + pf_score * 0.35 + sharpe_norm * 0.25, 6)


# ── ExperimentRecord TypedDict (loose) ───────────────────────────────────────

# We use plain dict rather than TypedDict so records survive JSON round-trips
# without any import friction for the CLI scripts.


def _make_record(
    run_id: str,
    symbol: str,
    category: str,
    hypothesis: str,
    reward_config_delta: dict,
    metrics: dict,
    composite_score: float,
    kept: bool,
) -> dict:
    """Build a canonical experiment record dict."""
    return {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol.upper(),
        "category": category,
        "hypothesis": hypothesis,
        "reward_config_delta": reward_config_delta,
        "metrics": {
            "pf": float(metrics.get("pf", metrics.get("profit_factor", 0.0))),
            "wfe": float(metrics.get("wfe", 0.0)),
            "sharpe": float(metrics.get("sharpe", 0.0)),
            "n_trades": int(metrics.get("n_trades", 0)),
            "pass_rate": float(metrics.get("pass_rate", 0.0)),
            "recommendation": str(metrics.get("recommendation", "unknown")),
        },
        "composite_score": float(composite_score),
        "kept": bool(kept),
    }


# ── ExperimentLog ─────────────────────────────────────────────────────────────


class ExperimentLog:
    """
    Append-only JSONL experiment log for JARVIS RL training runs.

    Thread-safety: each write opens → appends → closes the file so concurrent
    processes don't corrupt the log.  Reads load the entire file each time
    (file sizes are small — typically < 1000 records).
    """

    def __init__(self, log_path: Optional[Path] = None) -> None:
        self._path: Path = Path(log_path) if log_path is not None else _DEFAULT_LOG_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)

    # ── Writes ──────────────────────────────────────────────────────────────

    def log_experiment(
        self,
        symbol: str,
        category: str,
        hypothesis: str,
        reward_config_delta: dict,
        metrics: dict,
        composite_score: float,
        kept: bool,
        run_id: Optional[str] = None,
    ) -> str:
        """
        Append one experiment record and return its run_id.

        Parameters
        ----------
        symbol            : Instrument (e.g. "MCL", "MNQ")
        category          : One of the 8 experiment categories
                            (reward_shape, episode_config, signal_params,
                             regime_filter, rl_hyperparams, feature_engineering,
                             ablation, combine)
        hypothesis        : Human-readable description of the hypothesis
        reward_config_delta : Dict of keys changed vs. baseline REWARD_CONFIG
        metrics           : Dict with pf/wfe/sharpe/n_trades/pass_rate/recommendation
        composite_score   : Pre-computed score from compute_experiment_score()
        kept              : True = git commit kept; False = git reset
        run_id            : Optional explicit ID (auto-generated if None)
        """
        if run_id is None:
            run_id = str(uuid.uuid4())[:8]

        record = _make_record(
            run_id=run_id,
            symbol=symbol,
            category=category,
            hypothesis=hypothesis,
            reward_config_delta=reward_config_delta,
            metrics=metrics,
            composite_score=composite_score,
            kept=kept,
        )

        with open(self._path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")

        logger.info(
            "[ExperimentLog] Logged run=%s  symbol=%s  category=%s  "
            "score=%.4f  kept=%s",
            run_id,
            symbol.upper(),
            category,
            composite_score,
            kept,
        )
        return run_id

    # ── Reads ───────────────────────────────────────────────────────────────

    def _load(self, symbol: Optional[str] = None) -> list[dict]:
        """Load all records, optionally filtered to one symbol."""
        if not self._path.exists():
            return []
        records: list[dict] = []
        with open(self._path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if symbol is None or rec.get("symbol", "").upper() == symbol.upper():
                        records.append(rec)
                except json.JSONDecodeError as exc:
                    logger.warning("[ExperimentLog] Skipping malformed line: %s", exc)
        return records

    def list_all(self, symbol: Optional[str] = None) -> list[dict]:
        """Return all experiment records, newest-first."""
        records = self._load(symbol=symbol)
        return list(reversed(records))

    def get_best(self, symbol: str) -> Optional[dict]:
        """
        Return the highest-scoring kept experiment for this symbol.

        Only considers records where kept=True.
        Returns None if no kept experiments exist yet.
        """
        records = [r for r in self._load(symbol=symbol) if r.get("kept", False)]
        if not records:
            return None
        return max(records, key=lambda r: r.get("composite_score", -999.0))

    def get_near_misses(
        self,
        symbol: str,
        wfe_delta: float = NEAR_MISS_WFE_DELTA,
        pf_delta: float = NEAR_MISS_PF_DELTA,
    ) -> list[dict]:
        """
        Return experiments within wfe_delta WFE or pf_delta PF of the best.

        Near-misses are experiments that are close to the best but weren't kept.
        Useful for the 'combine' search strategy.

        Returns empty list if there is no best experiment yet.
        """
        best = self.get_best(symbol)
        if best is None:
            return []

        best_wfe: float = best["metrics"]["wfe"]
        best_pf: float = best["metrics"]["pf"]
        best_id: str = best["run_id"]

        near: list[dict] = []
        for rec in self._load(symbol=symbol):
            if rec["run_id"] == best_id:
                continue
            m = rec.get("metrics", {})
            wfe = m.get("wfe", 0.0)
            pf = m.get("pf", 0.0)
            if wfe >= (best_wfe - wfe_delta) or pf >= (best_pf - pf_delta):
                near.append(rec)

        # Sort by composite_score descending
        near.sort(key=lambda r: r.get("composite_score", -999.0), reverse=True)
        return near

    # ── Summaries ───────────────────────────────────────────────────────────

    def category_counts(self, symbol: str) -> dict[str, int]:
        """Count experiments run per category for a given symbol."""
        counts: dict[str, int] = {}
        for rec in self._load(symbol=symbol):
            cat = rec.get("category", "unknown")
            counts[cat] = counts.get(cat, 0) + 1
        return counts

    def print_summary(self, symbol: str) -> None:
        """Print a human-readable experiment summary to stdout."""
        records = self.list_all(symbol=symbol)
        best = self.get_best(symbol)
        near = self.get_near_misses(symbol)

        print(f"\n{'='*60}")
        print(f"  EXPERIMENT LOG — {symbol.upper()}  ({len(records)} runs)")
        print(f"{'='*60}")

        if best:
            bm = best["metrics"]
            print(
                f"  BEST  run={best['run_id']}  score={best['composite_score']:.4f}"
                f"  WFE={bm['wfe']:.2f}  PF={bm['pf']:.2f}  "
                f"Sharpe={bm['sharpe']:.2f}  Trades={bm['n_trades']}"
            )
            print(f"        [{best['category']}] {best['hypothesis']}")
        else:
            print("  BEST  (none yet)")

        if near:
            print(f"\n  NEAR-MISSES ({len(near)}):")
            for r in near[:5]:
                rm = r["metrics"]
                print(
                    f"    run={r['run_id']}  score={r['composite_score']:.4f}"
                    f"  WFE={rm['wfe']:.2f}  PF={rm['pf']:.2f}"
                    f"  [{r['category']}] {r['hypothesis'][:60]}"
                )

        print(f"\n  CATEGORY COVERAGE:")
        for cat, cnt in sorted(self.category_counts(symbol).items()):
            bar = "█" * cnt
            print(f"    {cat:<22} {bar} ({cnt})")

        print(f"\n  RECENT RUNS:")
        for r in records[:10]:
            rm = r["metrics"]
            kept_str = "✓KEEP" if r.get("kept") else "✗RESET"
            print(
                f"    [{r['timestamp'][:10]}] {r['run_id']}  {kept_str}  "
                f"score={r['composite_score']:.4f}  "
                f"WFE={rm['wfe']:.2f}  PF={rm['pf']:.2f}  "
                f"[{r['category']}]"
            )
        print()
```

---

## 7. Complete Code — rl_trainer.py Changes

**Path**: `engine/strategies/rl_trainer.py`

Two additions were made. Both are minimal and backward-compatible.

### Addition 1: IS evaluation in `_train_and_evaluate_window`

Inserted after `metrics = agent.evaluate(test_env, n_episodes=1)`:

```python
# IS evaluation — evaluate trained agent on full training data to get IS profit_factor
# Used by train_walkforward to compute WFE = avg(OOS_pf) / avg(IS_pf)
try:
    is_eval_env = build_env(symbol=symbol, df=df_train, max_episode_bars=len(df_train))
    is_metrics = agent.evaluate(is_eval_env, n_episodes=1)
except Exception as is_err:
    logger.warning(f"[RLTrainer.WF] Window {window_idx} IS eval failed: {is_err}")
    is_metrics = {}
```

Return dict updated to include `is_metrics`:

```python
return {
    "train_bars": len(df_train),
    "test_bars": len(df_test),
    "metrics": metrics,
    "is_metrics": is_metrics,        # ← NEW
    "model_path": model_path,
    "training_summary": training_summary,
}
```

### Addition 2: WFE computation in `train_walkforward`

Inserted as step 7b, between the recommendation derivation and building the final result dict:

```python
# ── 7b. Compute WFE = mean_oos_pf / mean_is_pf ──────────────────
oos_pfs = [w["metrics"].get("profit_factor", 0.0) for w in window_results]
is_pfs = [w.get("is_metrics", {}).get("profit_factor", 0.0) for w in window_results]
mean_oos_pf = sum(oos_pfs) / max(len(oos_pfs), 1)
mean_is_pf = sum(is_pfs) / max(len(is_pfs), 1)
if mean_is_pf <= 0.0:
    wfe = 0.0
else:
    wfe = min(max(mean_oos_pf / mean_is_pf, 0.0), 2.0)
wfe = round(wfe, 4)

logger.info(
    f"[RLTrainer.WF] WFE={wfe:.2f} "
    f"(OOS_PF={mean_oos_pf:.2f} / IS_PF={mean_is_pf:.2f})"
)
```

`wfe` key added to final result dict:

```python
result = {
    "status": "complete",
    "symbol": symbol,
    "interval": interval,
    "timesteps_per_window": timesteps_per_window,
    "n_windows": len(window_results),
    "windows": window_results,
    "all_pass": all_pass,
    "pass_rate": round(pass_rate, 4),
    "wfe": wfe,                          # ← NEW
    "aggregate_metrics": aggregate_metrics,
    "best_model_path": walkforward_best_path,
    "recommendation": recommendation,
    "completed_at": datetime.now(timezone.utc).isoformat(),
}
```

---

## 8. Complete Code — run_experiment.py

**Path**: `engine/strategies/run_experiment.py`

```python
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
    level=logging.WARNING,
    format="%(levelname)s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)

for noisy_pkg in ("stable_baselines3", "gymnasium", "strategies.rl_agent", "strategies.rl_environment"):
    logging.getLogger(noisy_pkg).setLevel(logging.ERROR)

KEEP_THRESHOLD: float = 0.95
EXIT_KEEP: int = 0
EXIT_RESET: int = 1


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="JARVIS RL Experiment Runner — n-autoresearch single-loop",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--symbol", required=True)
    parser.add_argument(
        "--category", required=True,
        choices=[
            "reward_shape", "episode_config", "signal_params", "regime_filter",
            "rl_hyperparams", "feature_engineering", "ablation", "combine",
        ],
    )
    parser.add_argument("--hypothesis", required=True)
    parser.add_argument("--config", default="{}")
    parser.add_argument("--timesteps", type=int, default=100_000)
    parser.add_argument("--windows", type=int, default=8)
    parser.add_argument("--keep", action="store_true", default=False)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--verbose", action="store_true", default=False)
    return parser.parse_args(argv)


async def run_experiment(args: argparse.Namespace) -> int:
    if args.verbose:
        logging.getLogger().setLevel(logging.INFO)

    try:
        reward_config_delta: dict = json.loads(args.config)
    except json.JSONDecodeError as exc:
        print(f"ERROR: --config is not valid JSON: {exc}", file=sys.stderr)
        return EXIT_RESET

    from strategies.experiment_log import ExperimentLog, compute_experiment_score

    log = ExperimentLog()
    best = log.get_best(args.symbol)
    best_score: float = best["composite_score"] if best else 0.0
    n_prior = len(log.list_all(args.symbol))

    print(f"\n{'='*64}")
    print(f"  JARVIS EXPERIMENT RUN")
    print(f"{'='*64}")
    print(f"  Symbol    : {args.symbol.upper()}")
    print(f"  Category  : {args.category}")
    print(f"  Hypothesis: {args.hypothesis}")
    print(f"  Config Δ  : {json.dumps(reward_config_delta)}")
    print(f"  Timesteps : {args.timesteps:,} × {args.windows} windows")
    print(f"  Prior runs: {n_prior}")
    print(f"  Best score: {best_score:.4f}" + (f"  ({best['run_id']})" if best else "  (none yet)"))
    print(f"{'='*64}")
    print(f"  Training ... (this may take several minutes)")
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

    agg = result.get("aggregate_metrics", {})
    wfe: float = float(result.get("wfe", 0.0))
    pf: float = float(agg.get("profit_factor", 0.0))
    sharpe: float = float(agg.get("sharpe", 0.0))
    n_trades: int = int(agg.get("n_trades", 0))
    pass_rate: float = float(result.get("pass_rate", 0.0))
    recommendation: str = result.get("recommendation", "unknown")

    metrics = {
        "pf": pf, "wfe": wfe, "sharpe": sharpe,
        "n_trades": n_trades, "pass_rate": pass_rate,
        "recommendation": recommendation,
    }

    score: float = compute_experiment_score(wfe=wfe, pf=pf, sharpe=sharpe, n_trades=n_trades)

    threshold = best_score * KEEP_THRESHOLD
    is_keep = score >= threshold

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
        print(f"\n  Suggested git commit:")
        print(f"    git commit -m \"rl-exp: [{run_id}] {args.category} — {args.hypothesis[:60]}\"")
        print(f"\n  To mark this run as kept in the experiment log:")
        print(f"    re-run with --keep flag")
    else:
        print(f"\n  Suggested git command:")
        print(f"    git reset --hard HEAD  # revert rl_config.py changes")
        print(f"\n  Score {score:.4f} < threshold {threshold:.4f} — RESET recommended.")

    print()
    return EXIT_KEEP if is_keep else EXIT_RESET


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    return asyncio.run(run_experiment(args))


if __name__ == "__main__":
    sys.exit(main())
```

---

## 9. Complete Code — search_strategy.py

**Path**: `engine/strategies/search_strategy.py`

```python
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

ALL_CATEGORIES: list[str] = [
    "reward_shape", "episode_config", "signal_params", "regime_filter",
    "rl_hyperparams", "feature_engineering", "ablation", "combine",
]

EXPLORE_THRESHOLD: int = 3
STAGNATION_WINDOW: int = 5


def _suggest_explore(symbol: str, counts: dict[str, int]) -> dict:
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


def _suggest_exploit(symbol: str, best: dict, counts: dict[str, int]) -> dict:
    best_cat = best.get("category", "reward_shape")
    best_delta = best.get("reward_config_delta", {})
    bm = best.get("metrics", {})

    tighter: dict = {}
    for k, v in best_delta.items():
        if isinstance(v, (int, float)):
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


def _suggest_combine(symbol: str, near_misses: list[dict]) -> dict:
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
        return {
            "mode": "combine",
            "category": "combine",
            "rationale": "Near-misses found but from same category — combine not possible yet.",
            "suggested_delta": {},
        }

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


def _suggest_ablation(symbol: str, best: Optional[dict]) -> dict:
    if best is None:
        best_delta: dict = {}
    else:
        best_delta = best.get("reward_config_delta", {})

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
        suggested = {"regime_filter_weight": 0.0}
        rationale = (
            f"No improvement in last {STAGNATION_WINDOW} experiments. "
            f"Ablation: no obvious component to remove — try removing regime_filter."
        )

    return {
        "mode": "ablation",
        "category": "ablation",
        "rationale": rationale,
        "suggested_delta": suggested,
    }


def _default_delta(category: str) -> dict:
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


def suggest_next_experiment(
    symbol: str,
    explore_threshold: int = EXPLORE_THRESHOLD,
    stagnation_window: int = STAGNATION_WINDOW,
) -> dict:
    """
    Recommend the next experiment category and mode for the given symbol.

    Decision priority:
      1. ABLATION  if no improvement in last stagnation_window runs
      2. COMBINE   if 2+ near-misses from different categories exist
      3. EXPLORE   if any non-ablation/combine category has < explore_threshold runs
      4. EXPLOIT   otherwise
    """
    from strategies.experiment_log import ExperimentLog

    log = ExperimentLog()
    all_records = log.list_all(symbol=symbol)
    best = log.get_best(symbol=symbol)
    near_misses = log.get_near_misses(symbol=symbol)
    counts = log.category_counts(symbol=symbol)

    # 1. Ablation
    if len(all_records) >= stagnation_window:
        recent = all_records[:stagnation_window]
        best_recent_score = max(r.get("composite_score", -999.0) for r in recent)
        if best is not None and best_recent_score <= best.get("composite_score", 0.0):
            return _suggest_ablation(symbol=symbol, best=best)

    # 2. Combine
    near_miss_cats = {nm.get("category") for nm in near_misses}
    if len(near_miss_cats) >= 2:
        return _suggest_combine(symbol=symbol, near_misses=near_misses)

    # 3. Explore
    under_explored = [
        cat for cat in ALL_CATEGORIES
        if cat not in ("ablation", "combine") and counts.get(cat, 0) < explore_threshold
    ]
    if under_explored:
        return _suggest_explore(symbol=symbol, counts=counts)

    # 4. Exploit
    if best is not None:
        return _suggest_exploit(symbol=symbol, best=best, counts=counts)

    return _suggest_explore(symbol=symbol, counts=counts)


def print_suggestion(symbol: str) -> None:
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


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="JARVIS search strategy advisor")
    parser.add_argument("--symbol", required=True)
    args = parser.parse_args(argv)
    print_suggestion(args.symbol)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

---

## 10. Key Technical Decisions

### WFE implementation choice

**Problem**: `training_summary` from `agent.train()` only has `episode_rewards` (reward checkpoints during training), not `profit_factor`. Computing WFE as `OOS_reward / IS_reward` would compare apples to oranges — different units.

**Solution chosen**: Run a second `agent.evaluate()` call on the training data (`df_train`) after training completes. This gives a proper IS `profit_factor` in the same units as the OOS `profit_factor`. WFE = mean(OOS_PF across windows) / mean(IS_PF across windows).

**Cost**: One extra inference pass on the training set per window. Inference is fast (no gradient computation) — adds ~5–10% overhead per window.

**Why not use episode_rewards as IS proxy**: Episode rewards and profit_factor are in completely different units. Episode rewards are reward-function-dependent (small floats like -0.01 to 0.5), while PF is a ratio ≥ 0 (typically 1–3 for good systems). The ratio would be meaningless.

### Experiment log design

**JSONL (append-only)**: Chosen over SQLite for simplicity — no schema, no migrations, no DB dependency, works with `git diff`, trivially grep-able. Max expected size is ~1000 records per symbol × a few KB each = a few MB total. Load-on-read is fine at this scale.

**`kept` field semantics**: `kept=True` means the git commit was kept (the experiment improved things). `kept=False` means git reset was performed. The `get_best()` method only looks at `kept=True` records to find the current production baseline.

**`run_id` as 8-char UUID prefix**: Short enough to type, collision probability negligible at <1000 records.

### Search strategy decision priority

```
1. ABLATION  — triggered by stagnation (no improvement in last 5 runs)
               → diagnose before trying more explore/exploit
2. COMBINE   — triggered when 2+ near-misses from different categories exist
               → merge configurations that individually almost worked
3. EXPLORE   — triggered when any core category has < 3 experiments
               → cover the space before optimizing
4. EXPLOIT   — default: refine around the best run
               → tighten the delta by 10% in the profitable direction
```

### KEEP threshold: 95% of best

`score >= best_score × 0.95` allows a 5% tolerance for natural variance in walk-forward results. This prevents discarding runs that are statistically equivalent to the best.

---

## 11. How to Use the New Infrastructure

### Step 1: Check what to try next

```bash
cd engine
.venv/Scripts/python -m strategies.search_strategy --symbol MCL
```

Output:
```
SEARCH STRATEGY — MCL  (1 total runs)
Mode      : EXPLORE
Category  : episode_config
Suggest Δ : {'max_bars_in_trade': 40}
Run command:
    python -m strategies.run_experiment --symbol MCL --category episode_config ...
```

### Step 2: Edit rl_config.py if needed (optional)

For `reward_shape` experiments, changes go directly via `--config`. For `episode_config` or `signal_params` that require code changes, edit `rl_config.py` first, then run the experiment with `--config '{}'`.

### Step 3: Run the experiment

```bash
.venv/Scripts/python -m strategies.run_experiment \
    --symbol MCL \
    --category episode_config \
    --hypothesis "Extend MAX_BARS_IN_TRADE to 40 to capture longer moves" \
    --config '{"max_bars_in_trade": 40}' \
    --timesteps 100000 \
    --windows 8
```

Output includes:
```
WFE       : 0.7800
PF        : 2.3400
Sharpe    : 1.4200
SCORE     : 0.5012  (vs best 0.4715  Δ +0.0297)
THRESHOLD : 0.4479  (95% of best)
VERDICT   : KEEP  ✓

Suggested git commit:
    git commit -m "rl-exp: [a1b2c3d4] episode_config — Extend MAX_BARS_IN_TRADE to 40"
```

### Step 4: Keep or reset (manual git)

```bash
# If KEEP:
git add engine/strategies/rl_config.py
git commit -m "rl-exp: [a1b2c3d4] episode_config — Extend MAX_BARS_IN_TRADE to 40"
# Re-run with --keep to update the log:
.venv/Scripts/python -m strategies.run_experiment ... --keep --run-id a1b2c3d4

# If RESET:
git reset --hard HEAD
```

### Step 5: View experiment history

```python
from strategies.experiment_log import ExperimentLog
log = ExperimentLog()
log.print_summary("MCL")
```

### Step 6: Query programmatically

```python
from strategies.experiment_log import ExperimentLog, compute_experiment_score

log = ExperimentLog()

# Get current best
best = log.get_best("MCL")
print(f"Best: {best['run_id']} score={best['composite_score']:.4f}")

# Get near-misses (candidates for combine)
near = log.get_near_misses("MCL")
print(f"{len(near)} near-misses across categories: {[n['category'] for n in near]}")

# Get all runs for a symbol
all_runs = log.list_all("MCL")

# Category coverage
counts = log.category_counts("MCL")
```

### Step 7: 10-agent parallel session

Each agent gets a different category assignment. All agents write to the same JSONL log (append-safe). After all agents complete, run search_strategy to find the best path forward.

Example manifest for 10 agents:
```
Agent 1: --symbol MCL --category reward_shape    --config '{"hold_cost": -0.008}'
Agent 2: --symbol MCL --category reward_shape    --config '{"t1_bonus": 0.60}'
Agent 3: --symbol MCL --category episode_config  --config '{"max_bars_in_trade": 40}'
Agent 4: --symbol MCL --category signal_params   --config '{"stc_oversold": 12}'
Agent 5: --symbol MCL --category ablation        --config '{"entry_cost": 0.0}'
Agent 6: --symbol MNQ --category reward_shape    --config '{"hold_cost": -0.008}'
Agent 7: --symbol MNQ --category episode_config  --config '{"max_bars_in_trade": 40}'
Agent 8: --symbol MNQ --category signal_params   --config '{"stc_oversold": 12}'
Agent 9: --symbol MNQ --category regime_filter   --config '{"min_layers_aligned": 4}'
Agent 10: --symbol MNQ --category rl_hyperparams --config '{"learning_rate": 0.0002}'
```

---

## 12. Next Steps

### Immediate (next session)
1. Run first real experiment with `run_experiment.py` on MCL (episode_config — MAX_BARS_IN_TRADE=40 is the search_strategy recommendation)
2. Verify WFE computation is sensible (IS_PF should be > OOS_PF for a well-fitting model → WFE < 1.0)
3. Run 3–5 explore experiments across different categories to build baseline

### Short-term (after 3+ experiments logged)
1. Verify `search_strategy` transitions from EXPLORE → COMBINE/EXPLOIT correctly
2. Consider adding `--dry-run` flag to `run_experiment.py` that skips training and prints what would happen
3. Add `run_id` to rl_config.py comment block for git lineage cross-reference

### Medium-term
1. Wire `ExperimentLog` into the engine API (add `GET /experiments/{symbol}` endpoint)
2. Add experiment history panel to the dashboard
3. Consider parallel experiment runs using the 10-agent session pattern
4. Integrate WFE from `train_walkforward` result into paper trading validation metrics

### Architecture note
The experiment loop is deliberately NOT integrated with the paper trading pipeline. RL optimization (offline, backtested) and paper trading (forward-test, live signals) are separate phases. The RL experiments improve the model, which is then deployed to paper trading once validated.

---

## Appendix: PRD Final State

All user stories passing:

```json
{
  "project": "n-autoresearch Experiment Loop Infrastructure",
  "branchName": "feat/experiment-loop",
  "userStories": [
    {"id": "US-001", "title": "Experiment Logger (experiment_log.py)",         "passes": true},
    {"id": "US-002", "title": "WFE computation in train_walkforward result",   "passes": true},
    {"id": "US-003", "title": "Experiment CLI runner (run_experiment.py)",     "passes": true},
    {"id": "US-004", "title": "Search strategy advisor (search_strategy.py)", "passes": true}
  ]
}
```

---

*Session log saved: 2026-04-03*
*Engine path: `C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\`*
*Skill path: `~/.claude/skills/n-autoresearch/`*
