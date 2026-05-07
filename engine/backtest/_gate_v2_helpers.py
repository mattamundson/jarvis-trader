"""Shared gate v2 metric helpers — single source of truth for runner files."""
from __future__ import annotations

from pathlib import Path

import numpy as np


def _find_latest_cache(data_dir: Path, prefix: str, suffix: str = "_1h.csv") -> Path:
    """Pick the cache file whose filename's second date segment is the latest.

    Filename contract:
        ``<PREFIX>_<START_DATE>_<END_DATE><SUFFIX>``
    where ``<START_DATE>`` and ``<END_DATE>`` are ISO ``YYYY-MM-DD`` strings.
    Lexicographic max on the second segment is equivalent to chronological max
    because ISO dates sort correctly as strings.

    A refreshed IBKR pull (e.g. ``MES_2024-01-01_2026-05-07_1h.csv``) will
    therefore always win over an older copy (e.g.
    ``MES_2024-01-01_2026-03-28_1h.csv``). Centralizes the bug-class fix from
    commit 55739db so future runners (MES, MGC, MNQ, MCL, M2K, ...) cannot
    silently revert to a hardcoded path.

    Args:
        data_dir: Directory to search (typically ``engine/backtest/cache/``).
        prefix:   Symbol or family prefix (e.g. ``"MES"``, ``"MGC"``).
        suffix:   Filename suffix including interval (default ``"_1h.csv"``).

    Returns:
        The :class:`Path` of the latest-end-date matching file.

    Raises:
        FileNotFoundError: If no files match ``<prefix>*<suffix>`` in ``data_dir``.
    """
    candidates = sorted(data_dir.glob(f"{prefix}*{suffix}"))
    if not candidates:
        raise FileNotFoundError(
            f"No {prefix} {suffix.lstrip('_').rstrip('.csv')} data found in "
            f"{data_dir} (looked for '{prefix}*{suffix}')"
        )

    def _end_date(p: Path) -> str:
        # Filename: <PREFIX>_YYYY-MM-DD_YYYY-MM-DD<SUFFIX> -> the second date
        parts = p.stem.split("_")
        return parts[2] if len(parts) >= 3 else ""

    return max(candidates, key=_end_date)


def bootstrap_pf_ci_lower(oos_pfs: list[float], n: int = 5000) -> float:
    """Bootstrap 5th-percentile of mean PF distribution; inf-cap baked in."""
    # Cap inf/-inf before bootstrapping — np.percentile returns NaN via inf-inf interpolation
    capped = [min(max(pf, 0.0), 5.0) if not (pf == float("inf") or pf == float("-inf"))
              else (5.0 if pf == float("inf") else 0.0)
              for pf in oos_pfs]
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
