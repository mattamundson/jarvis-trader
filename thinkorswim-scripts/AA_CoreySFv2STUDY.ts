# Corey Singlefinder (c) version 2
# By Corey Surles
# @coreysurles


#Disclaimer#
#All output is for informational and educational purposes only. This is not an investment recommendation or advice, and should not be relied upon in making the decision to buy or sell a security or pursue a particular investment strategy#


#\\\\\\\\\\\Definitions
input ShowExtensions = yes;
input ShowArrows = yes;
input ShowLabels = yes;
input showGaps = yes;
def dynamicClouds = no;
def na = Double.NaN;
input ShowFailDots = yes;
Input ShowClouds = no;

# Define Down minus development
def bearishSingle = 
    if high[-1] < low[1]
        and high > low[1]
        and (if showGaps then high > low[1] else low < high[-1])
    then 1 else 0;


#Define Up minus development
def bullishSingle = 
    if high[1] < low[-1]
        and high > low[-1]
        and (if showGaps then high > low[-1] else low < high[1])
    then 1 else 0;


def bullf = if open > high[2] and low < high[2] then 1 else na;
plot bullfail = if bullf then high[2] else na;
bullfail.setpaintingStrategy(paintingStrategy.HORIZONTAL);
bullfail.setdefaultColor(color.pink);

def bearf = if open < low[2] and high > low[2] then 1 else na;
plot bearfail = if bearf then low[2] else na;
bearfail.setpaintingStrategy(paintingStrategy.HORIZONTAL);
bearfail.setdefaultColor(COLOR.ORANGE);

#\\\\\\\\\\\Plots

# Horizontals
plot bearSingle = if bearishSingle then high[-1] else na;
bearSingle.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
bearSingle.SetDefaultColor(Color.ORANGE);
bearSingle.SetLineWeight(1);

plot bearSingle2 = if bearishSingle then low[1] else na;
bearSingle2.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
bearSingle2.SetDefaultColor(Color.ORANGE);
bearSingle2.SetLineWeight(1);

plot bullSingle = if bullishSingle then high[1] else na;
bullSingle.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
bullSingle.SetDefaultColor(Color.PINK);
bullSingle.SetLineWeight(1);

plot bullSingle2 = if bullishSingle then low[-1] else na;
bullSingle2.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
bullSingle2.SetDefaultColor(Color.PINK);
bullSingle2.SetLineWeight(1);


# Extend the current Bearish Singles to the right edge of the chart
def countp = if IsNaN(bearSingle) and !IsNaN(bearSingle[1]) then 1 else countp[1] + 1;
plot bearExt = if ShowExtensions and IsNaN(bearSingle) then GetValue(bearSingle, countp) else Double.NaN;
bearExt.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
bearExt.SetDefaultColor(Color.ORANGE);
bearExt.SetLineWeight(1);

def countp2 = if IsNaN(bearSingle2) and !IsNaN(bearSingle2[1]) then 1 else countp2[1] + 1;
plot bearExt2 = if ShowExtensions and IsNaN(bearSingle2) then GetValue(bearSingle2, countp2) else Double.NaN;
bearExt2.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
bearExt2.SetDefaultColor(Color.ORANGE);
bearExt2.SetLineWeight(1);

# Extend the current Bullish Singles to the right edge of the chart
def countv = if IsNaN(bullSingle) and !IsNaN(bullSingle[1]) then 1 else countv[1] + 1;
plot bullExt = if ShowExtensions and IsNaN(bullSingle) then GetValue(bullSingle, countv) else Double.NaN;
bullExt.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
bullExt.SetDefaultColor(Color.PINK);
bullExt.SetLineWeight(1);

def countv2 = if IsNaN(bullSingle2) and !IsNaN(bullSingle2[1]) then 1 else countv2[1] + 1;
plot bullExt2 = if ShowExtensions and IsNaN(bullSingle2) then GetValue(bullSingle2, countv2) else Double.NaN;
bullExt2.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
bullExt2.SetDefaultColor(Color.PINK);
bullExt2.SetLineWeight(1);

# Up Down Arrows

plot bearSingleArrow = if bearishSingle and ShowArrows then high else na;
bearSingleArrow.SetPaintingStrategy(PaintingStrategy.BOOLEAN_ARROW_DOWN);
bearSingleArrow.SetDefaultColor(Color.ORANGE);
bearSingleArrow.SetLineWeight(3);

plot bullSingleArrow = if bullishSingle and ShowArrows then low else na;
bullSingleArrow.SetPaintingStrategy(PaintingStrategy.BOOLEAN_ARROW_UP);
bullSingleArrow.SetDefaultColor(Color.PINK);
bullSingleArrow.SetLineWeight(3);

plot bearfailArrow = if bearf and ShowFailDots then low[2] else na;
bearfailArrow.SetPaintingStrategy(PaintingStrategy.LINE_VS_POINTS);
bearfailArrow.AssignValueColor(if bearfail and close < low[2] then Color.orange else Color.orange);
bearfailArrow.SetLineWeight(3);

plot bullfailArrow = if bullf and ShowFailDots then high[2] else na;
bullfailArrow.SetPaintingStrategy(PaintingStrategy.LINE_VS_POINTS);
bullfailArrow.assignvalueColor(if bullfail and close > high[2] then Color.pink else Color.pink);
bullfailArrow.SetLineWeight(3);



# Labels
AddLabel(yes, if close > bearExt2 then "Bear Single Filled " + bearExt2 else "Bear Single Unfilled " + bearExt2, Color.ORANGE);
AddLabel(yes, if close < bullExt then "Bull Single Filled " + bullExt else "Bull Single Unfilled " + bullExt, Color.PINK);

# Extension Clouds
AddCloud(if showclouds then bullext else na, if showclouds then bullext2 else na, if dynamicclouds then Color.green else color.pink, if dynamicclouds then  Color.red else color.pink);

AddCloud(if showclouds then bearext else na, if showclouds then bearext2 else na, if dynamicclouds then Color.green else color.orange, if dynamicclouds then  Color.red else color.orange);
