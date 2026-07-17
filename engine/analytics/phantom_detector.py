"""Automated pre-EOD phantom detector — flag-only (2026-07-02).

The recurring failure mode is a *phantom* closed trade — a duplicate booking, a
frozen/contaminated price, or a fabricated P&L — that lands ``status='closed'``,
gets counted by the 20:05 UTC EOD snapshot, and is only caught days later when
someone hand-edits ``scripts/mark_phantom_trades.py`` with the bad trade IDs.

This module closes that gap on the *front* end: it scans the closed ledger and
FLAGS suspicious trades automatically so Amo has a fresh, evidence-tagged list to
confirm-mark *before* the snapshot trusts them. It is deliberately **flag-only** —
it never mutates a row, never voids a trade, never changes a snapshot. Marking a
suspect phantom stays a human decision (``mark_phantom_trades.py``); once marked,
the EOD self-heal (``repair_daily_pnl``) corrects the historical daily_pnl rows.

Design constraint: the live price feed is frequently BLIND, so every signal here
is *self-contained* — it needs only the trades' own stored fields, never a live
quote. The four signals map onto the real historical phantom causes:

  duplicate_key          Same fill booked twice. Idempotency keys that share a
                         base (after stripping a ``-2`` / ``_3`` retry suffix)
                         across >=2 closed rows.
  pnl_price_inconsistent Stored ``pnl`` disagrees with
                         ``(exit-entry) * direction * multiplier * quantity``
                         beyond tolerance — a frozen exit, a contaminated entry,
                         or an outright fabricated P&L.
  entry_price_outlier    Entry deviates > ``ref_dev_pct`` from the robust median
                         entry of that symbol's other closed trades in the window.
                         This is the retrospective analogue of
                         ``entry_price_sanity``'s reference-deviation check, using
                         the trades themselves as the reference (the median is
                         outlier-robust, so a lone contaminated entry stands out).
  entry_exit_excursion   The row's own entry and exit are further apart than the
                         instrument can plausibly travel while the trade is open.
                         Needs no peer group, so it covers the sparse instruments
                         ``entry_price_outlier`` structurally cannot (see below).

Rows already resolved (``phantom`` / ``cancelled`` / ``void``) are never re-flagged.
"""

from __future__ import annotations

import logging
import re
import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

try:  # engine-root import (tests + runtime add engine/ to sys.path)
    from utils.position_sizing import INSTRUMENT_MULTIPLIERS
except Exception:  # pragma: no cover - packaged import fallback
    from engine.utils.position_sizing import INSTRUMENT_MULTIPLIERS  # type: ignore

# Statuses whose rows are already resolved as non-real — never re-flag them.
RESOLVED_STATUSES = frozenset({"phantom", "cancelled", "void"})

_LONG_SIDES = frozenset({"buy", "long", "b", "bot"})
_SHORT_SIDES = frozenset({"sell", "short", "s", "sld"})

# Trailing dedup suffix (``-2``, ``_3``) so retries collapse to one base key.
_SUFFIX_RE = re.compile(r"[-_]\d+$")

# Defaults (all overridable per-call).
DEFAULT_PNL_TOL_ABS = 1.0  # account currency: absolute floor on the pnl tolerance
DEFAULT_PNL_TOL_PCT = 0.02  # ...or 2% of the expected magnitude, whichever larger
DEFAULT_REF_DEV_PCT = 0.15  # entry-vs-peer-median deviation ceiling (matches sanity)
DEFAULT_MIN_PEERS = 3  # need >=3 same-symbol trades before a median is trustworthy
# Ceiling on |exit-entry|/entry for a single trade. Calibrated off the real MES
# ledger (2026-07-17): the wrong-era phantom sat at 0.4175 while the WORST
# genuine trade in 50 closed rows was 0.0177 — a 24x gap, so 0.15 is 8.5x above
# anything real and 2.8x below the contamination. Flat rather than
# holding-period-scaled on purpose: the signal is flag-only (a human confirms via
# mark_phantom_trades.py), so precision past "obviously impossible" buys nothing.
DEFAULT_EXCURSION_PCT = 0.15


def _commission_allowance() -> float:
    """Per-unit round-trip commission that a stored ``pnl`` may already net out.

    Mirrors ``portfolio.tracker._commission_per_contract`` (same env var, same
    $1.50 default) rather than importing it — analytics must not take a runtime
    dependency on the portfolio layer, and this module is pure over its rows.
    Keep the two in sync if the tracker's costing model changes.
    """
    import os

    try:
        return abs(float(os.getenv("COMMISSION_PER_CONTRACT", "1.50")))
    except (TypeError, ValueError):
        return 1.50


@dataclass
class Suspect:
    """One flagged closed trade with the reasons + evidence that flagged it."""

    trade_id: str
    symbol: str
    pnl: float
    reasons: list = field(default_factory=list)
    detail: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "pnl": self.pnl,
            "reasons": list(self.reasons),
            "detail": dict(self.detail),
        }


def _num(value) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _base_key(key) -> str:
    if not key:
        return ""
    return _SUFFIX_RE.sub("", str(key).strip())


def _direction(side) -> Optional[int]:
    s = str(side or "").strip().lower()
    if s in _LONG_SIDES:
        return 1
    if s in _SHORT_SIDES:
        return -1
    return None


def _multiplier(symbol) -> float:
    """P&L point-multiplier for reconstructing expected pnl.

    Known futures use their contract point value; every other symbol (equities,
    ETFs) defaults to 1.0 — a stock's P&L is ``(exit-entry) * shares``. The
    position-sizing default (5.0, MES-like, deliberately conservative for
    *sizing*) is WRONG here: applied to an equity it inflates expected pnl 5x and
    false-flags every stock trade as inconsistent. For pnl reconstruction the
    honest fallback is 1.0.
    """
    return INSTRUMENT_MULTIPLIERS.get(str(symbol or "").upper(), 1.0)


def detect_suspects(
    trades: Iterable[Mapping],
    *,
    pnl_tol_abs: float = DEFAULT_PNL_TOL_ABS,
    pnl_tol_pct: float = DEFAULT_PNL_TOL_PCT,
    ref_dev_pct: float = DEFAULT_REF_DEV_PCT,
    min_peers: int = DEFAULT_MIN_PEERS,
    excursion_pct: float = DEFAULT_EXCURSION_PCT,
    enable_price_outlier: bool = False,
) -> list:
    """Return the list of :class:`Suspect` closed trades in ``trades``.

    Pure over the supplied rows — no DB, no clock, no network. Each row is a
    mapping with (at least) ``trade_id``, ``symbol``, ``side``, ``quantity``,
    ``entry_price``, ``exit_price``, ``pnl``, ``status``, ``idempotency_key``.
    Only ``status=='closed'`` rows are candidates; resolved rows are ignored.

    The always-on signals (``duplicate_key``, ``pnl_price_inconsistent``,
    ``entry_exit_excursion``) are robust and self-contained — they never need a
    price reference and produce no false positives on the real ledger.

    ``enable_price_outlier`` (default **OFF**) gates the same-day entry-outlier
    signal. It is opt-in because it relies on the day's *own* trades as the price
    reference via a median, which is only trustworthy when the contaminated
    entries are the MINORITY of that day/symbol's trades. On a thin day where
    stale-era entries are the majority the median lands ON the contamination and
    the signal fingers the *genuine* trade — the exact confident-but-wrong flag
    this subsystem exists to avoid. Direction can only be disambiguated with an
    external era reference, which the (frequently blind) live feed can't supply.
    Enable it only for manual review, reading each flag as "look at this day",
    not "this specific trade is the phantom".
    """
    closed = [
        t
        for t in trades
        if str(t.get("status", "")).strip().lower() not in RESOLVED_STATUSES
        and str(t.get("status", "")).strip().lower() == "closed"
    ]

    suspects: dict = {}

    def _sus(t) -> Suspect:
        tid = str(t.get("trade_id"))
        s = suspects.get(tid)
        if s is None:
            s = Suspect(tid, str(t.get("symbol", "")).upper(), _num(t.get("pnl")) or 0.0)
            suspects[tid] = s
        return s

    def _flag(t, reason: str, detail: dict) -> None:
        s = _sus(t)
        if reason not in s.reasons:
            s.reasons.append(reason)
        s.detail[reason] = detail

    # --- Signal A: duplicate idempotency key ------------------------------
    key_groups: dict = defaultdict(list)
    for t in closed:
        base = _base_key(t.get("idempotency_key"))
        if base:
            key_groups[base].append(t)
    for base, group in key_groups.items():
        if len(group) >= 2:
            ids = [str(t.get("trade_id")) for t in group]
            for t in group:
                _flag(t, "duplicate_key", {"base_key": base, "count": len(group), "trade_ids": ids})

    # --- Signal B: pnl / price internal inconsistency ---------------------
    for t in closed:
        entry = _num(t.get("entry_price"))
        exit_ = _num(t.get("exit_price"))
        pnl = _num(t.get("pnl"))
        qty = _num(t.get("quantity"))
        direction = _direction(t.get("side"))
        if entry and exit_ and pnl is not None and qty and direction is not None:
            expected = (exit_ - entry) * direction * _multiplier(t.get("symbol")) * qty
            # ``expected`` is GROSS, but tracker.close_paper_trade stores pnl NET
            # of a flat round-trip commission (tracker.py:423). Absorb up to one
            # commission per unit so that cost isn't read as fabrication — it was
            # false-flagging every small-pnl trade (4 of 50 closed rows on
            # 2026-07-17, each off by exactly $1.50 x qty).
            #
            # Widen rather than subtract: rows closed before the commission term
            # existed are stored PRE-cost (see tracker._commission_per_contract),
            # so a subtraction would fix the new rows and break the old ones. A
            # widened band covers both eras and can only ever remove a false
            # positive, never add one. Nothing real hides under it — a fabricated
            # pnl (the -266.25 shape) clears this by orders of magnitude.
            tol = max(pnl_tol_abs, pnl_tol_pct * abs(expected)) + _commission_allowance() * abs(qty)
            if abs(pnl - expected) > tol:
                _flag(
                    t,
                    "pnl_price_inconsistent",
                    {
                        "stored_pnl": round(pnl, 4),
                        "expected_pnl": round(expected, 4),
                        "diff": round(pnl - expected, 4),
                        "tol": round(tol, 4),
                    },
                )

    # --- Signal D: implausible intra-trade excursion (always-on) ----------
    # Compares the row's OWN two prices, so it needs no peer group at all. That
    # is what makes it work where Signal C structurally cannot: C requires
    # >=min_peers same-symbol SAME-DAY exits, and MES exits exactly 1 trade per
    # day — so C has never once evaluated an MES entry.
    #
    # It also catches what Signal B provably cannot. On a wrong-era entry the
    # stored pnl is internally CONSISTENT with the corrupt price
    # ((5299.875-7512.5)*-1*5*1 == -11063.12 exactly), so B passes it clean. The
    # tell isn't the arithmetic — it's that no MES trade travels 41% while open.
    for t in closed:
        entry = _num(t.get("entry_price"))
        exit_ = _num(t.get("exit_price"))
        if not entry or entry <= 0 or not exit_ or exit_ <= 0:
            continue
        dev = abs(exit_ - entry) / entry
        if dev > excursion_pct:
            _flag(
                t,
                "entry_exit_excursion",
                {
                    "entry_price": round(entry, 4),
                    "exit_price": round(exit_, 4),
                    "deviation_pct": round(dev, 4),
                    "threshold": excursion_pct,
                },
            )

    # --- Signal C: entry price outlier vs same-symbol, SAME-DAY peers -----
    # Grouped by (symbol, exit-date), NOT the whole window: MES was ~5300 in
    # 2024 and ~7400 in 2026, so a window-wide median mixes price eras and
    # false-flags legitimate cross-era entries (the exact trap entry_price_sanity
    # documents). Same-day scoping also matches the real contamination shape — a
    # single 7398.5481 entry among that day's genuine 5600 cluster.
    by_symbol_day: dict = defaultdict(list)
    for t in closed if enable_price_outlier else []:
        entry = _num(t.get("entry_price"))
        if entry and entry > 0:
            day = str(t.get("exit_time") or "")[:10]
            if not day:
                continue
            by_symbol_day[(str(t.get("symbol", "")).upper(), day)].append(t)
    for _key, group in by_symbol_day.items():
        if len(group) < min_peers:
            continue
        median = statistics.median([_num(t.get("entry_price")) for t in group])
        if not median or median <= 0:
            continue
        for t in group:
            entry = _num(t.get("entry_price"))
            dev = abs(entry - median) / median
            if dev > ref_dev_pct:
                _flag(
                    t,
                    "entry_price_outlier",
                    {
                        "entry_price": round(entry, 4),
                        "peer_median": round(median, 4),
                        "deviation_pct": round(dev, 4),
                        "peers": len(group),
                    },
                )

    return sorted(suspects.values(), key=lambda s: (s.symbol, str(s.trade_id)))


def detect_suspect_closed_trades(
    db,
    *,
    on_date: Optional[str] = None,
    lookback: int = 300,
    **kwargs,
) -> list:
    """DB-backed entry point: pull the recent closed ledger and flag suspects.

    ``on_date`` (``YYYY-MM-DD``) scopes the *reported* suspects to trades whose
    ``exit_time`` falls on that UTC date, while still using the full ``lookback``
    window as peer/duplicate context (so a lone contaminated entry today is still
    measured against the whole cluster). Unscoped, every suspect in the window is
    returned. ``kwargs`` pass through to :func:`detect_suspects`.
    """
    try:
        trades = db.get_trade_history(limit=lookback, status="closed")
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("[PhantomDetector] failed to read closed ledger: %s", exc)
        return []

    suspects = detect_suspects(trades, **kwargs)
    if on_date is None:
        return suspects

    # Map trade_id -> exit-date for date scoping.
    exit_date = {}
    for t in trades:
        raw = str(t.get("exit_time") or "")
        exit_date[str(t.get("trade_id"))] = raw[:10]
    return [s for s in suspects if exit_date.get(s.trade_id) == on_date]


def format_suspect_report(suspects: Iterable[Suspect]) -> str:
    """One-line-per-suspect human summary for logs / notifications."""
    rows = list(suspects)
    if not rows:
        return "phantom-detector: 0 suspect closed trades."
    lines = [f"phantom-detector: {len(rows)} suspect closed trade(s):"]
    for s in rows:
        lines.append(f"  {s.trade_id} [{s.symbol}] pnl={s.pnl:+.2f} :: {', '.join(s.reasons)}")
    return "\n".join(lines)
