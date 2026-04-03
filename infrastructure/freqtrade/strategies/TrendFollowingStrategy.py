"""
TrendFollowingStrategy — EMA crossover on 4h timeframe.
Enters long when: EMA21 crosses above EMA55 AND ADX > 25 (strong trend).
Exits on: EMA21 crosses below EMA55 OR trailing stop.

Works best in trending markets. Use with MeanReversionStrategy for diversification.
"""
from __future__ import annotations

import talib.abstract as ta
from freqtrade.strategy import IStrategy, IntParameter
from pandas import DataFrame


class TrendFollowingStrategy(IStrategy):
    """
    Trend following strategy using EMA crossover + ADX trend filter.
    Higher timeframe (4h) = fewer signals, higher quality.
    """

    INTERFACE_VERSION = 3

    minimal_roi = {
        "0": 0.08,
        "240": 0.04,
        "480": 0.02,
        "720": 0,
    }

    stoploss = -0.07
    trailing_stop = True
    trailing_stop_positive = 0.03
    trailing_stop_positive_offset = 0.06
    trailing_only_offset_is_reached = True

    timeframe = "4h"
    process_only_new_candles = True
    startup_candle_count = 60

    fast_ema = IntParameter(15, 30, default=21, space="buy")
    slow_ema = IntParameter(40, 70, default=55, space="buy")
    adx_threshold = IntParameter(20, 35, default=25, space="buy")

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=self.fast_ema.value)
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=self.slow_ema.value)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)

        # Previous candle values for crossover detection
        dataframe["ema_fast_prev"] = dataframe["ema_fast"].shift(1)
        dataframe["ema_slow_prev"] = dataframe["ema_slow"].shift(1)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                # Golden cross: fast EMA crosses above slow EMA
                (dataframe["ema_fast"] > dataframe["ema_slow"]) &
                (dataframe["ema_fast_prev"] <= dataframe["ema_slow_prev"]) &
                # Strong trend filter
                (dataframe["adx"] > self.adx_threshold.value) &
                # Not overbought
                (dataframe["rsi"] < 70) &
                (dataframe["volume"] > 0)
            ),
            "enter_long",
        ] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                # Death cross: fast EMA crosses below slow EMA
                (dataframe["ema_fast"] < dataframe["ema_slow"]) &
                (dataframe["ema_fast_prev"] >= dataframe["ema_slow_prev"])
            ),
            "exit_long",
        ] = 1

        return dataframe
