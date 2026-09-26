"""
JARVIS TRADER -- Causal market-state snapshot
=============================================
Turns raw bars / top-of-book / account state into one compact numeric snapshot
that is the ONLY thing a reflex judge is shown.

Point-in-time discipline (see .claude/rules/testing.md "No look-ahead bias"):

* Bars are keyed by ``close_ts`` -- the moment the bar's OHLC became knowable.
  A bar stamped with its *open* time is not complete until the interval ends;
  using open-stamped bars here would leak up to one full bar of future data.
* Every bar and quote must satisfy ``ts <= as_of`` or :class:`CausalityError`
  is raised. There is no "drop the future rows and carry on" path: a leak is a
  bug upstream, and silently trimming it would hide that bug from backtests.
* All derived fields are computed here in code. The judge never computes a
  number it is later judged on.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence

__all__ = [
    "Bar",
    "Quote",
    "AccountState",
    "MarketSnapshot",
    "CausalityError",
    "build_snapshot",
    "SNAPSHOT_TOKEN_BUDGET",
]

# The judge prompt budget for the state block. Checked by tests and by
# ``MarketSnapshot.token_estimate`` so the snapshot cannot silently bloat.
SNAPSHOT_TOKEN_BUDGET = 400
# Rough chars-per-token for compact JSON; deliberately pessimistic (real
# tokenizers average ~3.5-4 on numeric JSON).
_CHARS_PER_TOKEN = 3.0
_BPS = 10_000.0
DEFAULT_RV_WINDOW = 20
DEFAULT_ATR_WINDOW = 14
DEFAULT_MOMENTUM_WINDOW = 10


class CausalityError(ValueError):
    """An input carried a timestamp later than the decision time."""


@dataclass(frozen=True)
class Bar:
    close_ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass(frozen=True)
class Quote:
    ts: datetime
    bid: float
    ask: float
    bid_size: float = 0.0
    ask_size: float = 0.0


@dataclass(frozen=True)
class AccountState:
    ts: datetime
    equity: float
    peak_equity: float
    day_start_equity: float
    position: int = 0  # signed contracts; + long, - short


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    as_of: datetime
    last: float
    mid: Optional[float]
    spread_bps: Optional[float]
    imbalance: Optional[float]  # (bid_size - ask_size) / (bid_size + ask_size), in [-1, 1]
    quote_age_s: Optional[float]
    rv_bps: float  # stdev of 1-bar log returns over the window, in bps
    atr: float  # points
    momentum_bps: float  # log return over the momentum window, in bps
    bars_used: int
    position: int
    drawdown_pct: float  # from peak equity, positive number
    daily_pnl_pct: float  # vs day-start equity, signed

    def to_compact(self) -> dict:
        """Short-keyed, rounded dict -- what the judge actually sees."""

        def r(x: Optional[float], nd: int = 2) -> Optional[float]:
            return None if x is None else round(x, nd)

        return {
            "sym": self.symbol,
            "t": self.as_of.isoformat(timespec="seconds"),
            "px": r(self.last, 4),
            "mid": r(self.mid, 4),
            "spr_bps": r(self.spread_bps),
            "imb": r(self.imbalance, 3),
            "q_age_s": r(self.quote_age_s, 1),
            "rv_bps": r(self.rv_bps),
            "atr": r(self.atr, 4),
            "mom_bps": r(self.momentum_bps),
            "n": self.bars_used,
            "pos": self.position,
            "dd_pct": r(self.drawdown_pct),
            "day_pct": r(self.daily_pnl_pct),
        }

    def to_prompt_json(self) -> str:
        return json.dumps(self.to_compact(), separators=(",", ":"))

    def token_estimate(self) -> int:
        return math.ceil(len(self.to_prompt_json()) / _CHARS_PER_TOKEN)


def _check_causal(bars: Sequence[Bar], quote: Optional[Quote], account: AccountState, as_of: datetime) -> None:
    prev: Optional[datetime] = None
    for b in bars:
        if b.close_ts > as_of:
            raise CausalityError(f"bar close_ts {b.close_ts.isoformat()} is after as_of {as_of.isoformat()}")
        if prev is not None and b.close_ts <= prev:
            raise CausalityError(f"bars not strictly increasing at {b.close_ts.isoformat()}")
        prev = b.close_ts
    if quote is not None and quote.ts > as_of:
        raise CausalityError(f"quote ts {quote.ts.isoformat()} is after as_of {as_of.isoformat()}")
    if account.ts > as_of:
        raise CausalityError(f"account ts {account.ts.isoformat()} is after as_of {as_of.isoformat()}")


def _log_returns(closes: Sequence[float]) -> list[float]:
    return [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0 and closes[i] > 0]


def _stdev(xs: Sequence[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _atr(bars: Sequence[Bar], window: int) -> float:
    trs = []
    for i in range(1, len(bars)):
        h, lo, pc = bars[i].high, bars[i].low, bars[i - 1].close
        trs.append(max(h - lo, abs(h - pc), abs(lo - pc)))
    tail = trs[-window:]
    return sum(tail) / len(tail) if tail else 0.0


def _quote_fields(quote: Optional[Quote], as_of: datetime) -> tuple:
    if quote is None or quote.bid <= 0 or quote.ask <= 0 or quote.ask < quote.bid:
        return None, None, None, None
    mid = (quote.bid + quote.ask) / 2.0
    spread_bps = (quote.ask - quote.bid) / mid * _BPS
    depth = quote.bid_size + quote.ask_size
    imbalance = (quote.bid_size - quote.ask_size) / depth if depth > 0 else None
    age = (as_of - quote.ts).total_seconds()
    return mid, spread_bps, imbalance, age


def build_snapshot(
    symbol: str,
    as_of: datetime,
    bars: Sequence[Bar],
    account: AccountState,
    quote: Optional[Quote] = None,
    rv_window: int = DEFAULT_RV_WINDOW,
    atr_window: int = DEFAULT_ATR_WINDOW,
    momentum_window: int = DEFAULT_MOMENTUM_WINDOW,
) -> MarketSnapshot:
    """Build the snapshot. Raises :class:`CausalityError` on any future-dated
    input and ``ValueError`` if there are fewer than two bars."""
    if len(bars) < 2:
        raise ValueError("need at least 2 bars to build a snapshot")
    _check_causal(bars, quote, account, as_of)

    closes = [b.close for b in bars]
    rets = _log_returns(closes)
    mom_n = min(momentum_window, len(closes) - 1)
    momentum = math.log(closes[-1] / closes[-1 - mom_n]) if closes[-1 - mom_n] > 0 else 0.0
    mid, spread_bps, imbalance, age = _quote_fields(quote, as_of)

    peak = max(account.peak_equity, account.equity)
    drawdown_pct = (peak - account.equity) / peak * 100.0 if peak > 0 else 0.0
    day_pct = (
        (account.equity - account.day_start_equity) / account.day_start_equity * 100.0
        if account.day_start_equity > 0
        else 0.0
    )
    return MarketSnapshot(
        symbol=symbol,
        as_of=as_of,
        last=closes[-1],
        mid=mid,
        spread_bps=spread_bps,
        imbalance=imbalance,
        quote_age_s=age,
        rv_bps=_stdev(rets[-rv_window:]) * _BPS,
        atr=_atr(bars, atr_window),
        momentum_bps=momentum * _BPS,
        bars_used=len(bars),
        position=account.position,
        drawdown_pct=drawdown_pct,
        daily_pnl_pct=day_pct,
    )
