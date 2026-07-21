"""Shared gate v2 metric helpers — single source of truth for runner files.

Gate v2 threshold constants
----------------------------
Import these into runner files instead of re-defining them locally:

    from backtest._gate_v2_helpers import (
        GATE_PF_CI_LOWER, GATE_P_EDGE, GATE_MC_DD_CORE, GATE_MC_DD_ALT,
        GATE_DSR, GATE_DSR_ALT, N_BOOTSTRAP,
        # WFO window defaults
        WFO_TRAIN_MONTHS, WFO_TEST_MONTHS, WFO_STEP_MONTHS,
        MIN_OOS_TRADES_PER_WINDOW, MIN_OOS_TRADES_TOTAL,
        # Cost sweep tiers
        COST_SWEEP_TIERS, COST_TIER_ORDER,
    )

Any future change to a threshold is a single-line edit here; no runner
files need to change.
"""

from __future__ import annotations

import os
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
#: Tightened from 0.07 (7%) to 0.04 (4%) on 2026-05-09; both active PASS-alt
#: strategies (MES R11 at 0.81%, MGC R4 at ~1.2%) sit well under the new ceiling.
GATE_MC_DD_ALT: float = 0.04

#: Deflated Sharpe ratio floor — CORE path.
GATE_DSR: float = 0.10

#: Deflated Sharpe ratio floor — ALT path (trend strategies on daily bars).
GATE_DSR_ALT: float = 0.30

#: Bootstrap win-rate CI lower-bound floor (Init 2C). Complements DSR — which a
#: few large outlier wins can carry — by binding on win RELIABILITY. SHADOW /
#: NOT YET ENFORCED: the runners record ``win_rate_ci_lower`` into gate_v2_metrics,
#: but this threshold stays ``None`` until calibrated empirically against the
#: historical PASS set (one refresh cycle of recorded values). Guessing a value
#: would be exactly the selection bias the gate exists to prevent. Wiring it into
#: the ALT ``alt_pass`` conjunction is the explicit enforce step that follows
#: calibration.
GATE_WIN_RATE_CI_LOWER: float | None = None

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

#: Minimum TOTAL out-of-sample trades (summed across ALL walk-forward windows)
#: for a gate verdict to be statistically defensible. 30 is the conventional
#: small-sample floor. Below this the per-trade DSR / Monte-Carlo drawdown are
#: estimated from too few points to trust — e.g. a 16-trade series can yield a
#: DSR ~ 1.0 that reflects luck, not a durable edge. Enforced ONLY when
#: ``sample_adequacy_enforced()`` returns True (Init 2B; see that function).
MIN_OOS_TRADES_TOTAL: int = 30


def sample_adequacy_enforced() -> bool:
    """Shadow -> enforce switch for the sample-adequacy floor (Init 2B).

    Default OFF (shadow mode): runners still compute and record the floor's
    inputs (``total_oos_trades`` / ``sample_adequate``) into the verdict
    metrics, but the verdict itself is unchanged — so live paper authorization
    is unaffected. Set the environment variable
    ``GATE_V2_ENFORCE_SAMPLE_ADEQUACY=1`` to enforce: a strategy with fewer
    than ``MIN_OOS_TRADES_TOTAL`` total OOS trades returns verdict
    ``INSUFFICIENT_SAMPLE`` and is de-authorized (gate_v2_policy default-deny).

    Env-gated rather than a code constant to match the existing house
    ``GATE_V2_ENFORCE_*`` convention (cf. ``GATE_V2_ENFORCE_ROUTING``) so the
    shadow->enforce flip is a one-line, fully reversible ``.env`` change with no
    code edit. Evaluated at call time so it can be toggled without re-import.
    """
    return os.getenv("GATE_V2_ENFORCE_SAMPLE_ADEQUACY", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def per_window_adequacy_enforced() -> bool:
    """Shadow -> enforce switch for the PER-WINDOW adequacy floor (Task 8 follow-on).

    Companion to ``sample_adequacy_enforced()``. The aggregate
    ``MIN_OOS_TRADES_TOTAL`` floor is necessary but NOT sufficient: a strategy can
    clear 30 aggregate OOS trades while most windows are 1-4 trades with degenerate
    PFs (e.g. ``MGC_trend_rank4``: 67 aggregate, median 4/window, 14 of 19 thin).
    This switch makes a strategy whose MEDIAN window is below
    ``MIN_OOS_TRADES_PER_WINDOW`` return ``INSUFFICIENT_SAMPLE``.

    Default OFF (shadow): runners record the per-window inputs but the verdict is
    unchanged, so live authorization is unaffected. Set
    ``GATE_V2_ENFORCE_PER_WINDOW=1`` to enforce. Like the aggregate flag this is an
    env switch (house ``GATE_V2_ENFORCE_*`` convention) evaluated at call time, so
    the shadow->enforce flip is a one-line, fully reversible ``.env`` change.
    """
    return os.getenv("GATE_V2_ENFORCE_PER_WINDOW", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def per_window_sample_adequate(per_window_trades: list[int] | None) -> bool:
    """True iff the MEDIAN per-window OOS trade count clears the per-window floor.

    ``per_window_trades`` is the list of OOS trade counts, one per WFO window.
    Empty/None -> False (fail-safe: unknown per-window distribution does not
    certify). Uses the median (not the mean) so a few fat windows cannot mask many
    thin ones — that masking is exactly the necessary-not-sufficient gap this guard
    closes.
    """
    if not per_window_trades:
        return False
    return bool(float(np.median(per_window_trades)) >= MIN_OOS_TRADES_PER_WINDOW)


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


class UntrustworthyCacheError(RuntimeError):
    """Raised when cache trust is ENFORCED and no sound cache is available.

    Deliberately a distinct type so the broad `except Exception` inside
    `_find_latest_cache` cannot swallow a refusal it was meant to produce.
    """


#: Env flag: make cache-trust failures REFUSE instead of warn-and-continue.
#: Default OFF -- ships dormant, mirroring `GATE_V2_ENFORCE_ROUTING`. Turning it
#: on halts any run whose cache is holed or unverifiable, which is the point;
#: enable once a trustworthy cache exists, or every gate-v2 run stops.
_CACHE_TRUST_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _is_cache_trust_enforced() -> bool:
    """Check `GATE_V2_ENFORCE_CACHE_TRUST` env var (case-insensitive truthy set)."""
    return (
        os.environ.get("GATE_V2_ENFORCE_CACHE_TRUST", "").strip().lower()
        in _CACHE_TRUST_TRUTHY
    )


def _find_latest_cache(
    data_dir: Path, prefix: str, suffix: str = "_1h.csv", *, prefer_complete: bool = True
) -> Path:
    """Pick the cache file whose filename's second date segment is the latest.

    Completeness preference (``prefer_complete``, default True): the latest END
    date does NOT imply the file is COMPLETE — a holed late-end cache (e.g.
    ``MES_2025-04-09_2026-06-22_5m_cont.csv`` missing Apr–Nov 2025) can out-sort a
    clean earlier one. When more than one candidate exists and ``prefer_complete``
    is set, this delegates to ``cache_completeness.find_trustworthy_cache`` (with
    both the full-closure and early-close calendars whitelisted) and returns the
    latest-end cache with no unexplained missing weekday; if none qualifies it
    falls back to the latest-end file (the historical behavior) and logs a
    warning. Pass ``prefer_complete=False`` to force pure latest-end.

    2026-07-06 correction: this docstring previously claimed the plain 1h futures
    caches (no ``_cont`` suffix) are RTH-only and therefore always fall back to
    latest-end unchanged. That was wrong — they are near-continuous (~23h Globex
    sessions) and the real failure mode was a missing early-close whitelist (see
    ``cache_completeness.US_MARKET_EARLY_CLOSES``), which caused the latest MES
    1h cache to be misjudged "holed" and passed over for a much smaller cache
    (the 2026-07-06 vwap-sharpe incident). Both calendars are now applied here.

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

    # Anchor the symbol on a trailing underscore so a prefix like "MES" matches
    # "MES_2024-..._1h.csv" but NOT a longer symbol that merely starts with it
    # ("MESXX_..._1h.csv"). The filename contract is <SYMBOL>_<START>_<END>_<INTERVAL>,
    # so a "_" always follows the symbol. Without the anchor, glob "MES*" leaks
    # MESXX files into MES's candidate set and a same-end-date tie can silently
    # select the wrong symbol's cache.
    candidates = sorted(data_dir.glob(f"{prefix}_*{suffix}"))
    if not candidates:
        raise FileNotFoundError(
            f"No {prefix} {suffix.lstrip('_').rstrip('.csv')} data found in "
            f"{data_dir} (looked for '{prefix}_*{suffix}')"
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

    latest = max(candidates, key=_end_date)

    # Completeness preference: prefer the latest-end fully-trustworthy cache over a
    # holed late-end one. Only engages with >1 candidate (single-cache dirs and the
    # common refreshed-pull case pay zero inspection cost).
    # Completeness preference. With >1 candidate this picks the sounder file
    # (historical behavior). A SINGLE candidate was previously skipped outright
    # -- exactly the case that shipped the 57%-complete MES 15m file into
    # gate-v2 runs on 2026-07-21, since a one-file directory is not evidence
    # the one file is sound. That hole is closed only when enforcement is on,
    # because inspecting a lone cache on every call costs real wall-clock
    # (~275ms on a 13k-bar file) and the dormant path must stay free.
    if prefer_complete and (len(candidates) > 1 or _is_cache_trust_enforced()):
        try:
            from backtest.cache_completeness import (
                US_MARKET_EARLY_CLOSES,
                US_MARKET_HOLIDAYS,
                find_trustworthy_cache,
            )

            pick = find_trustworthy_cache(
                data_dir,
                prefix,
                suffix,
                holiday_dates=US_MARKET_HOLIDAYS | US_MARKET_EARLY_CLOSES,
            )
            chosen = Path(pick["path"])
            log = logging.getLogger(__name__)
            if not pick["chose_latest_end"]:
                log.warning(
                    "Cache completeness: latest-end %s is holed; using "
                    "completeness-preferred %s (%s)",
                    latest.name,
                    chosen.name,
                    pick["reason"],
                )
            elif pick["fallback"]:
                if _is_cache_trust_enforced():
                    raise UntrustworthyCacheError(
                        f"No fully-trustworthy {prefix}{suffix} cache in {data_dir}: "
                        f"latest-end {latest.name} has {pick['n_suspicious_gaps']} "
                        f"suspicious gap(s). Refusing to load "
                        f"(GATE_V2_ENFORCE_CACHE_TRUST is on)."
                    )
                log.warning(
                    "Cache completeness: no fully-trustworthy %s%s cache; using "
                    "latest-end %s which has %s suspicious gap(s)",
                    prefix,
                    suffix,
                    latest.name,
                    pick["n_suspicious_gaps"],
                )
            return chosen
        except UntrustworthyCacheError:
            # An explicit refusal, not an infrastructure failure -- must not be
            # swallowed by the broad handler below.
            raise
        except Exception as exc:  # never let the completeness check break loading
            if _is_cache_trust_enforced():
                # Could not evaluate trust -> cannot assert it. Absence of
                # evidence is not evidence of soundness.
                raise UntrustworthyCacheError(
                    f"Cache completeness check failed for {prefix}{suffix} in "
                    f"{data_dir} ({exc}); refusing to load {latest.name} "
                    f"(GATE_V2_ENFORCE_CACHE_TRUST is on)."
                ) from exc
            logging.getLogger(__name__).warning(
                "Cache completeness check failed (%s); using latest-end %s",
                exc,
                latest.name,
            )
            return latest

    return latest


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
