"""Deterministic ES/MES auction overnight-bias synthesis.

Pure, no-I/O, no-LLM synthesis that combines the engine's own Saty ATR levels
(``backtest.indicators.saty_atr_levels``) with a TPO profile read and an ingested
Corey commentary read into a single "line-in-the-sand" overnight-bias payload for
the dashboard AuctionBiasCard.

This is decision-support ONLY. It never sizes or routes an order, and it is
explicitly engine-derived, NOT a mirror of the ThinkOrSwim chart (the AA_CoreyTscorev2
and AA Saty studies are thinkScript with no API — see
docs/design/es-auction-overnight-bias-card.md).

The output is gated by tests/test_auction_bias_parity.py, which pins the Saty portion
to a known live screenshot within +/-1 tick so this module can never render a
confidently-wrong number.
"""

from __future__ import annotations

from typing import Optional

from backtest.indicators import saty_atr_levels, saty_bias, saty_nearest_target

__all__ = ["synthesize_auction_bias", "RANGE_EXHAUSTED_PCT"]

# Day range >= this fraction of ATR => the session has largely spent its expected
# range; continuation has little statistical room left, so we suppress a directional
# overnight lean regardless of the intraday bias.
RANGE_EXHAUSTED_PCT = 0.90


def _line_in_the_sand(
    saty_levels: dict,
    tpo: Optional[dict],
    corey: Optional[dict],
) -> tuple[float, str]:
    """The pivot that flips the overnight lean, most-specific source first.

    Priority: Corey "buyers offside below" shelf -> TPO fail-target -> Saty put
    trigger. Returns (level, source_label).
    """
    if corey and corey.get("buyers_offside_below") is not None:
        return float(corey["buyers_offside_below"]), "corey_buyers_offside"
    if tpo and tpo.get("fail_target") is not None:
        return float(tpo["fail_target"]), "tpo_fail_target"
    return float(saty_levels["put_trigger"]), "saty_put_trigger"


def _confirm_long_above(saty_levels: dict, corey: Optional[dict]) -> float:
    """Level whose reclaim upgrades the read to a clean long (sellers lose control)."""
    if corey and corey.get("sellers_in_control_below") is not None:
        return float(corey["sellers_in_control_below"])
    return float(saty_levels["call_trigger"])


def _lean(bias: str, range_exhausted: bool, tpo_failed: bool) -> tuple[str, str]:
    """(lean, overnight_recommendation). Range exhaustion forces flat overnight."""
    if range_exhausted:
        return (
            f"{bias} intraday / flat overnight",
            "no-edge / stand aside — range exhausted, do not carry direction overnight",
        )
    if bias == "neutral":
        return "neutral", "no-edge / stand aside — price inside the trigger band"
    tag = " (profile failed)" if tpo_failed and bias == "short" else ""
    return bias, f"lean {bias}{tag} — trade the level, size small, honor invalidation"


def synthesize_auction_bias(
    symbol: str,
    price: float,
    prior_close: float,
    atr: float,
    day_range: Optional[float] = None,
    tpo: Optional[dict] = None,
    corey: Optional[dict] = None,
) -> dict:
    """Synthesize the deterministic auction / overnight-bias payload.

    Args:
        symbol: micro contract, e.g. "MES".
        price: last traded price.
        prior_close: prior-session close (Saty anchor).
        atr: ATR used by the Saty study (same period/session as the chart).
        day_range: session high-low, for the range-exhaustion flag.
        tpo: optional {value_area, profile_target, fail_target, failed}.
        corey: optional {bias, sellers_in_control_below, buyers_offside_below,
            data_quality} from ingested commentary (nullable / may be stale).

    Returns:
        A JSON-serializable dict. All numeric outputs derive from ``prior_close``,
        ``atr``, ``price`` and the passed structural levels — never hardcoded.
    """
    saty = saty_atr_levels(prior_close, atr)
    bias = saty_bias(price, saty)

    range_pct = (day_range / atr) if (day_range and atr > 0) else None
    range_exhausted = bool(range_pct is not None and range_pct >= RANGE_EXHAUSTED_PCT)

    line, line_src = _line_in_the_sand(saty, tpo, corey)
    confirm_long = _confirm_long_above(saty, corey)
    confirm_short = saty_nearest_target(price, "short", saty)
    tpo_failed = bool(tpo and tpo.get("failed"))
    lean, overnight = _lean(bias, range_exhausted, tpo_failed)

    caveats: list[str] = []
    if range_exhausted and range_pct is not None:
        caveats.append(f"day range {range_pct * 100:.0f}% of ATR — exhausted")
    corey_quality = (corey or {}).get("data_quality")
    if not corey or corey_quality in ("stale", "none", None):
        caveats.append("corey commentary stale/absent — bias is Saty+TPO only")
    if tpo_failed:
        caveats.append("TPO profile failed — downside fail-target in play")

    return {
        "symbol": symbol,
        "price": round(float(price), 2),
        "prior_close": round(float(prior_close), 2),
        "saty": {
            "atr": round(saty["atr"], 4),
            "call_trigger": round(saty["call_trigger"], 2),
            "put_trigger": round(saty["put_trigger"], 2),
            "plus_1_atr": round(saty["upper"][1.0], 2),
            "minus_1_atr": round(saty["lower"][1.0], 2),
            "bias": bias,
            "day_range_pct_of_atr": round(range_pct, 4) if range_pct is not None else None,
        },
        "tpo": tpo,
        "corey": corey,
        "synthesis": {
            "line_in_sand": round(line, 2),
            "line_source": line_src,
            "long_above": round(line, 2),
            "short_below": round(line, 2),
            "confirm_long_above": round(confirm_long, 2),
            "confirm_short_below": round(confirm_short, 2) if confirm_short is not None else None,
            "lean": lean,
            "overnight_recommendation": overnight,
        },
        "engine_derived": True,
        "chart_parity": False,
        "caveats": caveats,
    }
