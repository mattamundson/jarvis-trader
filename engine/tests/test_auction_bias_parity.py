"""Parity gate for the ES auction / overnight-bias synthesis.

Pins the synthesized payload to a known live ThinkOrSwim /ES screenshot
(2026-07-08, ~2:35 PM ET) within +/-1 tick, closing the end-to-end
numeric-accuracy gap called out in CLAUDE.md. The AuctionBiasCard endpoint
ships only while this stays green.

Screenshot transcription (AA Saty + AA_CoreyTscorev2 overlays):
    Calls > 7575.86  | +1 ATR 7653.91
    Puts  < 7527.64  | -1 ATR 7449.59
    Day Range ($94.5) is 93% of ATR ($102.16)
    Last 7526.75
    Sellers in Control below 7546.25 ; Buyers offsides below 7530.75
    Profile targets 7624.25 / fail target 7529.75 ; profile failed ; value 7500
"""

from __future__ import annotations

from analysis.auction_bias import synthesize_auction_bias

TICK = 0.25  # ES/MES tick — parity tolerance

# Saty anchors solved from the on-chart triggers (midpoint = prior_close,
# half-spread / 0.236 = ATR). Verified to reproduce all four Saty prints.
PRIOR_CLOSE = 7551.75
ATR = 102.161
PRICE = 7526.75
DAY_RANGE = 94.5

COREY = {
    "bias": "bearish",
    "sellers_in_control_below": 7546.25,
    "buyers_offside_below": 7530.75,
    "data_quality": "stale",
}
TPO = {
    "value_area": 7500,
    "profile_target": 7624.25,
    "fail_target": 7529.75,
    "failed": True,
}


def _payload():
    return synthesize_auction_bias(
        symbol="MES",
        price=PRICE,
        prior_close=PRIOR_CLOSE,
        atr=ATR,
        day_range=DAY_RANGE,
        tpo=TPO,
        corey=COREY,
    )


def test_saty_levels_match_screenshot_within_one_tick():
    saty = _payload()["saty"]
    assert abs(saty["call_trigger"] - 7575.86) <= TICK
    assert abs(saty["put_trigger"] - 7527.64) <= TICK
    assert abs(saty["plus_1_atr"] - 7653.91) <= TICK
    assert abs(saty["minus_1_atr"] - 7449.59) <= TICK


def test_saty_bias_is_short_below_put_trigger():
    # Last (7526.75) prints just below the put trigger (7527.64) => short.
    assert _payload()["saty"]["bias"] == "short"


def test_range_exhaustion_flag():
    saty = _payload()["saty"]
    # 94.5 / 102.161 = 0.925 -> exhausted (>= 0.90)
    assert abs(saty["day_range_pct_of_atr"] - 0.925) <= 0.01


def test_line_in_the_sand_prefers_corey_offside_shelf():
    syn = _payload()["synthesis"]
    assert abs(syn["line_in_sand"] - 7530.75) <= TICK
    assert syn["line_source"] == "corey_buyers_offside"


def test_confirmations():
    syn = _payload()["synthesis"]
    # Reclaim of sellers-in-control shelf upgrades to long.
    assert abs(syn["confirm_long_above"] - 7546.25) <= TICK
    # Nearest Saty level below price is the short confirmation (7512.72).
    assert abs(syn["confirm_short_below"] - 7512.72) <= TICK


def test_lean_is_flat_overnight_when_range_exhausted():
    syn = _payload()["synthesis"]
    assert syn["lean"] == "short intraday / flat overnight"
    assert "stand aside" in syn["overnight_recommendation"]


def test_stale_corey_is_flagged_in_caveats():
    caveats = " ".join(_payload()["caveats"])
    assert "exhausted" in caveats
    assert "corey" in caveats.lower()
    assert "failed" in caveats.lower()


def test_payload_is_labeled_engine_derived_not_chart_parity():
    p = _payload()
    assert p["engine_derived"] is True
    assert p["chart_parity"] is False
