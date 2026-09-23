"""
JARVIS TRADER — Defined-risk options opportunity board
======================================================

Pure, read-only analytics that rank bounded-risk SPY/QQQ/VIX-style option
structures from an already-parsed option chain. This module is intentionally
analysis-only: no broker, no order routing, no account state, no config edits.

The board answers: given the delayed chain, which *payoff shapes* are even
worth reviewing? It does not claim a validated predictive edge. POP/EV are
market-implied proxies using call-delta interpolation, conservative bid/ask
pricing, and simple terminal-payoff math.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional, Protocol

CONTRACT_MULTIPLIER = 100.0
DEFAULT_WIDTH_PCT = 0.008  # ~0.8% of spot: near 5-wide on SPY, 4-5 wide on QQQ.
MAX_LEG_SPREAD_PCT = 0.35
MIN_OPEN_INTEREST = 1
MIN_REWARD_RISK = 0.15


class ChainContract(Protocol):
    expiry: date
    right: str  # "C" | "P"
    strike: float
    bid: Optional[float]
    ask: Optional[float]
    mid: Optional[float]
    delta: Optional[float]
    open_interest: int
    volume: int


@dataclass(frozen=True)
class LegQuote:
    right: str
    strike: float
    bid: float
    ask: float
    mid: float
    delta: Optional[float]
    open_interest: int
    volume: int


@dataclass(frozen=True)
class StructureCandidate:
    symbol: str
    expiry: str
    structure: str
    thesis: str
    legs: list[dict]
    net_price: float
    max_loss: float
    max_gain: float
    breakeven: float
    pop: Optional[float]
    ev: Optional[float]
    ev_to_max_loss: Optional[float]
    reward_to_risk: float
    liquidity_score: float
    score: float
    reject_reasons: list[str]
    journal_url: str
    journal_note: str


def _valid_quote(contract: ChainContract) -> Optional[LegQuote]:
    """Return a usable two-sided quote, or None.

    Conservative structure math requires both bid and ask. A contract with only
    last trade / theoretical value is intentionally rejected from the board.
    """
    bid = contract.bid
    ask = contract.ask
    mid = contract.mid
    if bid is None or ask is None or mid is None:
        return None
    if bid <= 0 or ask <= 0 or ask < bid or mid <= 0:
        return None
    return LegQuote(
        right=contract.right,
        strike=float(contract.strike),
        bid=float(bid),
        ask=float(ask),
        mid=float(mid),
        delta=contract.delta,
        open_interest=int(contract.open_interest or 0),
        volume=int(contract.volume or 0),
    )


def _contracts_by_right(
    contracts: Iterable[ChainContract], expiry: date
) -> tuple[list[LegQuote], list[LegQuote]]:
    calls: list[LegQuote] = []
    puts: list[LegQuote] = []
    for c in contracts:
        if c.expiry != expiry:
            continue
        leg = _valid_quote(c)
        if leg is None:
            continue
        if leg.right == "C":
            calls.append(leg)
        elif leg.right == "P":
            puts.append(leg)
    calls.sort(key=lambda x: x.strike)
    puts.sort(key=lambda x: x.strike)
    return calls, puts


def _p_above_interpolator(calls: list[LegQuote]):
    usable = sorted(
        (c for c in calls if c.delta is not None and 0.0 < float(c.delta) < 1.0),
        key=lambda c: c.strike,
    )
    strikes = [c.strike for c in usable]
    deltas = [float(c.delta) for c in usable]

    def interp(level: float) -> Optional[float]:
        if len(strikes) < 2 or level < strikes[0] or level > strikes[-1]:
            return None
        i = bisect_left(strikes, level)
        if i < len(strikes) and strikes[i] == level:
            return max(0.0, min(1.0, deltas[i]))
        k_lo, k_hi = strikes[i - 1], strikes[i]
        d_lo, d_hi = deltas[i - 1], deltas[i]
        if k_hi == k_lo:
            return None
        p = d_lo + (d_hi - d_lo) * (level - k_lo) / (k_hi - k_lo)
        return max(0.0, min(1.0, p))

    return interp


def _nearest_width(strikes: list[float], target_width: float) -> Optional[float]:
    widths = sorted({round(abs(b - a), 6) for i, a in enumerate(strikes) for b in strikes[i + 1 :]})
    if not widths:
        return None
    viable = [w for w in widths if w >= max(1.0, target_width * 0.5)]
    source = viable or widths
    return min(source, key=lambda w: abs(w - target_width))


def _find_leg(legs: list[LegQuote], strike: float) -> Optional[LegQuote]:
    return next((leg for leg in legs if abs(leg.strike - strike) < 1e-9), None)


def _leg_spread_pct(leg: LegQuote) -> float:
    return (leg.ask - leg.bid) / leg.mid if leg.mid > 0 else 1.0


def _liquidity_score(*legs: LegQuote) -> tuple[float, list[str]]:
    reasons: list[str] = []
    if not legs:
        return 0.0, ["no legs"]
    max_spread = max(_leg_spread_pct(leg) for leg in legs)
    if max_spread > MAX_LEG_SPREAD_PCT:
        reasons.append(f"wide bid/ask spread ({max_spread:.0%})")
    min_oi = min(leg.open_interest for leg in legs)
    if min_oi < MIN_OPEN_INTEREST:
        reasons.append("open interest below floor")
    volume_total = sum(max(0, leg.volume) for leg in legs)
    spread_component = max(0.0, 1.0 - max_spread / MAX_LEG_SPREAD_PCT)
    oi_component = min(1.0, min_oi / 100.0)
    volume_component = min(1.0, volume_total / 200.0)
    score = 0.65 * spread_component + 0.25 * oi_component + 0.10 * volume_component
    return round(score, 4), reasons


def _journal_payload(
    *,
    symbol: str,
    expiry: date,
    structure: str,
    max_loss: float,
    max_gain: float,
    breakeven: float,
    pop: Optional[float],
    ev_to_loss: Optional[float],
) -> tuple[str, str]:
    pop_s = f"{pop:.1%}" if pop is not None else "n/a"
    ev_s = f"{ev_to_loss:.1%}" if ev_to_loss is not None else "n/a"
    note = (
        f"ANALYSIS_ONLY options review: {symbol} {structure.replace('_', ' ')} exp {expiry.isoformat()} | "
        f"max_loss=${max_loss:.0f} max_gain=${max_gain:.0f} breakeven={breakeven:.2f} | "
        f"POP={pop_s} EV/max_loss={ev_s} | "
        "source=delayed CBOE chain; manual/paper review only; no execution instruction."
    )
    return "/journal?source=options-opportunity-board", note


def _candidate(
    *,
    symbol: str,
    expiry: date,
    structure: str,
    thesis: str,
    long_leg: LegQuote,
    short_leg: LegQuote,
    net_price: float,
    max_loss: float,
    max_gain: float,
    breakeven: float,
    pop: Optional[float],
    reject_reasons: Optional[list[str]] = None,
) -> StructureCandidate:
    reasons = list(reject_reasons or [])
    if max_loss <= 0:
        reasons.append("non-positive max loss")
    if max_gain <= 0:
        reasons.append("non-positive max gain")
    reward_to_risk = (max_gain / max_loss) if max_loss > 0 else 0.0
    if reward_to_risk < MIN_REWARD_RISK:
        reasons.append(f"reward/risk below floor ({reward_to_risk:.2f})")
    liq, liq_reasons = _liquidity_score(long_leg, short_leg)
    reasons.extend(liq_reasons)

    ev: Optional[float] = None
    ev_to_loss: Optional[float] = None
    if pop is not None and max_loss > 0:
        ev = pop * max_gain - (1.0 - pop) * max_loss
        ev_to_loss = ev / max_loss

    score = 0.0
    if ev_to_loss is not None:
        score += ev_to_loss
    score += 0.35 * liq
    score += min(1.0, reward_to_risk) * 0.15
    if reasons:
        score -= 0.75 + 0.25 * len(reasons)

    journal_url, journal_note = _journal_payload(
        symbol=symbol,
        expiry=expiry,
        structure=structure,
        max_loss=max_loss,
        max_gain=max_gain,
        breakeven=breakeven,
        pop=pop,
        ev_to_loss=ev_to_loss,
    )

    return StructureCandidate(
        symbol=symbol,
        expiry=expiry.isoformat(),
        structure=structure,
        thesis=thesis,
        legs=[
            {
                "action": "BUY",
                "right": long_leg.right,
                "strike": long_leg.strike,
                "bid": long_leg.bid,
                "ask": long_leg.ask,
                "mid": long_leg.mid,
                "delta": long_leg.delta,
            },
            {
                "action": "SELL",
                "right": short_leg.right,
                "strike": short_leg.strike,
                "bid": short_leg.bid,
                "ask": short_leg.ask,
                "mid": short_leg.mid,
                "delta": short_leg.delta,
            },
        ],
        net_price=round(net_price, 4),
        max_loss=round(max_loss, 2),
        max_gain=round(max_gain, 2),
        breakeven=round(breakeven, 4),
        pop=round(pop, 4) if pop is not None else None,
        ev=round(ev, 2) if ev is not None else None,
        ev_to_max_loss=round(ev_to_loss, 4) if ev_to_loss is not None else None,
        reward_to_risk=round(reward_to_risk, 4),
        liquidity_score=liq,
        score=round(score, 4),
        reject_reasons=reasons,
        journal_url=journal_url,
        journal_note=journal_note,
    )


def _serialize(candidate: StructureCandidate) -> dict:
    return {
        "symbol": candidate.symbol,
        "expiry": candidate.expiry,
        "structure": candidate.structure,
        "thesis": candidate.thesis,
        "legs": candidate.legs,
        "net_price": candidate.net_price,
        "max_loss": candidate.max_loss,
        "max_gain": candidate.max_gain,
        "breakeven": candidate.breakeven,
        "pop": candidate.pop,
        "ev": candidate.ev,
        "ev_to_max_loss": candidate.ev_to_max_loss,
        "reward_to_risk": candidate.reward_to_risk,
        "liquidity_score": candidate.liquidity_score,
        "score": candidate.score,
        "reject_reasons": candidate.reject_reasons,
        "journal_url": candidate.journal_url,
        "journal_note": candidate.journal_note,
    }


def build_opportunity_board(
    symbol: str,
    contracts: Iterable[ChainContract],
    expiry: date,
    spot: float,
    *,
    max_candidates: int = 8,
) -> dict:
    """Rank bounded-risk structures for one symbol/expiry.

    Pricing convention is deliberately conservative:
    - debit spreads pay long ask and receive short bid;
    - credit spreads receive short bid and pay long ask;
    - all dollar payoffs use a 100-share contract multiplier.
    """
    calls, puts = _contracts_by_right(contracts, expiry)
    p_above = _p_above_interpolator(calls)
    candidates: list[StructureCandidate] = []
    reject_summary: list[str] = []

    if len(calls) < 2 or len(puts) < 2:
        return {
            "symbol": symbol,
            "expiry": expiry.isoformat(),
            "spot": round(spot, 4),
            "status": "degraded",
            "source": "CBOE delayed quotes",
            "source_confidence": 0.0,
            "source_notes": ["insufficient two-sided call/put quotes", "15-minute delayed public feed"],
            "candidate_count": 0,
            "rejected_count": 0,
            "candidates": [],
            "reject_summary": ["insufficient two-sided call/put quotes"],
            "disclaimer": "Analysis-only defined-risk board from delayed options quotes; not a trade signal.",
        }

    target_width = max(1.0, spot * DEFAULT_WIDTH_PCT)
    call_width = _nearest_width([c.strike for c in calls], target_width)
    put_width = _nearest_width([p.strike for p in puts], target_width)

    # Bull call debit spread: buy near-ATM/lower call, sell higher call.
    if call_width is not None:
        long_calls = [c for c in calls if c.strike <= spot and c.delta is not None]
        if long_calls:
            long_call = max(long_calls, key=lambda c: c.strike)
            short_call = _find_leg(calls, long_call.strike + call_width)
            if short_call:
                debit = long_call.ask - short_call.bid
                width = short_call.strike - long_call.strike
                be = long_call.strike + debit
                pop = p_above(be)
                candidates.append(
                    _candidate(
                        symbol=symbol,
                        expiry=expiry,
                        structure="BULL_CALL_DEBIT_SPREAD",
                        thesis="upside participation with bounded debit risk",
                        long_leg=long_call,
                        short_leg=short_call,
                        net_price=debit,
                        max_loss=debit * CONTRACT_MULTIPLIER,
                        max_gain=(width - debit) * CONTRACT_MULTIPLIER,
                        breakeven=be,
                        pop=pop,
                    )
                )
            else:
                reject_summary.append("bull call: no matching upper call leg")

        # Call credit spread: sell OTM call, buy higher call.
        short_calls = [c for c in calls if c.strike > spot and c.delta is not None and 0.15 <= c.delta <= 0.45]
        if short_calls:
            short_call = min(short_calls, key=lambda c: abs((c.delta or 0) - 0.30))
            long_call = _find_leg(calls, short_call.strike + call_width)
            if long_call:
                credit = short_call.bid - long_call.ask
                width = long_call.strike - short_call.strike
                be = short_call.strike + credit
                p_close_above = p_above(be)
                pop = (1.0 - p_close_above) if p_close_above is not None else None
                candidates.append(
                    _candidate(
                        symbol=symbol,
                        expiry=expiry,
                        structure="CALL_CREDIT_SPREAD",
                        thesis="defined-risk bearish/neutral premium sale",
                        long_leg=long_call,
                        short_leg=short_call,
                        net_price=credit,
                        max_loss=(width - credit) * CONTRACT_MULTIPLIER,
                        max_gain=credit * CONTRACT_MULTIPLIER,
                        breakeven=be,
                        pop=pop,
                    )
                )
            else:
                reject_summary.append("call credit: no matching protection leg")

    if put_width is not None:
        # Bear put debit spread: buy near-ATM/higher put, sell lower put.
        long_puts = [p for p in puts if p.strike >= spot and p.delta is not None]
        if long_puts:
            long_put = min(long_puts, key=lambda p: p.strike)
            short_put = _find_leg(puts, long_put.strike - put_width)
            if short_put:
                debit = long_put.ask - short_put.bid
                width = long_put.strike - short_put.strike
                be = long_put.strike - debit
                p_close_above = p_above(be)
                pop = (1.0 - p_close_above) if p_close_above is not None else None
                candidates.append(
                    _candidate(
                        symbol=symbol,
                        expiry=expiry,
                        structure="BEAR_PUT_DEBIT_SPREAD",
                        thesis="downside participation with bounded debit risk",
                        long_leg=long_put,
                        short_leg=short_put,
                        net_price=debit,
                        max_loss=debit * CONTRACT_MULTIPLIER,
                        max_gain=(width - debit) * CONTRACT_MULTIPLIER,
                        breakeven=be,
                        pop=pop,
                    )
                )
            else:
                reject_summary.append("bear put: no matching lower put leg")

        # Put credit spread: sell OTM put, buy lower put.
        short_puts = [p for p in puts if p.strike < spot and p.delta is not None and 0.15 <= abs(p.delta) <= 0.45]
        if short_puts:
            short_put = min(short_puts, key=lambda p: abs(abs(p.delta or 0) - 0.30))
            long_put = _find_leg(puts, short_put.strike - put_width)
            if long_put:
                credit = short_put.bid - long_put.ask
                width = short_put.strike - long_put.strike
                be = short_put.strike - credit
                pop = p_above(be)
                candidates.append(
                    _candidate(
                        symbol=symbol,
                        expiry=expiry,
                        structure="PUT_CREDIT_SPREAD",
                        thesis="defined-risk bullish/neutral premium sale",
                        long_leg=long_put,
                        short_leg=short_put,
                        net_price=credit,
                        max_loss=(width - credit) * CONTRACT_MULTIPLIER,
                        max_gain=credit * CONTRACT_MULTIPLIER,
                        breakeven=be,
                        pop=pop,
                    )
                )
            else:
                reject_summary.append("put credit: no matching protection leg")

    accepted = [c for c in candidates if not c.reject_reasons]
    rejected = [c for c in candidates if c.reject_reasons]
    ranked = sorted(accepted or candidates, key=lambda c: c.score, reverse=True)[:max_candidates]
    status = "ok" if accepted else "degraded"
    if candidates and not accepted:
        reject_summary.append("all candidates rejected by quality filters")
    if not candidates:
        reject_summary.append("no bounded-risk candidates found")
    source_confidence = 0.0
    if accepted:
        source_confidence = min(1.0, sum(c.liquidity_score for c in accepted) / len(accepted))
    elif candidates:
        source_confidence = min(0.5, max(c.liquidity_score for c in candidates) * 0.5)
    source_notes = [
        "CBOE 15-minute delayed chain",
        f"{len(accepted)} accepted / {len(rejected)} rejected candidates",
        "POP/EV are risk-neutral approximations, not calibrated edge",
    ]

    return {
        "symbol": symbol,
        "expiry": expiry.isoformat(),
        "spot": round(spot, 4),
        "status": status,
        "source": "CBOE delayed quotes",
        "source_confidence": round(source_confidence, 4),
        "source_notes": source_notes,
        "candidate_count": len(accepted),
        "rejected_count": len(rejected),
        "candidates": [_serialize(c) for c in ranked],
        "rejected_candidates": [_serialize(c) for c in sorted(rejected, key=lambda c: c.score, reverse=True)[:max_candidates]],
        "reject_summary": reject_summary,
        "disclaimer": "Analysis-only defined-risk board from delayed options quotes; not a trade signal.",
    }
