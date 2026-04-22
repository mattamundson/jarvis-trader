declare hide_on_daily;


input aggregationPeriod = AggregationPeriod.DAY;
input showOnlyToday = yes;

def PH = high(period = aggregationPeriod)[1];
def PL = low(period = aggregationPeriod)[1];
def PC = close(period = aggregationPeriod)[1];


plot R4;
plot R3;
plot R2;
plot R1;
plot PP;
plot S1;
plot S2;
plot S3;
plot S4;

if showOnlyToday and !IsNaN(close(period = aggregationPeriod)[-1])

then {

    R1 = Double.NaN;
    R2 = Double.NaN;
    R3 = Double.NaN;
    R4 = Double.NaN;
    PP = Double.NaN;
    S1 = Double.NaN;
    S2 = Double.NaN;
    S3 = Double.NaN;
    S4 = Double.NaN;

} else {

    PP = (PH + PL + PC) / 3;
    R1 = 2 * PP - PL;
    R2 = PP + (PH - PL);
    R3 = 2 * PP + (PH - 2 * PL);
    R4 = PH + 3 * (PP - PL);
    S1 = 2 * PP - PH;
    S2 = PP - (PH - PL);
    S3 = 2 * PP - (2 * PH - PL);
    S4 = PL - 3 * (PH - PP);
}


R4.SetDefaultColor(GetColor(5));
R3.SetDefaultColor(GetColor(5));
R2.SetDefaultColor(GetColor(5));
R1.SetDefaultColor(GetColor(5));
PP.SetDefaultColor(GetColor(0));
S1.SetDefaultColor(GetColor(6));
S2.SetDefaultColor(GetColor(6));
S3.SetDefaultColor(GetColor(6));
S4.SetDefaultColor(GetColor(6));

R4.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
R3.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
R2.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
R1.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
PP.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
S1.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
S2.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
S3.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
S4.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);

R4.SetStyle(Curve.SHORT_DASH);
R3.SetStyle(Curve.SHORT_DASH);
R2.SetStyle(Curve.SHORT_DASH);
R1.SetStyle(Curve.SHORT_DASH);
PP.SetStyle(Curve.MEDIUM_DASH);
S1.SetStyle(Curve.SHORT_DASH);
S2.SetStyle(Curve.SHORT_DASH);
S3.SetStyle(Curve.SHORT_DASH);
S4.SetStyle(Curve.SHORT_DASH);
