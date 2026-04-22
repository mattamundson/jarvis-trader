
#Program: Multi Time Frame Keltner Channels presented as horizontal lines on side of chart
#Created by Maverick & Renegade
#Creation date: 2/15/20


input period = AggregationPeriod.FIFTEEN_MIN;
input factor = 1.5;
input factor2 = 2.0;
input length = 20;
input lineLength = 50;
Input ShowLabel = YES;
input ShowCloud = YES;
input ShowClosedDoor = NO;

def h = high(period = period);
def l = low (period = period);
def c = close (period = period);
def averageType = AverageType.SIMPLE;
def trueRangeAverageType = AverageType.SIMPLE;
def shift1 = factor * MovingAverage(trueRangeAverageType, TrueRange(h, c, l), length);
def shift2 = factor2 * MovingAverage(trueRangeAverageType, TrueRange(h, c, l), length);
def average = MovingAverage(averageType, c, length);
def UB = average + shift1;
def UBa = average + shift2;
def LB = average - shift1;
def Lba = average - shift2;
def time = (Period / 60) * .001;
def lastBar = HighestAll(if !IsNaN(close) then BarNumber() else 0);
def barNumber = BarNumber();
def barCount = HighestAll(If(IsNaN(close), 0, barNumber));


#Plots Kelt Bands

def plotAvg = if barNumber == lineLength then Double.NaN else if barNumber == barCount - lineLength 
                            then average[-lineLength]  else plotAvg[1];
plot Avg = PlotAvg;
Avg.SetDefaultColor(GetColor(1));
Avg.SetLineWeight(2);
Avg.Setstyle(Curve.LONG_DASH);

def plotUpper_Band1 = if barNumber == lineLength then Double.NaN else if barNumber == barCount - lineLength 
                            then UB[-lineLength]  else plotUpper_band1[1];
plot Upper_Band1 = plotUpper_Band1;
Upper_Band1.SetDefaultColor(GetColor(2));
Upper_Band1.SetLineWeight(1);

def plotLower_Band1 =  if barNumber == lineLength then Double.NaN else if barNumber == barCount - lineLength 
                            then LB[-lineLength]  else plotLower_Band1[1];
plot Lower_Band1= plotLower_Band1;
Lower_Band1.SetDefaultColor(GetColor(2));
Lower_Band1.SetLineWeight(1);

def PlotUpper_Band2 =  if barNumber == lineLength then Double.NaN else if barNumber == barCount - lineLength 
                            then UBa[-lineLength]  else PlotUpper_Band2[1];
plot Upper_Band2 = plotUpper_Band2;
Upper_Band2.SetDefaultColor(GetColor(3));
Upper_Band2.SetLineWeight(1);

def plotLower_Band2 =  if barNumber == lineLength then Double.NaN else if barNumber == barCount - lineLength 
                            then LBa[-lineLength]  else PlotLower_Band2[1];
plot Lower_Band2 = plotLower_Band2;
Lower_Band2.SetDefaultColor(GetColor(3));
Lower_Band2.SetLineWeight(1);


#LineLabels

AddChartBubble(ShowLabel, if BarNumber() == HighestAll(lastBar + 20) then Upper_Band1 else Double.NaN, if time / 60 == 720 then "Monthly Top" else if time / 60 == 168 then "Weekly Top" else if time / 60 == 24 then "Daily Top" else if time / 60 == 4 then "4hr Top" else if time / 60 == 1 then "1hr Top" else time + (if time >= 60 then "" else "min Top"), GlobalColor("sand" ), 0);


AddChartBubble(ShowLabel, if BarNumber() == HighestAll(lastBar + 20) then Lower_Band1 else Double.NaN, if time / 60 == 720 then "Monthly Bottom" else if time / 60 == 168 then "Weekly Bottom" else if time / 60 == 24 then "Daily Bottom" else if time / 60 == 4 then "4hr Bottom" else if time / 60 == 1 then "1hr Bottom" else time + (if time >= 60 then "" else "min Bottom"), GlobalColor("sand" ), 0);


# -----------------------------------------
#MACD Primer Cloud
#==============================================================================================


def fastLength0 = 12;
def slowLength0 = 26;
def MACDLength = 9;
def MACDaverageType = AverageType.EXPONENTIAL;
#input showBreakoutSignals = yes;

def Value = MovingAverage(MACDaverageType, c, fastLength0) - MovingAverage(MACDaverageType, c, slowLength0);
def Avg0 = MovingAverage(MACDaverageType, Value, MACDLength);

def Diff = Value - Avg0;


#CLOUDS
#==============================================================================================


def MainCloudU1 = if ShowCloud == YES then Upper_Band1 else Double.NaN;
def MainCloudU2= if ShowCloud == YES then Upper_Band2 else Double.NaN;
def MainCloudL1 = if ShowCloud == YES then Lower_Band1 else Double.NaN;
def MainCloudL2 = if ShowCloud == YES then Lower_Band2 else Double.NaN;
AddCloud(MainCloudU2,   MainCloudU1,   (GlobalColor("Cloud")));
AddCloud(MainCloudL1,   MainCloudL2,   (GlobalColor("Cloud")));


def cloud1 = if Diff > 0 then Double.NaN else Upper_Band1;
def cloud1a = if ShowClosedDoor == YES then cloud1 else Double.NaN;
def cloud2 = if Diff > 0 then Double.NaN else Upper_Band2;
def cloud2a = if ShowClosedDoor == YES then cloud2 else Double.NaN;
def cloud3 = if Diff < 0  then Double.NaN else Lower_Band1;
def cloud3a = if ShowClosedDoor == YES then cloud3 else Double.NaN;
def cloud4 = if Diff < 0  then Double.NaN else Lower_Band2;
def cloud4a = if ShowClosedDoor == YES then cloud4 else Double.NaN;

AddCloud(cloud2a,   cloud1a,   (GlobalColor("MACD")));
AddCloud(cloud3a, cloud4a, (GlobalColor("MACD")));
#GLOBAL COLORS
#==============================================================================================
DefineGlobalColor("Cloud", CreateColor(102, 102, 102));
DefineGlobalColor("MACD", CreateColor(181, 181, 181));
DefineGlobalColor("sand", CreateColor(255, 204, 102)); #sand
