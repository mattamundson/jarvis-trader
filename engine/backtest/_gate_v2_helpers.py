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

import hashlib
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

#: Fraction of OOS windows with PF > 1.0 required on the ALT path.
#:
#: NOT YET ENFORCED BY ANY RUNNER — this constant exists so the ALT path can be
#: aligned with the criterion that is already documented as the *promotion*
#: requirement, `engine/CLAUDE.md` "Flip-to-active criteria" item 1:
#:
#:     p_positive_edge >= 0.6 on a fresh rolling walk-forward run (ALT path)
#:
#: The ALT conjunction currently inlined across the runners is
#: `dsr >= GATE_DSR_ALT and wfo in {MODERATE,STRONG} and
#:  fixed_params_min_pf >= 1.20 and cost_passes and mc_95th_dd <= GATE_MC_DD_ALT`
#: — it does NOT reference `p_edge`, so a verdict can print "PASS via alt" with a
#: p_edge below the documented 0.6 activation bar. Observed 2026-09-17:
#: `MES_trend_vix_pctile_rank1` reported PASS via alt at p_edge = 0.5926, while 47 of its
#: 54 traded windows held exactly one trade, the median window held one trade, and ZERO
#: windows reached the gate-standard 5-trade floor (sample adequacy FALSE) — i.e. the
#: p_edge numerator was a fraction of windows that cannot support an edge claim.
#: (An earlier note here said "29 of 32 profitable windows were single-trade / 0.12
#: excluding them"; that was inferred from PF=inf and is WRONG — inf only means no losing
#: trades. Corrected to direct per-window trade counts. See PR #866.)
#:
#: Wiring this into the ~65 inline ALT conjunctions is a repo-wide behavioural
#: change to every future verdict; it is deliberately left unwired pending review.
#: See `docs/research/alt-p-edge-gate-proposal-2026-09-17.md` for the impact
#: analysis: of 9 recorded ALT-path PASS verdicts, exactly 1 would flip.
GATE_P_EDGE_ALT: float = 0.60

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


def _span_label(path: Path) -> str:
    """Human-readable span label from a cache filename (e.g. '7.3y')."""
    years = _span_years(path)
    return f"{years:.1f}y" if years else "unknown-span"


def _span_years(path: Path) -> float:
    """Approx. calendar span (years) from the filename's two ISO date segments.

    Contract: ``<PREFIX>_<START>_<END><SUFFIX>``. Off-contract names return 0.
    This is a FILENAME-level estimate (cheap, no CSV read) used only by the
    deep->shallow demotion guard to detect a span collapse like
    ``MES_2015-01-01_2026-08-16`` (deep) vs ``MES_2024-04-26_2026-08-14``
    (shallow). The authoritative span check is
    ``cache_completeness.inspect_completeness`` on the actual timestamps; this
    only needs the *relative* magnitude to catch a material demotion.
    """
    parts = Path(path).stem.split("_")
    if len(parts) < 3:
        return 0.0
    try:
        from datetime import date

        start = date.fromisoformat(parts[1])
        end = date.fromisoformat(parts[2])
        return max((end - start).days, 0) / 365.25
    except ValueError:
        return 0.0


def _is_material_shallow_demotion(chosen: Path, deep: Path) -> bool:
    """True when ``chosen`` is materially shallower than ``deep``.

    The 2026-08-17 contamination pair was 7.3y (deep) vs 2.3y (shallow): a
    3.2x span collapse. We treat anything >= 1.5x shorter (or unknown) as
    material so a demotion can never be *silent*, while not flagging the
    benign refreshed-pull case where the latest-end file simply has a later
    end date at a similar span (e.g. 2026-05-07 vs 2026-03-28 pulls of the
    same 2y window).
    """
    deep_years = _span_years(deep)
    chosen_years = _span_years(chosen)
    if deep_years <= 0:
        return False  # nothing to demote from
    if chosen_years <= 0:
        return True  # off-contract chosen: cannot prove it is deep -> flag
    return chosen_years < deep_years / 1.5


def _deep_cache_enforced() -> bool:
    """Fail-fast switch for the deep->shallow demotion guard (2026-08-17 fix).

    Default OFF: the demotion still logs a WARNING but returns the chosen
    cache (historical behavior). Set ``GATE_V2_ENFORCE_DEEP_CACHE=1`` to make
    ``_find_latest_cache`` raise ``RuntimeError`` instead of silently letting
    shallow data stand in for a deep cache. Matches the house
    ``GATE_V2_ENFORCE_*`` convention (evaluated at call time, no re-import).
    """
    return os.getenv("GATE_V2_ENFORCE_DEEP_CACHE", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


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

 Deep-data standard (2026-08-17): only the deep cache certifies edge. Shallow
 (~2.3y) caches do NOT certify — they were moved out of the certification path
 during the deep revalidation to
 ``wt-deep-reval-20260817/engine/backtest/cache/_shallow_isolated/`` (that
 worktree has since been removed by peer cleanup; the policy stands). Runners
 must not select shallow caches for certification runs — the MES deep cache is
 ``MES_2015-01-01_2026-08-16_1h.csv`` (actual span 2019-05-05 → 2026-08-14,
 7.27y; filenames can lie — verify from data, not filename).

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
    if prefer_complete and len(candidates) > 1:
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
        except Exception as exc:  # never let the completeness check break loading
            logging.getLogger(__name__).warning(
                "Cache completeness check failed (%s); using latest-end %s",
                exc,
                latest.name,
            )
            return latest

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
            log.warning(
                "Cache completeness: no fully-trustworthy %s%s cache; using "
                "latest-end %s which has %s suspicious gap(s)",
                prefix,
                suffix,
                latest.name,
                pick["n_suspicious_gaps"],
            )

        # DEEP->SHALLOW demotion guard (2026-08-17 contamination fix, E2).
        # `find_trustworthy_cache` can return a cache whose END date is later
        # but whose SPAN is far shorter than the latest-end deep cache (e.g.
        # the 7.3y MES_2015-01-01_2026-08-16 deep cache vetoed as "holed" in
        # favor of the 2.3y MES_2024-04-26_2026-08-14 shallow cache, which
        # produced fake 'deep' verdicts at n_windows=20). Shallow data must
        # NEVER silently certify a deep verdict: log a WARNING naming the
        # exact cache chosen + reason, and fail fast when
        # GATE_V2_ENFORCE_DEEP_CACHE=1. Runs OUTSIDE the try above so the
        # enforcement raise is not swallowed by the load-tolerance fallback.
        if (
            pick["fallback"]
            or not pick["chose_latest_end"]
            or chosen != latest
        ) and _is_material_shallow_demotion(chosen, latest):
            if _deep_cache_enforced():
                raise RuntimeError(
                    f"GATE_V2_ENFORCE_DEEP_CACHE: refusing shallow fallback "
                    f"{chosen.name} when deep cache {latest.name} exists "
                    f"(completeness reason: {pick['reason']})"
                )
            log.warning(
                "Cache completeness DEEP->SHALLOW demotion: deep cache %s "
                "(%s) vetoed; using shallow %s (%s). Shallow caches do NOT "
                "certify deep gate-v2 verdicts. Reason: %s",
                latest.name,
                _span_label(latest),
                chosen.name,
                _span_label(chosen),
                pick["reason"],
            )
        return chosen

    return latest


def cache_provenance(path) -> dict:
    """Content-addressed provenance for a cache file, for recording inside a verdict.

    Why this exists (2026-09-17 audit, `docs/research/verdict-artifact-audit-2026-09-17.md`):
    **zero of 76** verdict artifacts recorded which cache they ran on. Provenance existed only as
    a filename convention, and that convention is demonstrably unreliable — 8 duplicate-content
    groups (19 files) file the same bytes under `-deep-`, `-pre-deep-`, and
    `-shallow-contaminated-` labels. So no "validated on deep data" claim could be independently
    verified from its artifact.

    Recording this dict in the verdict makes provenance checkable with one line instead of a
    re-run. Filename is recorded too, but the hash is what makes it tamper-evident.

    Deliberately dependency-light (no pandas): it must work on the raw file even if a loader
    later changes, and it must be cheap to test.
    """
    p = Path(path)
    if not p.exists():
        return {"error": "cache_not_found", "cache_file": p.name}

    raw = p.read_bytes()
    # Timestamps: first and last data row's first CSV field (no pandas needed).
    lines = raw.decode("utf-8", errors="replace").splitlines()
    data = [ln for ln in lines[1:] if ln.strip()] if lines else []
    first_ts = data[0].split(",")[0].strip() if data else ""
    last_ts = data[-1].split(",")[0].strip() if data else ""

    prov = {
        "cache_file": p.name,
        "cache_rows": len(data),
        "cache_span_first": first_ts,
        "cache_span_last": last_ts,
        "cache_bytes": len(raw),
        "cache_sha256": hashlib.sha256(raw).hexdigest(),
    }
    # Flag non-deep provenance on a MEASURABLE basis, not a filename token: the repo names its
    # deep caches by span (e.g. MES_2019-05-05_2026-08-26_1h.csv), so a `-deep-` token check
    # misfires on exactly the cache that matters. The standing rule is that a shallow cache
    # (~2.3y) does NOT certify edge, so span is the thing worth recording.
    try:
        from datetime import datetime

        first = datetime.fromisoformat(first_ts)
        last = datetime.fromisoformat(last_ts)
        span_years = (last - first).days / 365.25
        prov["cache_span_years"] = round(span_years, 3)
        if span_years < 5.0:
            prov["provenance_note"] = (
                f"span {span_years:.2f}y < 5.0y: does not meet the deep-data standard"
            )
    except (TypeError, ValueError):
        prov["provenance_note"] = "span unparseable from cache timestamps"
    return prov


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


def window_quality(oos_results, gate_min_trades: int = MIN_OOS_TRADES_PER_WINDOW) -> dict:
    """Honest window-quality decomposition of an OOS window set.

    **ADDITIVE — this function changes no pass/fail decision.**

    Why it exists (2026-09-17): 37 runners override the gate-standard
    ``MIN_OOS_TRADES_PER_WINDOW`` (5) down to 1, deliberately and with comments —
    trend strategies generate only 1-3 trades per 2-month OOS window, so a 5-trade
    floor yields ``INSUFFICIENT_SAMPLE`` everywhere. The consequence is that the
    reported ``p_edge`` is computed over windows that cannot distinguish edge from a
    coin flip: for ``MES_sma_trend_vix_pctile_blockCrisis_v1`` the verdict reported
    ``p_edge = 0.5926`` while 47 of its 54 traded windows held exactly one trade.

    Rather than raise the floor (which would silently fail every trend strategy), this
    reports the elevation in the open. For the candidate above on the deep cache the
    measured structure was: 82 windows, 54 with trades, of which **47 held exactly one
    trade**, median 1.0 trades/window, and **zero windows reached the 5-trade gate floor** —
    so ``p_edge_at_gate_floor`` is 0.0 and the sample-adequacy check is ``False``. The
    reported ``p_edge`` of 0.5926 is therefore a fraction of windows that cannot support an
    edge claim in either direction.

    - ``p_edge`` — the runner's existing definition (unchanged, for comparability)
    - ``p_edge_excl_single_trade`` — over windows with >= 2 trades
    - ``p_edge_at_gate_floor`` — over windows meeting the gate-standard floor
    - ``median_trades_per_window`` / ``sample_adequate_at_gate_floor`` — the same
      adequacy question the gate already asks via ``MIN_OOS_TRADES_PER_WINDOW``
    - ``n_windows_single_trade`` — the count of degenerate "profitable" windows

    A verdict whose ``p_edge`` sits near a threshold while
    ``p_edge_excl_single_trade`` collapses toward 0 is carried by degenerate windows,
    not by edge.
    """

    def _p_edge_of(rows, min_trades: int = 1) -> float:
        pfs = [r.profit_factor for r in rows if getattr(r, "total_trades", 0) >= min_trades]
        if not pfs:
            return 0.0
        return sum(1 for pf in pfs if pf > 1.0) / len(pfs)

    windows = list(oos_results or [])
    with_trades = [r for r in windows if getattr(r, "total_trades", 0) >= 1]
    single = [r for r in with_trades if r.total_trades == 1]
    trades = [int(r.total_trades) for r in with_trades]
    median_tpw = float(np.median(trades)) if trades else 0.0

    return {
        "n_windows": len(windows),
        "n_windows_with_trades": len(with_trades),
        "n_windows_single_trade": len(single),
        "gate_min_trades": int(gate_min_trades),
        "n_windows_at_gate_floor": sum(1 for r in with_trades if r.total_trades >= gate_min_trades),
        "median_trades_per_window": round(median_tpw, 3),
        "sample_adequate_at_gate_floor": bool(median_tpw >= gate_min_trades),
        "p_edge": round(_p_edge_of(windows), 4),
        "p_edge_excl_single_trade": round(_p_edge_of(windows, 2), 4),
        "p_edge_at_gate_floor": round(_p_edge_of(windows, gate_min_trades), 4),
    }
