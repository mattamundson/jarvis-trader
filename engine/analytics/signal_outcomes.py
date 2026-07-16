"""
JARVIS TRADER — Signal-outcome evaluation (pure).

Scores emitted pipeline signals against what the market subsequently did:
hit classification (target1/target2/stop/expired/open), MFE/MAE excursions,
and hypothetical P&L — the calibration feedback loop that answers "did our
predictions pay off?" independent of whether a trade was ever executed.

Ported from amo-arbitrage's `pipelines/signal_outcomes.py` scoring helpers,
adapted to jarvis's decision records. Rules preserved:

- PURE — operates on plain dicts/lists, no I/O, ``now`` is a parameter.
- Outcomes are EVALUATION TARGETS ONLY (testing.md point-in-time discipline):
  nothing here may feed back into a same-bar or future trading decision.
- Hypothetical fill model, stated not hidden: entry at the decision's
  entry_price on its decision date; exit at target_1 on a target hit
  (conservative 1R even when target_2 hit), at stop on a stop hit, else
  marked-to-last-close. Intra-bar ambiguity resolves to the STOP
  (pessimistic) when both stop and target are touched in the same bar.
- Missing data degrades to nulls / "open" — never fabricated.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

# A signal is evaluated only after this many calendar days, so early bars
# can't flatter it; younger signals stay honestly "open".
MIN_AGE_DAYS = 1

# A signal with no stop/target resolution after this many post-entry bars is
# "expired" — the thesis went nowhere within its useful life.
EXPIRY_BARS = 10


def _f(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_date(raw: Any) -> Optional[date]:
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


def bars_after(bars: list[dict], start: date) -> list[dict]:
    """Bars strictly after the decision date (the decision bar itself is
    excluded — using it would let the signal grade itself on same-bar data)."""
    out = []
    for b in bars:
        d = _to_date(b.get("timestamp") or b.get("date"))
        if d is not None and d > start:
            out.append(b)
    return out


def compute_hit_status(
    *,
    long: bool,
    stop: Optional[float],
    target_1: Optional[float],
    target_2: Optional[float],
    post_bars: list[dict],
) -> str:
    """Walk post-entry bars chronologically; first touch wins.

    Same-bar stop+target ambiguity resolves to the stop (pessimistic).
    No post bars => "open"; no touch within EXPIRY_BARS => "expired";
    still inside the expiry window with no touch => "open".
    """
    if not post_bars:
        return "open"
    sign = 1.0 if long else -1.0
    for i, bar in enumerate(post_bars):
        high = _f(bar.get("high"))
        low = _f(bar.get("low"))
        if high is None or low is None:
            continue
        favorable = high if long else low
        adverse = low if long else high
        if stop is not None and (adverse - stop) * sign <= 0:
            return "stop_hit"
        if target_2 is not None and (favorable - target_2) * sign >= 0:
            return "target2_hit"
        if target_1 is not None and (favorable - target_1) * sign >= 0:
            return "target1_hit"
        if i + 1 >= EXPIRY_BARS:
            return "expired"
    return "expired" if len(post_bars) >= EXPIRY_BARS else "open"


def compute_mfe_mae(
    *, long: bool, entry: float, post_bars: list[dict]
) -> tuple[Optional[float], Optional[float]]:
    """Max Favorable / Max Adverse Excursion as positive % of entry."""
    if not post_bars or entry == 0:
        return None, None
    highs = [h for h in (_f(b.get("high")) for b in post_bars) if h is not None]
    lows = [lo for lo in (_f(b.get("low")) for b in post_bars) if lo is not None]
    if not highs or not lows:
        return None, None
    if long:
        mfe = (max(highs) - entry) / entry * 100
        mae = (entry - min(lows)) / entry * 100
    else:
        mfe = (entry - min(lows)) / entry * 100
        mae = (max(highs) - entry) / entry * 100
    return round(max(mfe, 0.0), 4), round(max(mae, 0.0), 4)


def compute_pnl_pct(
    *,
    long: bool,
    entry: float,
    stop: Optional[float],
    target_1: Optional[float],
    hit: str,
    last_close: Optional[float],
) -> Optional[float]:
    """Hypothetical P&L %: exit at target_1 on any target hit (conservative
    1R), at stop on stop_hit, else mark to last close. None when unresolvable."""
    if entry == 0:
        return None
    if hit in ("target1_hit", "target2_hit") and target_1 is not None:
        exit_price = target_1
    elif hit == "stop_hit" and stop is not None:
        exit_price = stop
    elif last_close is not None:
        exit_price = last_close
    else:
        return None
    sign = 1.0 if long else -1.0
    return round((exit_price - entry) * sign / entry * 100, 4)


def evaluate_signal(decision: dict, bars: list[dict], *, now: date) -> dict:
    """Score one stored decision against subsequent daily bars.

    ``decision`` is a pending_trade_approvals row dict (parsed snapshot);
    ``bars`` are daily OHLC dicts for its symbol, any range covering the
    decision date onward. Younger than MIN_AGE_DAYS or missing geometry =>
    honest "open"/null outcome, never a guess.
    """
    snap = decision.get("pipeline_snapshot") or {}
    td = snap.get("trade_decision") or {}
    if not isinstance(td, dict):
        td = {}

    symbol = (decision.get("symbol") or "").upper()
    action = (decision.get("action") or "").lower()
    long = action != "sell"
    entry = _f(td.get("entry_price")) or _f(td.get("limit_price")) or _f(decision.get("entry_price"))
    stop = _f(td.get("stop_price"))
    target_1 = _f(td.get("target_1"))
    target_2 = _f(td.get("target_2"))
    decided = _to_date(decision.get("created_at"))

    base = {
        "approval_id": decision.get("approval_id"),
        "symbol": symbol,
        "direction": "long" if long else "short",
        "decision_date": decided.isoformat() if decided else None,
        "approval_status": decision.get("status"),
        "confidence": _f(td.get("confidence")),
        "entry_price": entry,
        "stop_loss": stop,
        "target_1": target_1,
        "target_2": target_2,
        "hit": "open",
        "mfe_pct": None,
        "mae_pct": None,
        "hypothetical_pnl_pct": None,
        "evaluable": False,
        "note": None,
    }

    if decided is None or entry is None:
        base["note"] = "missing decision date or entry level — not evaluable"
        return base
    if (now - decided).days < MIN_AGE_DAYS:
        base["note"] = f"younger than {MIN_AGE_DAYS}d — not yet evaluated"
        return base

    post = bars_after(bars, decided)
    if not post:
        base["note"] = "no post-decision bars available — not evaluated"
        return base

    hit = compute_hit_status(
        long=long, stop=stop, target_1=target_1, target_2=target_2, post_bars=post
    )
    mfe, mae = compute_mfe_mae(long=long, entry=entry, post_bars=post)
    last_close = _f(post[-1].get("close"))
    pnl = compute_pnl_pct(
        long=long, entry=entry, stop=stop, target_1=target_1, hit=hit,
        last_close=last_close,
    )

    base.update(
        hit=hit, mfe_pct=mfe, mae_pct=mae, hypothetical_pnl_pct=pnl,
        evaluable=True,
    )
    return base


def aggregate_outcomes(outcomes: list[dict]) -> dict:
    """Roll evaluated outcomes up to the headline numbers.

    hit_rate counts target1/target2 hits over RESOLVED outcomes (open ones
    can't be scored either way and are excluded from the denominator).
    """
    resolved = [o for o in outcomes if o.get("evaluable") and o.get("hit") != "open"]
    count_by_hit: dict[str, int] = {}
    for o in outcomes:
        key = o.get("hit") or "open"
        count_by_hit[key] = count_by_hit.get(key, 0) + 1

    hits = [o for o in resolved if o["hit"] in ("target1_hit", "target2_hit")]
    pnls = [o["hypothetical_pnl_pct"] for o in resolved if o.get("hypothetical_pnl_pct") is not None]

    return {
        "hit_rate": round(len(hits) / len(resolved) * 100, 2) if resolved else None,
        "avg_hypothetical_pnl_pct": round(sum(pnls) / len(pnls), 4) if pnls else None,
        "total_evaluated": len(resolved),
        "total_signals": len(outcomes),
        "count_by_hit": count_by_hit,
    }
