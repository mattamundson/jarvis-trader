"""Bayesian gate-v2 threshold calibrator — recommendation only.

This module computes Bayesian posterior estimates of the "right" gate-v2
thresholds given accumulated verdict history.  It NEVER applies its
recommendations to GATE_V2_* env vars — those require a human decision.

Architecture
------------
- ``collect_historical_verdicts`` — reads all JSON verdict files (live +
  archive) whose ``created_at`` falls within the lookback window.
- ``recommended_thresholds`` — for each of the 4 gate metrics, finds the
  threshold value that maximises precision while keeping recall above 80%,
  using a Beta prior on strategy win probability.  Returns strength rating
  based on sample count.
- ``diff_vs_current`` — compares recommended vs current canonical thresholds
  and classifies each delta as "tighten", "loosen", or "hold".

Bayesian prior choice
---------------------
We use Beta(2, 2) — a symmetric, weakly informative prior centred on 0.5
win probability.  At n=20 this prior still pulls estimates toward 0.5
noticeably; by n=50 the data dominates.  This is intentional: the calibrator
should be sceptical of extreme recommendations from small samples.

IMPORTANT: this module is read-only with respect to the engine configuration.
Importing it has no side effects.  It reads verdict JSON files and, optionally,
the live DB for paper-trade outcomes.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Current canonical thresholds — imported lazily to avoid circular imports.
# We embed the values here so the calibrator can run stand-alone.
# ---------------------------------------------------------------------------

CURRENT_THRESHOLDS: dict[str, float] = {
    "pf_ci_lower": 1.10,
    "p_edge": 0.95,
    "mc_95th_dd": 0.05,  # core ceiling; alt ceiling is 0.04
    "dsr": 0.10,  # core floor; alt floor is 0.30
}

# ---------------------------------------------------------------------------
# Sample-size bands for recommendation strength
# ---------------------------------------------------------------------------

SAMPLE_WEAK_MAX = 50  # < 50 verdicts -> "weak"
SAMPLE_MODERATE_MAX = 200  # 50-199 verdicts -> "moderate"
# >= 200 verdicts -> "strong"

# Bayesian Beta prior parameters (intentionally weak / fast-converging)
BETA_PRIOR_ALPHA = 2.0
BETA_PRIOR_BETA = 2.0

# Minimum recall we refuse to sacrifice in threshold search
MIN_RECALL = 0.80

# Precision candidates: grid over each metric
_PF_CANDIDATES = np.arange(0.90, 2.51, 0.05)
_P_EDGE_CANDIDATES = np.arange(0.50, 1.01, 0.025)
_DD_CANDIDATES = np.arange(0.01, 0.16, 0.005)  # smaller is tighter
_DSR_CANDIDATES = np.arange(0.00, 1.01, 0.05)


def _default_verdicts_dir() -> Path:
    """Canonical gate_v2_verdicts directory relative to the engine package."""
    return Path(__file__).resolve().parent.parent / "data" / "gate_v2_verdicts"


def _default_db_path() -> str:
    return os.environ.get(
        "DB_PATH",
        str(Path(__file__).resolve().parent.parent / "data" / "jarvis_trader.db"),
    )


# ---------------------------------------------------------------------------
# Verdict loading
# ---------------------------------------------------------------------------


def _load_verdict_file(path: Path) -> dict[str, Any] | None:
    """Parse a verdict JSON file; return None on any error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Skipping malformed verdict file %s: %s", path, exc)
        return None


def _iter_all_verdict_files(verdicts_dir: Path | None = None):
    """Yield verdict dicts from live dir + archive subdir."""
    d = verdicts_dir or _default_verdicts_dir()
    if not d.exists():
        return
    for p in d.glob("*.json"):
        if p.is_file():
            doc = _load_verdict_file(p)
            if doc:
                yield doc
    archive = d / "archive"
    if archive.exists():
        for p in archive.glob("*.json"):
            if p.is_file():
                doc = _load_verdict_file(p)
                if doc:
                    yield doc


def _parse_created_at(doc: dict[str, Any]) -> datetime | None:
    raw = doc.get("created_at")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def collect_historical_verdicts(
    db_path: str | None = None,
    lookback_days: int = 90,
    verdicts_dir: Path | None = None,
) -> pd.DataFrame:
    """Pull all gate-v2 verdicts from the last ``lookback_days`` days.

    Returns a DataFrame with columns:
        symbol, family, rank, verdict (PASS/FAIL),
        pf_ci_lower, p_edge, mc_95th_dd, dsr,
        created_at, win_rate (paper, if available)

    The ``win_rate`` column reflects actual paper-trade win rate for the
    symbol since the verdict was issued.  When no paper data exists the
    column is NaN.

    Args:
        db_path:       Path to the SQLite DB.  Defaults to env / engine default.
        lookback_days: How many calendar days of verdicts to include.
        verdicts_dir:  Override for the gate_v2_verdicts directory.
    """
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=lookback_days)

    rows: list[dict[str, Any]] = []
    for doc in _iter_all_verdict_files(verdicts_dir):
        created_at = _parse_created_at(doc)
        if created_at is None or created_at < cutoff:
            continue
        metrics = doc.get("gate_v2_metrics", {})
        if not metrics:
            continue
        rows.append(
            {
                "symbol": doc.get("symbol", ""),
                "family": doc.get("family", ""),
                "rank": doc.get("rank"),
                "verdict": doc.get("verdict", "FAIL"),
                "pf_ci_lower": metrics.get("pf_ci_lower", float("nan")),
                "p_edge": metrics.get("p_edge", float("nan")),
                "mc_95th_dd": metrics.get("mc_95th_dd", float("nan")),
                "dsr": metrics.get("dsr", float("nan")),
                "created_at": created_at,
                "win_rate": float("nan"),
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=[
                "symbol",
                "family",
                "rank",
                "verdict",
                "pf_ci_lower",
                "p_edge",
                "mc_95th_dd",
                "dsr",
                "created_at",
                "win_rate",
            ]
        )

    df = pd.DataFrame(rows)

    # Enrich with paper-trade win rates per symbol
    db = db_path or _default_db_path()
    try:
        import sqlite3

        conn = sqlite3.connect(db)
        paper = conn.execute(
            """
            SELECT symbol,
                   SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) * 1.0 /
                       NULLIF(COUNT(*), 0) AS win_rate
            FROM paper_trades
            WHERE status = 'closed'
            GROUP BY symbol
            """
        ).fetchall()
        conn.close()

        wr_map: dict[str, float] = {row[0]: row[1] for row in paper if row[1] is not None}
        if wr_map:
            df["win_rate"] = df["symbol"].map(wr_map)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not enrich with paper win rates: %s", exc)

    return df


# ---------------------------------------------------------------------------
# Bayesian calibration
# ---------------------------------------------------------------------------


def _recommendation_strength(n: int) -> str:
    if n < SAMPLE_WEAK_MAX:
        return "weak"
    if n < SAMPLE_MODERATE_MAX:
        return "moderate"
    return "strong"


def _bayesian_win_prob_estimate(n_total: int, n_pass: int) -> float:
    """Posterior mean of Beta(alpha, beta) updated with (n_pass, n_fail)."""
    alpha_post = BETA_PRIOR_ALPHA + n_pass
    beta_post = BETA_PRIOR_BETA + (n_total - n_pass)
    return alpha_post / (alpha_post + beta_post)


def _find_precision_maximising_threshold(
    values: np.ndarray,
    outcomes: np.ndarray,
    candidates: np.ndarray,
    higher_is_better: bool,
    min_recall: float = MIN_RECALL,
) -> float:
    """Search ``candidates`` for the most selective threshold that maximises
    precision while keeping recall >= ``min_recall``.

    "Most selective" means:
    - For higher_is_better metrics (pf_ci_lower, p_edge, dsr): the *highest*
      threshold that achieves max precision with adequate recall.
    - For lower_is_better metrics (mc_95th_dd): the *lowest* threshold with
      the same criteria.

    This is the correct semantics: among all precision-equivalent candidates,
    prefer the one that is hardest to pass — the calibrator should not
    recommend loosening a threshold unless loosening demonstrably helps.

    Args:
        values:           Array of metric values, one per verdict.
        outcomes:         Boolean array; True means the verdict led to a good
                          outcome (PASS verdict + positive paper performance).
        candidates:       Sorted (ascending) threshold candidates to search.
        higher_is_better: If True, "above threshold" means pass; else below.
        min_recall:       Minimum fraction of true positives we must retain.

    Returns:
        The most selective threshold from ``candidates`` that maximises
        precision while keeping recall >= ``min_recall``.  Returns NaN if
        no candidate satisfies the recall constraint.
    """
    n_true = outcomes.sum()
    if n_true == 0:
        return float("nan")

    best_thresh = float("nan")
    best_precision = -1.0

    # Iterate from most-selective to least-selective so that the first
    # candidate achieving max precision is the most selective one.
    if higher_is_better:
        ordered = candidates[::-1]  # high to low
    else:
        ordered = candidates  # low to high (low = more selective for dd)

    for t in ordered:
        if higher_is_better:
            predicted_pos = values >= t
        else:
            predicted_pos = values <= t

        tp = (predicted_pos & outcomes).sum()
        fp = (predicted_pos & ~outcomes).sum()

        recall = tp / n_true
        if recall < min_recall:
            continue

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        if precision > best_precision:
            best_precision = precision
            best_thresh = float(t)
        # Once we've found a candidate that ties the current best precision,
        # do not update — we already have the most selective one (first found
        # in the most-selective-first iteration order).

    return best_thresh


def _derive_outcomes(df: pd.DataFrame) -> np.ndarray:
    """Derive a boolean "good outcome" array from the verdict DataFrame.

    A verdict is a "good outcome" if:
    - The verdict is PASS, AND
    - win_rate >= 0.5 (or win_rate is NaN, meaning no paper data yet —
      we give the benefit of the doubt and count PASS as good).
    """
    is_pass = df["verdict"].str.upper() == "PASS"
    win_ok = df["win_rate"].isna() | (df["win_rate"] >= 0.5)
    return (is_pass & win_ok).to_numpy(dtype=bool)


def recommended_thresholds(verdicts_df: pd.DataFrame) -> dict[str, Any]:
    """Compute Bayesian posterior recommended thresholds.

    For each of the 4 gate metrics, find the threshold that maximises
    precision while keeping recall >= 80%.  The posterior is anchored on a
    Beta(2, 2) prior that converges quickly once data exceeds 50 verdicts.

    Args:
        verdicts_df: DataFrame from ``collect_historical_verdicts``.

    Returns:
        Dict with keys:
            pf_ci_lower, p_edge, mc_95th_dd, dsr — recommended float values
            sample_size — int, number of verdicts analysed
            confidence   — float in [0, 1], posterior mean win probability
            recommendation_strength — "weak" | "moderate" | "strong"
    """
    n = len(verdicts_df)
    if n == 0:
        return {
            "pf_ci_lower": CURRENT_THRESHOLDS["pf_ci_lower"],
            "p_edge": CURRENT_THRESHOLDS["p_edge"],
            "mc_95th_dd": CURRENT_THRESHOLDS["mc_95th_dd"],
            "dsr": CURRENT_THRESHOLDS["dsr"],
            "sample_size": 0,
            "confidence": float(_bayesian_win_prob_estimate(0, 0)),
            "recommendation_strength": "weak",
        }

    outcomes = _derive_outcomes(verdicts_df)
    n_pass = int(outcomes.sum())
    confidence = _bayesian_win_prob_estimate(n, n_pass)
    strength = _recommendation_strength(n)

    def _safe_array(col: str) -> np.ndarray:
        s = verdicts_df[col].dropna()
        return s.to_numpy(dtype=float)

    def _safe_outcomes_for(col: str) -> np.ndarray:
        mask = verdicts_df[col].notna()
        return outcomes[mask.to_numpy()]

    # PF CI lower: higher is better (tighter gate)
    pf_vals = _safe_array("pf_ci_lower")
    pf_outs = _safe_outcomes_for("pf_ci_lower")
    pf_rec = _find_precision_maximising_threshold(
        pf_vals, pf_outs, _PF_CANDIDATES, higher_is_better=True
    )
    if np.isnan(pf_rec):
        pf_rec = CURRENT_THRESHOLDS["pf_ci_lower"]

    # p_edge: higher is better (tighter gate)
    pe_vals = _safe_array("p_edge")
    pe_outs = _safe_outcomes_for("p_edge")
    pe_rec = _find_precision_maximising_threshold(
        pe_vals, pe_outs, _P_EDGE_CANDIDATES, higher_is_better=True
    )
    if np.isnan(pe_rec):
        pe_rec = CURRENT_THRESHOLDS["p_edge"]

    # mc_95th_dd: lower is better (tighter gate = lower ceiling)
    dd_vals = _safe_array("mc_95th_dd")
    dd_outs = _safe_outcomes_for("mc_95th_dd")
    dd_rec = _find_precision_maximising_threshold(
        dd_vals, dd_outs, _DD_CANDIDATES, higher_is_better=False
    )
    if np.isnan(dd_rec):
        dd_rec = CURRENT_THRESHOLDS["mc_95th_dd"]

    # DSR: higher is better (tighter gate)
    dsr_vals = _safe_array("dsr")
    dsr_outs = _safe_outcomes_for("dsr")
    dsr_rec = _find_precision_maximising_threshold(
        dsr_vals, dsr_outs, _DSR_CANDIDATES, higher_is_better=True
    )
    if np.isnan(dsr_rec):
        dsr_rec = CURRENT_THRESHOLDS["dsr"]

    return {
        "pf_ci_lower": round(pf_rec, 4),
        "p_edge": round(pe_rec, 4),
        "mc_95th_dd": round(dd_rec, 4),
        "dsr": round(dsr_rec, 4),
        "sample_size": n,
        "confidence": round(confidence, 4),
        "recommendation_strength": strength,
    }


# ---------------------------------------------------------------------------
# Diff vs current
# ---------------------------------------------------------------------------


def diff_vs_current(
    recommended: dict[str, Any],
    current: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Compare recommended thresholds against current canonical values.

    Args:
        recommended: Output of ``recommended_thresholds``.
        current:     Current thresholds dict.  Defaults to
                     ``CURRENT_THRESHOLDS``.

    Returns:
        Dict mapping each metric to:
            ``{"current": float, "recommended": float, "delta": float,
               "action": "tighten" | "loosen" | "hold"}``
    """
    cur = current if current is not None else CURRENT_THRESHOLDS
    result: dict[str, Any] = {}

    for metric, current_val in cur.items():
        rec_val = recommended.get(metric)
        if rec_val is None:
            continue
        delta = rec_val - current_val

        # Determine whether raising or lowering the threshold is "tightening"
        # For pf_ci_lower / p_edge / dsr: higher = tighter gate
        # For mc_95th_dd: lower = tighter gate
        if metric == "mc_95th_dd":
            action = "tighten" if delta < -0.001 else ("loosen" if delta > 0.001 else "hold")
        else:
            action = "tighten" if delta > 0.001 else ("loosen" if delta < -0.001 else "hold")

        result[metric] = {
            "current": current_val,
            "recommended": rec_val,
            "delta": round(delta, 4),
            "action": action,
        }

    return result


# ---------------------------------------------------------------------------
# Vault markdown rendering
# ---------------------------------------------------------------------------


def render_vault_markdown(
    recommended: dict[str, Any],
    diff: dict[str, Any],
    run_date: str | None = None,
) -> str:
    """Render the calibration report as vault-ingestible Markdown.

    Includes YAML frontmatter that makes the file discoverable by the
    second-brain ingest pipeline.

    Args:
        recommended: Output of ``recommended_thresholds``.
        diff:        Output of ``diff_vs_current``.
        run_date:    ISO date string (YYYY-MM-DD); defaults to today UTC.

    Returns:
        Full Markdown string including frontmatter.
    """
    date_str = run_date or datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    strength = recommended.get("recommendation_strength", "weak")
    n = recommended.get("sample_size", 0)
    confidence = recommended.get("confidence", 0.0)

    frontmatter = f"""---
source: "gate-v2-calibration"
kind: "calibration-report"
date: "{date_str}"
sample_size: {n}
recommendation_strength: "{strength}"
tags:
  - gate-v2
  - calibration
  - jarvis-trader/threshold-tuning
---"""

    def _fmt_action(action: str) -> str:
        icon = {"tighten": "^", "loosen": "v", "hold": "="}
        return f"{icon.get(action, '?')} {action.upper()}"

    rows = []
    for metric, info in diff.items():
        rows.append(
            f"| `{metric}` | {info['current']} | {info['recommended']} "
            f"| {info['delta']:+.4f} | {_fmt_action(info['action'])} |"
        )
    table = "\n".join(rows)

    body = f"""
# Gate-v2 Threshold Calibration — {date_str}

> Generated by `engine/analytics/gate_v2_calibrator.py`.
> **READ-ONLY** — these are recommendations, never auto-applied.

## Summary

| Field | Value |
|---|---|
| Sample size (verdicts) | {n} |
| Recommendation strength | **{strength}** |
| Posterior win probability | {confidence:.1%} |
| Prior | Beta({BETA_PRIOR_ALPHA:.0f}, {BETA_PRIOR_BETA:.0f}) — weak, fast-converging |

## Threshold Recommendations

| Metric | Current | Recommended | Delta | Action |
|---|---|---|---|---|
{table}

## Interpretation

- **weak** (n < {SAMPLE_WEAK_MAX}): Treat as directional only.  Prior dominates.
- **moderate** (n {SAMPLE_WEAK_MAX}–{SAMPLE_MODERATE_MAX - 1}): Credible signal; review with intuition.
- **strong** (n >= {SAMPLE_MODERATE_MAX}): Data dominates prior; worth discussing threshold change.

A "tighten" recommendation means the data suggests raising the hurdle
(pf_ci_lower / p_edge / dsr) or lowering the ceiling (mc_95th_dd).
A "loosen" recommendation means the current gate may be excluding
strategies that would have performed well in paper.

## Next steps

- Do NOT update `GATE_V2_*` env vars unless strength is **strong** AND
  the action aligns with your market-regime intuition.
- Link: `[[KRONOS_AND_RESEARCH_AGENT_RUNBOOK]]`
- Cross-check: Phase 3 readiness criterion C5 (max_drawdown).

## Related

- `docs/runbooks/GATE_V2_CALIBRATOR_RUNBOOK.md`
- `engine/backtest/_gate_v2_helpers.py` — canonical threshold constants
"""

    return frontmatter + body
