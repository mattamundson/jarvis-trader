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
