
declare lower;
#Assign Breakout signals
input TimeShift = {"1 min", "2 min", "3 min", default "5 min",  "10 min", "15 min", "20 min", "30 min", "1h", "2h", "4h", "Daily", "Weekly", "Monthly"};

input STC_BreakoutSignals = {default "No", "Yes"};

input fastLength = 23;
input slowLength = 50;
input KPeriod = 10;
input DPeriod = 3;

input over_bought = 88;
input over_sold = 19;
input averageType = AverageType.EXPONENTIAL;
input paintBars = yes;

def TimeShiftCandle;

switch (TimeShift) {
case "1 min":
    TimeShiftCandle = AggregationPeriod.MIN;
case "2 min":
    TimeShiftCandle = AggregationPeriod.TWO_MIN;
case "3 min":
    TimeShiftCandle = AggregationPeriod.THREE_MIN;
case "5 min":
    TimeShiftCandle = AggregationPeriod.FIVE_MIN;
case "10 min":
    TimeShiftCandle = AggregationPeriod.TEN_MIN;
case "15 min":
    TimeShiftCandle = AggregationPeriod.FIFTEEN_MIN;
case "20 min":
    TimeShiftCandle = AggregationPeriod.TWENTY_MIN;
case "30 min":
    TimeShiftCandle = AggregationPeriod.THIRTY_MIN;
case "1h":
    TimeShiftCandle = AggregationPeriod.HOUR;
case "2h":
    TimeShiftCandle = AggregationPeriod.TWO_HOURS;
case "4h":
    TimeShiftCandle = AggregationPeriod.FOUR_HOURS;
case "Daily":
    TimeShiftCandle = AggregationPeriod.DAY;
case "Weekly":
    TimeShiftCandle = AggregationPeriod.WEEK;
case "Monthly":
    TimeShiftCandle = AggregationPeriod.MONTH;
}


def macd = MovingAverage(averageType, (close(period = TimeShiftCandle)), fastLength) - MovingAverage(averageType, close(period = TimeShiftCandle), slowLength);
def fastK1 = FastKCustom(macd, KPeriod);
def fastD1 = MovingAverage(averageType, fastK1, DPeriod);
def fastK2 = FastKCustom(fastD1, KPeriod);
plot STC = MovingAverage(averageType, fastK2, DPeriod);
plot OverBought = over_bought;
plot OverSold = over_sold;


STC.SetDefaultColor(GetColor(8));
STC.DefineColor("Positive and Up", Color.GREEN);
STC.DefineColor("Negative and Down", Color.RED);
STC.AssignValueColor(if STC >= STC[1] then STC.Color("Positive and Up") else STC.Color("Negative and Down"));
STC.SetLineWeight(2);

OverBought.SetDefaultColor(GetColor(7));
OverSold.SetDefaultColor(GetColor(7));

# --- Conditions
def sellerRegular = overbought;
def sellerExtreme = STC <= STC[1];
def buyerRegular = oversold;
def buyerExtreme = STC >= STC[1];
# --- End Conditions

# -- Price Color
AssignPriceColor( if paintBars and sellerExtreme then Color.gray 

else if buyerExtreme and paintBars then Color.MAGENTA 
else if paintBars and sellerRegular then Color.GREEN 
else if buyerRegular and paintBars then Color.RED 
else if paintBars then Color.white else Color.CURRENT);

# --- Arrows/Triggers
plot RegularBuy = if sellerRegular[1] and !sellerRegular then low else Double.NaN;

RegularBuy.SetPaintingStrategy(PaintingStrategy.ARROW_UP);

RegularBuy.SetDefaultColor(Color.GREEN);


plot RegularSell = if buyerRegular[1] and !buyerRegular then high else Double.NaN;

RegularSell.SetPaintingStrategy(PaintingStrategy.ARROW_DOWN);

RegularSell.SetDefaultColor(Color.RED);


###########    PLOTS FOR TRIGGERS  #####################

##########   Change the trigger point for different time frame charts... they will scale difference the higer the chart time is..

plot BULLTRIGGER = 82;
#BULLTRIGGER.SetStyle(Curve.short_Dash);
#BULLTRIGGER.SetLineWeight(1);
#BULLTRIGGER.SetDefaultColor(GetColor(5));

plot BULLTRIGGER1 = 82;
#BULLTRIGGER1.SetStyle(Curve.short_Dash);
#BULLTRIGGER1.SetLineWeight(1);
#BULLTRIGGER1.SetDefaultColor(GetColor(5));

plot Beartrigger = 20;
#BEARTRIGGER.SetStyle(Curve.short_Dash);
#BEARTRIGGER.SetLineWeight(1);
#BEARTRIGGER.SetDefaultColor(GetColor(5));

plot Beartrigger1 = 90;
#BEARTRIGGER1.SetStyle(Curve.short_Dash);
#BEARTRIGGER1.SetLineWeight(1);
#BEARTRIGGER1.SetDefaultColor(GetColor(5));

plot Midline = 50;
Midline.SetStyle(Curve.LONG_DASH);
Midline.SetLineWeight(2);
Midline.SetDefaultColor(GetColor(9));


plot StyleBuy = 15;
StyleBuy.SetStyle(Curve.SHORT_DASH);
StyleBuy.SetLineWeight(1);
StyleBuy.SetDefaultColor(CreateColor(0, 255, 0));

plot StyleSell = 85;
StyleSell.SetStyle(Curve.SHORT_DASH);
StyleSell.SetDefaultColor(CreateColor(255, 0, 0));

#GLOBAL COLORS
#==============================================================================================
DefineGlobalColor("BEARTRIGGER", CreateColor(54, 56, 54));
DefineGlobalColor("BULLTRIGGER", CreateColor(54, 56, 54));
DefineGlobalColor("BEARTRIGGER1", CreateColor(54, 56, 54));
DefineGlobalColor("BULLTRIGGER1", CreateColor(54, 56, 54));

AddCloud(if BULLTRIGGER then 65 else Double.NaN, if BULLTRIGGER then 75 else Double.NaN, GlobalColor("BEARTRIGGER"), GlobalColor("BEARTRIGGER1"));
AddCloud(if BULLTRIGGER1 then 20 else Double.NaN, if BULLTRIGGER1 then 35 else Double.NaN,
GlobalColor("BULLTRIGGER"), GlobalColor("BULLTRIGGER1"));
AddCloud(if Beartrigger then 85 else Double.NaN, if Beartrigger then 100 else Double.NaN,
GlobalColor("BEARTRIGGER"), GlobalColor("BEARTRIGGER1"));
AddCloud(if Beartrigger1 then 0 else Double.NaN, if Beartrigger1 then 15 else Double.NaN,
GlobalColor("BEARTRIGGER"), GlobalColor("BEARTRIGGER1"));
