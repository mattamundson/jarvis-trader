#Program: jp_keltner_multi_timeframe.ts
#
#Creation date: 11/9/2018
#Edit Log (Date/Editor):
#
#
#
#==============================================================================================
#hint: Enables user-defined aggregation period setting for Keltner Channels

#INPUTS
#==============================================================================================
input iAggregationPeriod = AggregationPeriod.FIVE_MIN;
input iHideMidLine = YES;

input iDisplace = 0;
input iFactor = 3.0;
input iLength = 20;
input iPrice = {OPEN, HIGH, LOW, default CLOSE, HL2, HLC3, OHLC4};
input iAvgType = AverageType.SIMPLE;
input iTrueRangeAvgType = AverageType.SIMPLE;

#VARS & LOGIC
#==============================================================================================
def vShift = iFactor * MovingAverage(iTrueRangeAvgType, 
                                     TrueRange(high(period = iAggregationPeriod), 
                                               close(period = iAggregationPeriod),
                                               low(period = iAggregationPeriod)), 
                                     iLength);

def vAverage;
if iPrice == iPrice.OPEN
    then {vAverage = MovingAverage(iAvgType, open(period = iAggregationPeriod), iLength);}
else if iPrice == iPrice.HIGH
    then {vAverage = MovingAverage(iAvgType, high(period = iAggregationPeriod), iLength);}
else if iPrice == iPrice.LOW
    then {vAverage = MovingAverage(iAvgType, low(period = iAggregationPeriod), iLength);}
else if iPrice == iPrice.CLOSE
    then {vAverage = MovingAverage(iAvgType, close(period = iAggregationPeriod), iLength);}
else if iPrice == iPrice.HL2
    then {vAverage = MovingAverage(iAvgType, hl2(period = iAggregationPeriod), iLength);}
else if iPrice == iPrice.HLC3
    then {vAverage = MovingAverage(iAvgType, hlc3(period = iAggregationPeriod), iLength);}
else if iPrice == iPrice.OHLC4
    then {vAverage = MovingAverage(iAvgType, ohlc4(period = iAggregationPeriod), iLength);}
else {vAverage = Double.NaN;}

#PLOTS
#==============================================================================================
plot Avg = vAverage[-iDisplace];
plot Upper_Band = vAverage[-iDisplace] + vShift[-iDisplace];
plot Lower_Band = vAverage[-iDisplace] - vShift[-iDisplace];

Avg.SetHiding(iHideMidLine);

#DEBUG
#==============================================================================================
