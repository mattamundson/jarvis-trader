"""
post_trade.py -- Pure post-trade / scenario analytics over closed paper trades.

Everything here is a PURE function: no DB handle, no engine, no network, no
clock. Each takes a list of closed-trade dicts (rows straight out of
``paper_trades`` via ``dict(sqlite3.Row)``) and returns plain dicts. The
``analytics_router`` wires them to GET endpoints; the unit tests exercise them
directly with synthetic trades, so they stay green offline with no live data.

A "trade" is a dict whose keys mirror paper_trades columns. The relevant ones:

    trade_id, symbol, side, quantity, entry_price, exit_price, pnl,
    entry_time, exit_time, status, stop_loss, take_profit, bracket_status,
    slippage_ticks, regime, mae_pct, mfe_pct, mae_usd, mfe_usd

All functions tolerate missing / NULL values -- a column that no migration has
populated yet simply lands in the "unknown" / "unpopulated" bucket rather than
raising.

Design note on honesty
-----------------------
We do NOT invent data. ``exit_reason`` is *derived* from columns that already
exist (bracket_status, exit_price vs stop_loss/take_profit) rather than stored,
so this module adds no migration and never mutates a live trading schema. Where
the recorded data is insufficient to classify, the answer is ``"unknown"`` --
not a guess. ``slippage_ticks`` is reported as a standalone execution-quality
figure, never silently folded into a reconstructed "gross" P&L (which would
double-count against the already-realized ``pnl``).
"""

from __future__ import annotations

from typing import Callable, Iterable, Optional

# A spec_lookup is any callable symbol -> object with .tick_value / .multiplier
# / .commission attributes (backtest.contract_specs.ContractSpec), or None when
# the symbol is unknown. Kept as a parameter so the module imports nothing from
# the engine and the tests can pass a trivial fake.
SpecLookup = Callable[[str], Optional[object]]

# Exit-reason categories. Deliberately small + honest.
EXIT_TARGET = "target"
EXIT_STOP = "stop"
EXIT_MANUAL = "manual"
EXIT_UNKNOWN = "unknown"
EXIT_CATEGORIES = (EXIT_TARGET, EXIT_STOP, EXIT_MANUAL, EXIT_UNKNOWN)

_LONG_SIDES = {"buy", "buy_to_open", "long", "b"}
_SHORT_SIDES = {"sell", "sell_to_open", "short", "s"}


# ── small numeric helpers (stdlib only) ──────────────────────────────────────


def _num(v) -> Optional[float]:
    """Coerce to float, returning None for None / non-numeric / NaN."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def _mean(vals: Iterable[Optional[float]]) -> Optional[float]:
    clean = [v for v in vals if v is not None]
    return round(sum(clean) / len(clean), 6) if clean else None


def _median(vals: Iterable[Optional[float]]) -> Optional[float]:
    clean = sorted(v for v in vals if v is not None)
    n = len(clean)
    if n == 0:
        return None
    mid = n // 2
    if n % 2:
        return round(clean[mid], 6)
    return round((clean[mid - 1] + clean[mid]) / 2.0, 6)


def _percentile(vals: Iterable[Optional[float]], pct: float) -> Optional[float]:
    """Nearest-rank percentile (pct in [0, 100]). None on empty."""
    clean = sorted(v for v in vals if v is not None)
    n = len(clean)
    if n == 0:
        return None
    if n == 1:
        return round(clean[0], 6)
    # linear interpolation between closest ranks
    rank = (pct / 100.0) * (n - 1)
    lo = int(rank)
    hi = min(lo + 1, n - 1)
    frac = rank - lo
    return round(clean[lo] + (clean[hi] - clean[lo]) * frac, 6)


def _is_long(side) -> Optional[bool]:
    s = str(side or "").strip().lower()
    if s in _LONG_SIDES:
        return True
    if s in _SHORT_SIDES:
        return False
    return None


def _profit_factor(pnls: Iterable[Optional[float]]) -> Optional[float]:
    """
    gross_win / gross_loss. Returns None when undefined -- both "no trades" and
    "no losing trades" (profit factor would be infinite) collapse to None, which
    is JSON-safe (inf is not). The wins/losses counts in the same block let the
    caller distinguish an all-winners set from an empty one.
    """
    gross_win = sum(p for p in pnls if p is not None and p > 0)
    gross_loss = -sum(p for p in pnls if p is not None and p < 0)
    if gross_loss <= 0:
        return None
    return round(gross_win / gross_loss, 4)


def _win_rate(pnls) -> Optional[float]:
    decided = [p for p in pnls if p is not None and p != 0]
    if not decided:
        return None
    wins = sum(1 for p in decided if p > 0)
    return round(wins / len(decided), 4)


def _pnl_block(trades: list[dict]) -> dict:
    """Shared aggregate block used by several attribution groupings."""
    pnls = [_num(t.get("pnl")) for t in trades]
    decided = [p for p in pnls if p is not None and p != 0]
    return {
        "count": len(trades),
        "total_pnl": round(sum(p for p in pnls if p is not None), 4),
        "avg_pnl": _mean(pnls),
        "win_rate": _win_rate(pnls),
        "wins": sum(1 for p in decided if p > 0),
        "losses": sum(1 for p in decided if p < 0),
        "profit_factor": _profit_factor(pnls),
        "avg_mae_pct": _mean(_num(t.get("mae_pct")) for t in trades),
        "avg_mfe_pct": _mean(_num(t.get("mfe_pct")) for t in trades),
    }


# ── 1. exit-reason derivation + attribution ──────────────────────────────────


def derive_exit_reason(trade: dict, *, tick_tolerance: float = 0.6) -> str:
    """
    Classify why a closed trade exited, from data that already exists.

    Order of evidence:
      1. ``bracket_status`` if it carries a recognizable keyword
         (target/profit -> target; stop -> stop).
      2. ``exit_price`` proximity to ``take_profit`` / ``stop_loss``
         (within ``tick_tolerance`` * tick_size, approximated relatively when no
         spec is available).
      3. Otherwise ``manual`` when an exit price exists, ``unknown`` otherwise.

    Never guesses a direction it can't justify -- an unclassifiable exit is
    ``"unknown"``, which is the honest answer.
    """
    bs = str(trade.get("bracket_status") or "").strip().lower()
    if bs:
        if "target" in bs or "profit" in bs or "tp" == bs:
            return EXIT_TARGET
        if "stop" in bs or "sl" == bs:
            return EXIT_STOP

    exit_price = _num(trade.get("exit_price"))
    if exit_price is None:
        return EXIT_UNKNOWN

    is_long = _is_long(trade.get("side"))
    tp = _num(trade.get("take_profit"))
    sl = _num(trade.get("stop_loss"))

    # relative tolerance when we have no tick size: 0.05% of the exit price
    tol = max(abs(exit_price) * 0.0005, 1e-9)

    if is_long is True:
        if tp is not None and exit_price >= tp - tol:
            return EXIT_TARGET
        if sl is not None and exit_price <= sl + tol:
            return EXIT_STOP
    elif is_long is False:
        if tp is not None and exit_price <= tp + tol:
            return EXIT_TARGET
        if sl is not None and exit_price >= sl - tol:
            return EXIT_STOP

    # an exit happened but it matched neither bracket leg -> discretionary
    return EXIT_MANUAL


def exit_attribution(trades: list[dict]) -> dict:
    """P&L grouped by derived exit reason. Pure."""
    buckets: dict[str, list[dict]] = {c: [] for c in EXIT_CATEGORIES}
    for t in trades:
        buckets[derive_exit_reason(t)].append(t)

    by_reason = {
        reason: _pnl_block(ts) for reason, ts in buckets.items() if ts
    }
    return {
        "by_reason": by_reason,
        "overall": _pnl_block(trades),
        "classified_pct": round(
            sum(len(ts) for r, ts in buckets.items() if r != EXIT_UNKNOWN)
            / len(trades),
            4,
        )
        if trades
        else None,
    }


# ── 2. slippage attribution ──────────────────────────────────────────────────


def _slippage_usd(trade: dict, spec_lookup: Optional[SpecLookup]) -> Optional[float]:
    ticks = _num(trade.get("slippage_ticks"))
    if ticks is None:
        return None
    qty = abs(_num(trade.get("quantity")) or 1.0)
    tick_value = None
    if spec_lookup is not None:
        spec = spec_lookup(str(trade.get("symbol") or ""))
        if spec is not None:
            tick_value = getattr(spec, "tick_value", None)
            if callable(tick_value):  # property accessed on instance returns float
                tick_value = tick_value()
    if tick_value is None:
        return None
    return abs(ticks) * float(tick_value) * qty


def slippage_attribution(
    trades: list[dict], spec_lookup: Optional[SpecLookup] = None
) -> dict:
    """
    Execution-quality breakdown of recorded ``slippage_ticks``.

    Reports per-symbol slippage in ticks (avg / median / p90) and, when a
    contract spec is available, the dollar cost. ``slippage_ticks`` is NULL for
    simulated fills, so ``populated_count`` is reported alongside ``count`` --
    never conflated.
    """
    populated = [t for t in trades if _num(t.get("slippage_ticks")) is not None]

    def _group(ts: list[dict]) -> dict:
        ticks = [_num(t.get("slippage_ticks")) for t in ts]
        usds = [_slippage_usd(t, spec_lookup) for t in ts]
        usd_clean = [u for u in usds if u is not None]
        return {
            "count": len(ts),
            "avg_ticks": _mean(ticks),
            "median_ticks": _median(ticks),
            "p90_ticks": _percentile(ticks, 90),
            "total_slippage_usd": round(sum(usd_clean), 4) if usd_clean else None,
        }

    by_symbol: dict[str, dict] = {}
    syms = sorted({str(t.get("symbol") or "?") for t in populated})
    for sym in syms:
        by_symbol[sym] = _group([t for t in populated if str(t.get("symbol") or "?") == sym])

    usd_values = [
        u for u in (_slippage_usd(t, spec_lookup) for t in populated) if u is not None
    ]
    total_usd = sum(usd_values)
    total_pnl = sum(p for p in (_num(t.get("pnl")) for t in populated) if p is not None)

    return {
        "trade_count": len(trades),
        "populated_count": len(populated),
        "by_symbol": by_symbol,
        # None (not 0) when no contract spec was available to convert ticks ->
        # dollars: an uncomputable cost is "unknown", never a real zero.
        "total_slippage_usd": round(total_usd, 4) if usd_values else None,
        "slippage_pct_of_pnl": round(total_usd / abs(total_pnl), 4)
        if (usd_values and total_pnl)
        else None,
        "overall": _group(populated) if populated else None,
    }


# ── 3. losing-streak analysis ─────────────────────────────────────────────────


def losing_streak(trades: list[dict]) -> dict:
    """
    Consecutive-win/loss runs over closed trades, in chronological order.

    Scratch trades (pnl == 0 or None) break a run without counting as a win or
    a loss. ``worst_drawdown_run_usd`` is the most negative cumulative P&L of any
    single losing run (a streak-local drawdown, not the account peak-to-trough).
    """
    ordered = sorted(
        trades, key=lambda t: (str(t.get("exit_time") or t.get("entry_time") or ""))
    )

    max_loss_streak = 0
    max_win_streak = 0
    cur = 0  # signed: negative = losing run length, positive = winning run length
    worst_run_usd = 0.0
    cur_run_usd = 0.0

    for t in ordered:
        pnl = _num(t.get("pnl"))
        if pnl is None or pnl == 0:
            cur = 0
            cur_run_usd = 0.0
            continue
        if pnl < 0:
            cur = cur - 1 if cur < 0 else -1
            cur_run_usd = cur_run_usd + pnl if cur < -1 else pnl
            max_loss_streak = max(max_loss_streak, -cur)
            worst_run_usd = min(worst_run_usd, cur_run_usd)
        else:  # pnl > 0
            cur = cur + 1 if cur > 0 else 1
            cur_run_usd = 0.0
            max_win_streak = max(max_win_streak, cur)

    return {
        "trade_count": len(ordered),
        "max_consecutive_losses": max_loss_streak,
        "max_consecutive_wins": max_win_streak,
        "current_streak": cur,  # negative=losing, positive=winning, 0=scratch/none
        "worst_drawdown_run_usd": round(worst_run_usd, 4),
    }


# ── 4. per-trade P&L waterfall ────────────────────────────────────────────────


def pnl_waterfall(trade: dict, spec_lookup: Optional[SpecLookup] = None) -> dict:
    """
    Decompose a single trade into a chartable waterfall reusing MAE/MFE + pnl.

    Steps (USD): peak unrealized (MFE) -> realized -> "given back" (the delta
    from peak to realized). MAE is reported as the worst unrealized excursion for
    context, and recorded slippage cost is surfaced as an execution-quality
    figure. We do not reconstruct a synthetic gross from realized pnl (that would
    double-count); the waterfall is internally self-consistent from MFE.
    """
    pnl = _num(trade.get("pnl"))
    mfe_usd = _num(trade.get("mfe_usd"))
    mae_usd = _num(trade.get("mae_usd"))
    slip_usd = _slippage_usd(trade, spec_lookup)

    steps: list[dict] = []
    if mfe_usd is not None:
        steps.append({"label": "Peak (MFE)", "value": round(mfe_usd, 4)})
        if pnl is not None:
            steps.append({"label": "Given back", "value": round(pnl - mfe_usd, 4)})
    if pnl is not None:
        steps.append({"label": "Realized", "value": round(pnl, 4)})

    capture = None
    if mfe_usd is not None and mfe_usd > 0 and pnl is not None:
        capture = round(pnl / mfe_usd, 4)  # fraction of the peak actually kept

    return {
        "trade_id": str(trade.get("trade_id", "")),
        "symbol": str(trade.get("symbol", "")),
        "side": str(trade.get("side", "")),
        "exit_reason": derive_exit_reason(trade),
        "realized_pnl": round(pnl, 4) if pnl is not None else None,
        "mfe_usd": round(mfe_usd, 4) if mfe_usd is not None else None,
        "mae_usd": round(mae_usd, 4) if mae_usd is not None else None,
        "slippage_usd": round(slip_usd, 4) if slip_usd is not None else None,
        "mfe_capture_ratio": capture,
        "steps": steps,
    }


# ── 5. regime attribution ─────────────────────────────────────────────────────


def regime_attribution(trades: list[dict]) -> dict:
    """
    P&L grouped by the ``regime`` the trade was *entered* in (paper_trades.regime,
    migration 010). Distinct from the live market-regime *state* endpoints
    (/analytics/regime), which report the current detector reading.
    """
    buckets: dict[str, list[dict]] = {}
    for t in trades:
        key = str(t.get("regime") or "unknown").strip() or "unknown"
        buckets.setdefault(key, []).append(t)

    by_regime = {regime: _pnl_block(ts) for regime, ts in sorted(buckets.items())}
    return {
        "by_regime": by_regime,
        "overall": _pnl_block(trades),
        "regimes_observed": len(buckets),
    }
