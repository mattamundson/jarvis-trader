##################  LBR PAINT BARS #########################



input HLLength = 16;
input ATRLength = 9;
input factor = 2.5;
input paintBars = yes;
input averageType = AverageType.SIMPLE;

assert(factor > 0, "'factor' must be positive: " + factor);

def AATR = factor * MovingAverage(averageType, MovingAverage(averageType, TrueRange(high, close, low), ATRLength), ATRLength);
def band1 = Lowest(low, HLLength) + AATR;
def band2 = Highest(high, HLLength) - AATR;

plot UpperVolatility = close > band1 and close > band2;
plot LowerVolatility = close < band1 and close < band2;

UpperVolatility.SetPaintingStrategy(PaintingStrategy.BOOLEAN_POINTS);
UpperVolatility.SetLineWeight(3);
UpperVolatility.SetDefaultColor(Color.GREEN);
UpperVolatility.hide();
LowerVolatility.SetPaintingStrategy(PaintingStrategy.BOOLEAN_POINTS);
LowerVolatility.SetLineWeight(3);
LowerVolatility.SetDefaultColor(Color.RED);
LowerVolatility.hide();

DefineGlobalColor("Bullish", Color.GREEN);
DefineGlobalColor("Bearish", Color.RED);
AssignPriceColor(if !paintBars
    then Color.CURRENT
    else if UpperVolatility
        then globalColor("Bullish")
        else if LowerVolatility
            then globalColor("Bearish")
            else Color.CURRENT);



