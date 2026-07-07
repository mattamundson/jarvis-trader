#Program: JBOYD(renegade)_keltner_multi_timeframe.ts
#
#Creation date: 11/14/2018
#Edit Log (Date/Editor):
#
#
#
#==============================================================================================
#hint: Enables user-defined aggregation period setting for multiple sets of Keltner Channels

#INPUTS
#==============================================================================================
input iAggregationPeriod = AggregationPeriod.four_hours;
#input iAggregationPeriodPrimary = AggregationPeriod.FIVE_MIN;
input iHideMidLinePrimary = NO;
input iDisplacePrimary = 0;
input iFactorPrimary = 1.5;
input iLengthPrimary = 20;
input iPricePrimary = {OPEN, HIGH, LOW, default CLOSE, HL2, HLC3, OHLC4};
input iAvgTypePrimary = AverageType.SIMPLE;
input iTrueRangeAvgTypePrimary = AverageType.SIMPLE;

#input iAggregationPeriodSecondary = AggregationPeriod.FIVE_MIN;
input iHideMidLineSecondary = NO;
input iDisplaceSecondary = 0;
input iFactorSecondary = 2.0;
input iLengthSecondary = 20;
input iPriceSecondary = {OPEN, HIGH, LOW, default CLOSE, HL2, HLC3, OHLC4};
input iAvgTypeSecondary = AverageType.SIMPLE;
input iTrueRangeAvgTypeSecondary = AverageType.SIMPLE;

input iHideMidLine = YES;

input iDisplace = 0;
input iFactor = 1.8;
input iLength = 20;
input iPrice = {OPEN, HIGH, LOW, default CLOSE, HL2, HLC3, OHLC4};
input iAvgType = AverageType.SIMPLE;
input iTrueRangeAvgType = AverageType.SIMPLE;




#VARS & LOGIC
#==============================================================================================
def vShiftPrimary = iFactorPrimary * MovingAverage(iTrueRangeAvgTypePrimary, 
                                     TrueRange(high(period = iAggregationPeriod), 
                                               close(period = iAggregationPeriod),
                                               low(period = iAggregationPeriod)), 
                                     iLengthPrimary);

def vAveragePrimary;
if iPricePrimary == iPricePrimary.OPEN
then {
    vAveragePrimary = MovingAverage(iAvgTypePrimary, open(period = iAggregationPeriod), iLengthPrimary);
}
else if iPricePrimary == iPricePrimary.HIGH
then {
    vAveragePrimary = MovingAverage(iAvgTypePrimary, high(period = iAggregationPeriod), iLengthPrimary);
}
else if iPricePrimary == iPricePrimary.LOW
then {
    vAveragePrimary = MovingAverage(iAvgTypePrimary, low(period = iAggregationPeriod), iLengthPrimary);
}
else if iPricePrimary == iPricePrimary.CLOSE
then {
    vAveragePrimary = MovingAverage(iAvgTypePrimary, close(period = iAggregationPeriod), iLengthPrimary);
}
else if iPricePrimary == iPricePrimary.HL2
then {
    vAveragePrimary = MovingAverage(iAvgTypePrimary, hl2(period = iAggregationPeriod), iLengthPrimary);
}
else if iPricePrimary == iPricePrimary.HLC3
then {
    vAveragePrimary = MovingAverage(iAvgTypePrimary, hlc3(period = iAggregationPeriod), iLengthPrimary);
}
else if iPricePrimary == iPricePrimary.OHLC4
then {
    vAveragePrimary = MovingAverage(iAvgTypePrimary, ohlc4(period = iAggregationPeriod), iLengthPrimary);
}
else {
    vAveragePrimary = Double.NaN;
}

def vShiftSecondary = iFactorSecondary * MovingAverage(iTrueRangeAvgTypeSecondary, 
                                     TrueRange(high(period = iAggregationPeriod), 
                                               close(period = iAggregationPeriod),
                                               low(period = iAggregationPeriod)), 
                                     iLengthSecondary);

def vAverageSecondary;
if iPriceSecondary == iPriceSecondary.OPEN
then {
    vAverageSecondary = MovingAverage(iAvgTypeSecondary, open(period = iAggregationPeriod), iLengthSecondary);
}
else if iPriceSecondary == iPriceSecondary.HIGH
then {
    vAverageSecondary = MovingAverage(iAvgTypeSecondary, high(period = iAggregationPeriod), iLengthSecondary);
}
else if iPriceSecondary == iPriceSecondary.LOW
then {
    vAverageSecondary = MovingAverage(iAvgTypeSecondary, low(period = iAggregationPeriod), iLengthSecondary);
}
else if iPriceSecondary == iPriceSecondary.CLOSE
then {
    vAverageSecondary = MovingAverage(iAvgTypeSecondary, close(period = iAggregationPeriod), iLengthSecondary);
}
else if iPriceSecondary == iPriceSecondary.HL2
then {
    vAverageSecondary = MovingAverage(iAvgTypeSecondary, hl2(period = iAggregationPeriod), iLengthSecondary);
}
else if iPriceSecondary == iPriceSecondary.HLC3
then {
    vAverageSecondary = MovingAverage(iAvgTypeSecondary, hlc3(period = iAggregationPeriod), iLengthSecondary);
}
else if iPriceSecondary == iPriceSecondary.OHLC4
then {
    vAverageSecondary = MovingAverage(iAvgTypeSecondary, ohlc4(period = iAggregationPeriod), iLengthSecondary);
}
else {
    vAverageSecondary = Double.NaN;
}

#PLOTS
#==============================================================================================
plot pAvgPrimary = vAveragePrimary[-iDisplacePrimary];
plot pUpperBandPrimary = vAveragePrimary[-iDisplacePrimary] + vShiftPrimary[-iDisplacePrimary];
pUpperBandPrimary.SetDefaultColor(CreateColor(181, 181, 181));
plot pLowerBandPrimary = vAveragePrimary[-iDisplacePrimary] - vShiftPrimary[-iDisplacePrimary];
pLowerBandPrimary.SetDefaultColor(CreateColor(181, 181, 181));

plot pAvgSecondary = vAverageSecondary[-iDisplaceSecondary];
plot pUpperBandSecondary = vAverageSecondary[-iDisplaceSecondary] + vShiftSecondary[-iDisplaceSecondary];
pUpperBandSecondary.SetDefaultColor(CreateColor(0, 197, 49));
plot pLowerBandSecondary = vAverageSecondary[-iDisplaceSecondary] - vShiftSecondary[-iDisplaceSecondary];
pLowerBandSecondary.SetDefaultColor(CreateColor(0, 197, 49));


#Sets Mid to Hotness
pAvgPrimary.SetDefaultColor(CreateColor(0, 197, 49));
pAvgPrimary.SetLineWeight(2);
pAvgPrimary.SetStyle(Curve.LONG_DASH);

pAvgPrimary.SetDefaultColor(CreateColor(0, 197, 49));
pAvgSecondary.SetLineWeight(2);
pAvgSecondary.SetStyle(Curve.FIRM);

pAvgPrimary.SetHiding(iHideMidLinePrimary);
pAvgSecondary.SetHiding(iHideMidLineSecondary);


#GLOBAL COLORS
#==============================================================================================
DefineGlobalColor("Cloud", CreateColor(95, 95, 95));
DefineGlobalColor("MACD", CreateColor(80, 80, 80));

#MACD Primer Cloud
#==============================================================================================
def c = close(period = iAggregationPeriod);


input fastLength0 = 12;
input slowLength0 = 26;
input MACDLength = 9;
input averageType = AverageType.EXPONENTIAL;

def Value = MovingAverage(averageType, c, fastLength0) - MovingAverage(averageType, c, slowLength0);
def Avg0 = MovingAverage(averageType, Value, MACDLength);

def Diff = Value - Avg0;



#CLOUDS
#==============================================================================================



AddCloud(pUpperBandSecondary, pUpperBandPrimary, (GlobalColor("Cloud")));
AddCloud(pLowerBandPrimary, pLowerBandSecondary, (GlobalColor("Cloud")));


def cloud1 = if diff > 0 then Double.NaN else pUpperBandPrimary;
def cloud2 = if diff > 0 then Double.NaN else pUpperBandSecondary;
AddCloud(cloud2, cloud1, (GlobalColor("MACD")));

def cloud3 = if diff < 0 then Double.NaN else pLowerBandPrimary;
def cloud4 = if diff < 0 then Double.NaN else pLowerBandSecondary;
AddCloud(cloud3, cloud4, (GlobalColor("MACD")));



#DEBUG
#==============================================================================================

#Program: jp_keltner_multi_timeframe.ts
#
#Creation date: 11/9/2018
#Edit Log (Date/Editor):
#
#
#
#==============================================================================================
#hint: Enables user-defined aggregation period setting for Keltner Channels

#VARS & LOGIC
#==============================================================================================
def vShift = iFactor * MovingAverage(iTrueRangeAvgType, 
                                     TrueRange(high(period = iAggregationPeriod), 
                                               close(period = iAggregationPeriod),
                                               low(period = iAggregationPeriod)), 
                                     iLength);

def vAverage;
if iPrice == iPrice.OPEN
then {
    vAverage = MovingAverage(iAvgType, open(period = iAggregationPeriod), iLength);
}
else if iPrice == iPrice.HIGH
then {
    vAverage = MovingAverage(iAvgType, high(period = iAggregationPeriod), iLength);
}
else if iPrice == iPrice.LOW
then {
    vAverage = MovingAverage(iAvgType, low(period = iAggregationPeriod), iLength);
}
else if iPrice == iPrice.CLOSE
then {
    vAverage = MovingAverage(iAvgType, close(period = iAggregationPeriod), iLength);
}
else if iPrice == iPrice.HL2
then {
    vAverage = MovingAverage(iAvgType, hl2(period = iAggregationPeriod), iLength);
}
else if iPrice == iPrice.HLC3
then {
    vAverage = MovingAverage(iAvgType, hlc3(period = iAggregationPeriod), iLength);
}
else if iPrice == iPrice.OHLC4
then {
    vAverage = MovingAverage(iAvgType, ohlc4(period = iAggregationPeriod), iLength);
}
else {
    vAverage = Double.NaN;
}

#PLOTS
#==============================================================================================
#plot Avg = vAverage[-iDisplace];
plot Upper_Band = vAverage[-iDisplace] + vShift[-iDisplace];
Upper_Band.AssignValueColor(Color.GRAY);
#Upper_Band.SetLineWeight(1);
#Upper_Band.SetStyle(Curve.LONG_DASH);
plot Lower_Band = vAverage[-iDisplace] - vShift[-iDisplace];
Lower_Band.AssignValueColor(Color.GRAY);
#Lower_Band.SetLineWeight(1);
#Lower_Band.SetStyle(Curve.LONG_DASH);


#Avg.SetHiding(iHideMidLine);

#DEBUG
#==============================================================================================

