"""Shared gate v2 metric helpers — single source of truth for runner files.

Gate v2 threshold constants
----------------------------
Import these into runner files instead of re-defining them locally:

    from backtest._gate_v2_helpers import (
        GATE_PF_CI_LOWER, GATE_P_EDGE, GATE_MC_DD_CORE, GATE_MC_DD_ALT,
        GATE_DSR, GATE_DSR_ALT, N_BOOTSTRAP,
        # WFO window defaults
        WFO_TRAIN_MONTHS, WFO_TEST_MONTHS, WFO_STEP_MONTHS,
        MIN_OOS_TRADES_PER_WINDOW,
        # Cost sweep tiers
        COST_SWEEP_TIERS, COST_TIER_ORDER,
    )

Any future change to a threshold is a single-line edit here; no runner
files need to change.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Gate v2 threshold constants — canonical values; do not redefine per-runner
# ---------------------------------------------------------------------------

#: Bootstrap 5th-percentile OOS PF lower bound (CORE and ALT paths).
GATE_PF_CI_LOWER: float = 1.10

#: Fraction of OOS windows with PF > 1.0 required for edge confirmation.
GATE_P_EDGE: float = 0.95

#: 95th-percentile OOS max-drawdown ceiling — CORE path.
GATE_MC_DD_CORE: float = 0.05

#: 95th-percentile OOS max-drawdown ceiling — ALT path ($50K+ accounts).
GATE_MC_DD_ALT: float = 0.07

#: Deflated Sharpe ratio floor — CORE path.
GATE_DSR: float = 0.10

#: Deflated Sharpe ratio floor — ALT path (trend strategies on daily bars).
GATE_DSR_ALT: float = 0.30

#: Bootstrap sample count for PF CI estimation.
N_BOOTSTRAP: int = 2000

# ---------------------------------------------------------------------------
# Walk-forward optimisation window defaults — canonical; do not redefine
# ---------------------------------------------------------------------------

#: In-sample training window length in calendar months.
WFO_TRAIN_MONTHS: int = 6

#: Out-of-sample test window length in calendar months.
WFO_TEST_MONTHS: int = 1

#: Roll-forward step size in calendar months.
WFO_STEP_MONTHS: int = 1

#: Minimum OOS trades required for a window to count toward gate v2.
MIN_OOS_TRADES_PER_WINDOW: int = 5

# ---------------------------------------------------------------------------
# Cost sweep tiers — canonical; do not redefine per-runner
# ---------------------------------------------------------------------------

#: Four-tier cost grid for ORB-family runners (MES/M2K).
#: Trend runners use higher slippage assumptions and define COST_SWEEP_TIERS locally.
#: Keys: commission per side (USD) and slippage in ticks.
COST_SWEEP_TIERS: dict[str, dict[str, float]] = {
    "optimistic": {"commission": 0.31, "slippage_ticks": 1.0},
    "realistic": {"commission": 0.62, "slippage_ticks": 1.0},
    "pessimistic": {"commission": 1.24, "slippage_ticks": 2.0},
    "catastrophic": {"commission": 2.48, "slippage_ticks": 3.0},
}

#: Ordered tier names from best to worst — used for threshold checking.
COST_TIER_ORDER: list[str] = ["optimistic", "realistic", "pessimistic", "catastrophic"]


def _find_latest_cache(data_dir: Path, prefix: str, suffix: str = "_1h.csv") -> Path:
    """Pick the cache file whose filename's second date segment is the latest.

    Filename contract (LOAD-BEARING — see ``export_ibkr_history.py``
    ``CACHE_FILENAME_CONTRACT`` for the canonical regex):

        ``<PREFIX>_<START_DATE>_<END_DATE><SUFFIX>``

    where ``<START_DATE>`` and ``<END_DATE>`` are ISO ``YYYY-MM-DD`` strings.
    Lexicographic max on the second underscore-split segment (``parts[2]``,
    the end-date) is equivalent to chronological max because ISO dates sort
    correctly as strings. ``parts[0]`` is the prefix, ``parts[1]`` is the
    start-date, ``parts[2]`` is the end-date — the sort key.

    A refreshed IBKR pull (e.g. ``MES_2024-01-01_2026-05-07_1h.csv``) will
    therefore always win over an older copy (e.g.
    ``MES_2024-01-01_2026-03-28_1h.csv``). Centralizes the bug-class fix from
    commit 55739db so future runners (MES, MGC, MNQ, MCL, M2K, ...) cannot
    silently revert to a hardcoded path.

    Contract drift policy: filenames matching the glob ``<prefix>*<suffix>``
    but violating the underscore-split contract (fewer than 3 segments) sort
    to the empty string and end up at the bottom of the lex order, so they
    never beat a contract-conforming sibling. They will only be selected if
    no conforming file exists, in which case the helper falls back to the
    glob-sort tail and a warning is logged. The companion runtime assertion
    in ``export_ibkr_history._save_merged`` is the canary that prevents new
    drift from entering the cache directory.

    Args:
        data_dir: Directory to search (typically ``engine/backtest/cache/``).
        prefix:   Symbol or family prefix (e.g. ``"MES"``, ``"MGC"``).
        suffix:   Filename suffix including interval (default ``"_1h.csv"``).

    Returns:
        The :class:`Path` of the latest-end-date matching file.

    Raises:
        FileNotFoundError: If no files match ``<prefix>*<suffix>`` in ``data_dir``.
    """
    import logging

    candidates = sorted(data_dir.glob(f"{prefix}*{suffix}"))
    if not candidates:
        raise FileNotFoundError(
            f"No {prefix} {suffix.lstrip('_').rstrip('.csv')} data found in "
            f"{data_dir} (looked for '{prefix}*{suffix}')"
        )

    def _end_date(p: Path) -> str:
        # Filename: <PREFIX>_YYYY-MM-DD_YYYY-MM-DD<SUFFIX> -> the second date.
        # Off-contract files have <3 parts and return "" (sort to the bottom).
        parts = p.stem.split("_")
        return parts[2] if len(parts) >= 3 else ""

    # Surface contract-violating files so drift is visible in logs.
    off_contract = [p for p in candidates if not _end_date(p)]
    if off_contract:
        logging.getLogger(__name__).warning(
            "Cache filename contract drift detected in %s: %s "
            "(expected '<PREFIX>_<YYYY-MM-DD>_<YYYY-MM-DD>%s')",
            data_dir,
            [p.name for p in off_contract],
            suffix,
        )

    return max(candidates, key=_end_date)


def bootstrap_pf_ci_lower(oos_pfs: list[float], n: int = 5000) -> float:
    """Bootstrap 5th-percentile of mean PF distribution; inf-cap baked in."""
    # Cap inf/-inf before bootstrapping — np.percentile returns NaN via inf-inf interpolation
    capped = [
        (
            min(max(pf, 0.0), 5.0)
            if not (pf == float("inf") or pf == float("-inf"))
            else (5.0 if pf == float("inf") else 0.0)
        )
        for pf in oos_pfs
    ]
    if len(capped) < 2:
        return float(np.mean(capped)) if capped else 0.0
    rng = np.random.default_rng(42)
    arr = np.array(capped, dtype=float)
    boot_means = [rng.choice(arr, size=len(arr), replace=True).mean() for _ in range(n)]
    return float(np.percentile(boot_means, 5.0))


def classify_wfo_consistency(oos_pfs: list[float]) -> str:
    """Classify WFO consistency: STRONG >= 75% profitable windows, MODERATE >= 55%."""
    if not oos_pfs:
        return "WEAK"
    pct = sum(1 for pf in oos_pfs if pf > 1.0) / len(oos_pfs)
    if pct >= 0.75:
        return "STRONG"
    if pct >= 0.55:
        return "MODERATE"
    return "WEAK"
