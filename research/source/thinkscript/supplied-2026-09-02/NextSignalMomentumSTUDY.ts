## Identify Last
def lastBar = BarNumber();
def current = HighestAll(If(IsNaN(close), 0, lastBar));
## Chop Thinkorswim’s MovAvgAdaptive
input mode = {default KAMA, AMA};
def direction;
def volatility;
def ER;
switch (mode) {
case KAMA:
direction = AbsValue(close – close[10]);
volatility = Sum(AbsValue(close – close[1]), 10);
ER = if volatility != 0 then direction / volatility else 0;
case AMA:
direction = Double.NaN;
volatility = Double.NaN;
ER = AbsValue((close – Lowest(low, 10)) –
(Highest(high, 10) – close)) / (Highest(high,
10) – Lowest(low, 10));}
def SlowSF = 0.2222;
def ScaledSF = ER * (0.4 – SlowSF) + SlowSF;
def AMA = CompoundValue(1, AMA[1] + Sqr(ScaledSF) * (close – AMA[1]),
close);
plot MAA = AMA;
MAA.assignvaluecolor(if OHLC4 > AMA then createcolor(38,115,251)
else createcolor(234,33,0));
MAA.setlineweight(2);
MAA.hidebubble();
MAA.hidetitle();
### Calculate Tangent
def m = Tan(OHLC4 * Double.Pi / 10) – Tan(OHLC4[5] * Double.Pi / 10);
# 7-bar slope line
def lrs = 6 * (WMA(OHLC4,7) – Average(OHLC4,7))/(6);
input fr = No;
def mlr;
if (fr) then {
mlr = InertiaAll(OHLC4);} else {
mlr = InertiaAll(OHLC4,7);}
def dist = HighestAll(AbsValue(mlr – OHLC4));
plot mlrPlot = mlr;
mlrPlot.SetDefaultColor(createcolor(25,115,250));
mlrPlot.assignvaluecolor(if m < 0 then color.red else createcolor(25,115,250));
mlrPlot.setlineweight(2);
mlrPlot.hidebubble();
mlrPlot.hidetitle();
# 20-bar slope line;
def lrs2 = 6 * (WMA(OHLC4, 20) – Average(OHLC4, 20))/(19);
input fr2 = No;
def mlr2;
if (fr2) then {
mlr2 = InertiaAll(OHLC4);} else {
mlr2 = InertiaAll(OHLC4, 20);}
plot mlr2Plot = mlr2;
mlr2Plot.HideBubble();
mlr2Plot.hidetitle();
mlr2Plot.SetDefaultColor(createcolor(80,100,130));
mlr2Plot.SetStyle(curve.short_dash);
mlr2Plot.setlineweight(1);

addlabel(current == lastBar and close > AMA,” Long “,createcolor(38,115,251));
addlabel(current == lastBar and close < AMA,” Short “,createcolor(206,49,56));
assignpricecolor(if close > AMA then createcolor(38,115,251) else createcolor(206,49,56));
