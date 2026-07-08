"""Live AuctionDataProvider for GET /auction/bias/{symbol} (v3, HOST-ONLY).

Implements routers.auction_bias_router.AuctionDataProvider by stitching four
already-existing engine subsystems: MarketDataManager (price + bars), the
engine's own Wilder ATR, backtest.tpo_profile, and CoreyAuctionAnalystAgent.

NOT unit-tested in this session — it requires a live IB Gateway connection and
real market bars, neither available in the cloud dev container this was written
in. Structurally correct by inspection against the exact source interfaces (see
commit history / docs/design/es-auction-overnight-bias-card.md), but treat every
number as UNVERIFIED until the host smoke test below passes.

HOST SMOKE TEST (run after wiring into main.py — see the design doc's mount
snippet):
    curl -s localhost:8010/auction/bias/MES | jq
Then, with the live TOS chart open side-by-side, confirm:
  1. saty.atr matches the chart's ATR (was 102.16 on 2026-07-08).
  2. saty.call_trigger / put_trigger / plus_1_atr / minus_1_atr match the
     chart's Calls/Puts/+1 ATR/-1 ATR lines (this part is ALREADY covered by
     tests/test_auction_bias_parity.py once #1 confirms the ATR feed is right).
  3. tpo.fail_target is in the right ballpark vs the chart's "fail targets Y"
     line (exact match is NOT expected — see the class docstring below on why
     Corey's proprietary shelves are not reproduced).
Do not trust the payload for a real overnight decision until 1-2 pass.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from analysis.tpo_bias_mapping import row_to_tpo_dict
from backtest.indicators import wilder_atr
from backtest.tpo_profile import compute_tpo_profile

logger = logging.getLogger(__name__)

__all__ = ["LiveAuctionDataProvider"]

# Wilder ATR period used by the AA Saty ATR Levels ThinkScript study — see
# backtest/indicators.py:wilder_atr docstring ("used by Saty ATR Levels script").
SATY_ATR_PERIOD = 14
ATR_LOOKBACK_DAYS = 30  # enough daily bars for Wilder smoothing to converge
TPO_LOOKBACK_DAYS = 5   # enough intraday sessions for compute_tpo_profile's
                        # prior-session shift to have a defined current row


class LiveAuctionDataProvider:
    """Concrete AuctionDataProvider backed by the live MarketDataManager.

    IMPORTANT — what this does NOT reproduce: the chart's Corey
    AA_CoreyTscorev2 study ("Sellers in Control below X / Buyers offsides below
    Y", "This profile is failed") is a proprietary ThinkScript overlay with no
    API; this provider does not attempt to mirror those exact numbers. It
    instead surfaces two independent, real engine signals:
      - Saty ATR triggers/bias (verified in test_auction_bias_parity.py, given
        a correct ATR feed — see the smoke test above).
      - The engine's OWN generic TPO measured-move (backtest.tpo_profile),
        whose "failed" flag is grounded in that module's own target/fail_target
        algebra (see analysis/tpo_bias_mapping.py) — a genuine engine signal,
        not a mirror of Corey's chart study.
      - CoreyAuctionAnalystAgent's Discord-commentary-derived directional bias
        (bias/confidence/data_quality only). ``sellers_in_control_below`` /
        ``buyers_offside_below`` are deliberately left unset here: that agent's
        ``key_levels`` field has no confirmed semantic mapping to those two
        specific shelves, and guessing one would be exactly the
        confidently-wrong-number failure mode CLAUDE.md warns against. With
        them unset, analysis.auction_bias's line-in-the-sand priority falls
        through to the TPO fail_target, then the Saty put_trigger — both real.
    """

    def __init__(self, data_manager, corey_agent=None):
        self._data_manager = data_manager
        self._corey_agent = corey_agent  # lazily constructed on first use if None

    def _get_corey_agent(self):
        if self._corey_agent is None:
            # Local import: heavy dependency (LLM client factory), matches the
            # engine's lazy-import-for-heavy-deps convention.
            from agents.corey_auction_analyst import CoreyAuctionAnalystAgent

            self._corey_agent = CoreyAuctionAnalystAgent()
        return self._corey_agent

    @staticmethod
    def _indexed(df):
        """Attach a DatetimeIndex from the 'timestamp' column, as required by
        backtest.tpo_profile.compute_tpo_profile (data_manager.get_bars returns
        'timestamp' as a plain column, not an index)."""
        import pandas as pd

        out = df.copy()
        out.index = pd.to_datetime(out["timestamp"], utc=True)
        return out

    @staticmethod
    def _prior_close_from_daily(daily_df) -> Optional[float]:
        """The last COMPLETED prior session's close from daily bars — the anchor
        saty_atr_levels() actually needs, per the AA Saty study (prior session
        close, not a ticker's generic "prev_close").

        A ticker-level get_current_price() prev_close is NOT reliable for this:
        IBKR's snapshot fallback can return the previous 1-hour bar's close
        rather than the prior daily session's close, and TradingView/Schwab
        often return None entirely. Using it as the Saty anchor would silently
        shift call/put triggers off the chart's real levels.

        Robust to whether the daily-bar feed includes today's still-forming bar
        as the last row: filters to bars strictly before today's UTC date and
        takes the most recent of those. Falls back to the last bar only if no
        bar is strictly before today (feed already excludes the partial day).
        """
        import pandas as pd

        if daily_df is None or daily_df.empty:
            return None
        ts = pd.to_datetime(daily_df["timestamp"], utc=True)
        today = pd.Timestamp.now(tz="UTC").normalize()
        prior_mask = ts.dt.normalize() < today
        if prior_mask.any():
            return float(daily_df.loc[prior_mask, "close"].iloc[-1])
        return float(daily_df["close"].iloc[-1])

    async def get_inputs(self, symbol: str) -> Optional[dict]:
        dm = self._data_manager

        price_data = await dm.get_current_price(symbol, is_futures=True)
        price = price_data.get("last_price")
        source = price_data.get("source")

        atr: Optional[float] = None
        day_range: Optional[float] = None
        prior_close: Optional[float] = None
        try:
            daily_df = await dm.get_bars(
                symbol, lookback_days=ATR_LOOKBACK_DAYS, timeframe="1d", is_futures=True
            )
            if daily_df is not None and not daily_df.empty:
                prior_close = self._prior_close_from_daily(daily_df)
                if len(daily_df) >= SATY_ATR_PERIOD:
                    atr_series = wilder_atr(
                        daily_df["high"], daily_df["low"], daily_df["close"], period=SATY_ATR_PERIOD
                    )
                    atr = float(atr_series.iloc[-1])
                    last_bar = daily_df.iloc[-1]
                    day_range = float(last_bar["high"] - last_bar["low"])
        except Exception as exc:
            logger.warning("auction bias: daily bars fetch failed for %s: %s", symbol, exc)

        # Ticker prev_close is a fallback ONLY — daily bars are the reliable
        # prior-session-close source (see _prior_close_from_daily docstring).
        if prior_close is None:
            prior_close = price_data.get("prev_close")

        if price is None or prior_close is None:
            return None

        tpo: Optional[dict] = None
        try:
            intraday_df = await dm.get_bars(
                symbol, lookback_days=TPO_LOOKBACK_DAYS, timeframe="5m", is_futures=True
            )
            if intraday_df is not None and not intraday_df.empty:
                profile_df = compute_tpo_profile(self._indexed(intraday_df))
                row = profile_df.iloc[-1]
                tpo = row_to_tpo_dict(
                    close=float(price),
                    va_high=(None if row.get("va_high") != row.get("va_high") else float(row["va_high"])),
                    va_low=(None if row.get("va_low") != row.get("va_low") else float(row["va_low"])),
                    profile_target=(
                        None if row.get("tpo_target") != row.get("tpo_target") else float(row["tpo_target"])
                    ),
                    fail_target=(
                        None
                        if row.get("tpo_fail_target") != row.get("tpo_fail_target")
                        else float(row["tpo_fail_target"])
                    ),
                    imbalance=row.get("tpo_imbalance"),
                )
        except Exception as exc:
            logger.warning("auction bias: TPO fetch failed for %s: %s", symbol, exc)

        corey: Optional[dict] = None
        try:
            report = await self._get_corey_agent().analyze(
                symbol, current_price=float(price), atr=float(atr or 0.0)
            )
            corey = {
                "bias": report.directional_bias,
                "data_quality": "stale" if report.sentiment_stale else report.data_quality,
                # Deliberately NOT populated — see class docstring.
                "sellers_in_control_below": None,
                "buyers_offside_below": None,
            }
        except Exception as exc:
            logger.warning("auction bias: Corey analyst failed for %s: %s", symbol, exc)

        return {
            "price": float(price),
            "prior_close": float(prior_close),
            "atr": atr,
            "day_range": day_range,
            "tpo": tpo,
            "corey": corey,
            "source": source,
            "as_of": time.time(),
            "ibkr_connected": bool(dm.ibkr and dm.ibkr.is_connected),
        }
