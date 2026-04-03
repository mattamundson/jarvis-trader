
plot StudyLabelColor = Double.NaN;
StudyLabelColor.DefineColor("Labels and Bubbles" , (CreateColor(255, 255, 255)));
StudyLabelColor.AssignValueColor(StudyLabelColor.Color("Labels and Bubbles"));
#Use any color you desire this is only to set the color of the Study in the data box, must be the first plot defined in the study for this to control the color of the Study Title in the data box. Note: can not hide study plot, if hidden will not set the color of the study title in the data box. HideTitle is okay to use though.
StudyLabelColor.HideTitle();

plot VPOC_Color = Double.NaN;
VPOC_Color.DefineColor("VPOC Color" , (CreateColor(30, 155, 172)));
VPOC_Color.HideTitle();
VPOC_Color.Hide();

plot VVAH_Color = Double.NaN;
VVAH_Color.DefineColor("VVAH Color" , (CreateColor(225, 85, 65)));
VVAH_Color.HideTitle();
VVAH_Color.Hide();

plot VVAL_Color = Double.NaN;
VVAL_Color.DefineColor("VVAL Color" , (CreateColor(130, 238, 116)));
VVAL_Color.HideTitle();
VVAL_Color.Hide();




input show_volume_time_profile = {default "Volume", "Time"}; #Hint show_volume_time_profile: Option to choose between displaying Time Profle or Volume Profle
def shows_volume_time_profiles;
switch (show_volume_time_profile){
case "Volume":
    shows_volume_time_profiles = 0;
case "Time":
    shows_volume_time_profiles = 1;
}

input poc_calculation = {default "Volume", "Time", "Average of Vol&Time"}; #Hint poc_calculation: Option to choose between Volume POC, Time POC and taking the Avgerage of Time plus Volume values, also changes Value Area High and Value Area Low values.

def poc_calculations;
switch(poc_calculation){
case "Volume":
    poc_calculations = 0;
case "Time":
    poc_calculations = 1;
case "Average of Vol&Time":
    poc_calculations = 2;
}
####
input SplitVolumeProfile = {default "No", "Yes"};#Hint SplitVolumeProfile: Option to Split Volume Profile into RTH vs AH
input rthbegin = 0930; #Hint rthbegin: Input time for Regular Trading Hours start, used for splitting profiles
input rthend = 1600; #Hint rthend: Input time for Regular Trading Hours end, only affects Equities Profiles, Futures will use AHEnd input to set when profile will be split, used for splitting profiles
input ahend = 1700; #Hint ahend: Input time for Futures Trading Hours end, only affects Futures Profiles, Equites will use RTHEnd input to set when profile will be split, used for splitting profiles

input valueAreaPercent = 70.0; #Hint valueAreaPercent: Set the size of the Value Area

input show_vpocs = {default "Yes", "No"}; #Hint show_vpocs: Option to show/hide Virgin Point of Control Plots
def shows_vpocs;
switch (show_vpocs){
case "No":
    shows_vpocs = 0;
case "Yes":
    shows_vpocs = 1;
}

input show_vvah= {default "Yes", "No"}; #Hint show_vvah:Option to show/hide Virgin Value Area High Plots
def shows_vvah;
switch (show_vvah){
case "No":
    shows_vvah = 0;
case "Yes":
    shows_vvah = 1;
}

input show_vval = {default "Yes", "No"}; #Hint show_vval:Option to show/hide Virgin Value Area Low Plots
def shows_vval;
switch (show_vval){
case "No":
    shows_vval = 0;
case "Yes":
    shows_vval = 1;
}

input show_labels = {default "Yes", "No"}; #Hint show_labels: Option to show/hide profile/timeframe label
def shows_labels;
switch (show_labels){
case "No":
    shows_labels = 0;
case "Yes":
    shows_labels = 1;
}

input show_stats_labels = {default "Yes", "No"}; #Hint show_stats_labels: Option to show/hide profile/timeframe stats labels
def shows_stats_labels;
switch (show_stats_labels){
case "No":
    shows_stats_labels = 0;
case "Yes":
    shows_stats_labels = 1;
}

input show_cloud = {default "Yes", "No"}; #Hint show_cloud: Option to show/hide profile/timeframe cloudvah from VAL to VAH
def shows_cloud;
switch (show_cloud){
case "No":
    shows_cloud = 1;
case "Yes":
    shows_cloud = 0;
}





input display_profile_bubbles = {default "Yes","No"}; #Hint display_profile_bubbles:option to display bubbles for Point of Control, Value Area High and Value Area Low levels to identify them easily
def bubbles_profiles_number;
switch(display_profile_bubbles){
case "Yes":
bubbles_profiles_number = 1;
case "No":
bubbles_profiles_number = 0;
}

DefineGlobalColor("Profile", Color.gray);
DefineGlobalColor("Today's Point Of Control", GetColor(5));
DefineGlobalColor("Today's Value Area", GetColor(8));
DefineGlobalColor("Previous Value Area Cloud", CreateColor(128, 128, 128));




def symbol_check = 
(if GetSymbol() == "/ES:XCME" then 1
else if GetSymbol() == "/NQ:XCME" then 1
else if GetSymbol() == "/YM:XCBT" then 1
else if GetSymbol() == "/RTY:XCME" then 1
else if GetSymbol() == "/NKD:XCME" then 1
else if GetSymbol() == "/EMD:XCME" then 1
else if GetSymbol() == "/VX:XCBF" then 1
else if GetSymbol() == "/BTC:XCME" then 1
else if GetSymbol() == "/XBT:XCBF" then 1
else if GetSymbol() == "/CL:XNYM" then 1
else if GetSymbol() == "/QM:XNYM" then 1
else if GetSymbol() == "/NG:XNYM" then 1
else if GetSymbol() == "/QG:XNYM" then 1
else if GetSymbol() == "/RB:XNYM" then 1
else if GetSymbol() == "/HO:XNYM" then 1
else if GetSymbol() == "/BZ:XNYM" then 1
else if GetSymbol() == "/GC:XCEC" then 1
else if GetSymbol() == "/MGC:XCEC" then 1
else if GetSymbol() == "/SI:XCEC" then 1
else if GetSymbol() == "/SIL:XCEC" then 1
else if GetSymbol() == "/HG:XCEC" then 1
else if GetSymbol() == "/PL:XNYM" then 1
else if GetSymbol() == "/PA:XNYM" then 1
else if GetSymbol() == "/ZB:XCBT" then 1
else if GetSymbol() == "/ZN:XCBT" then 1
else if GetSymbol() == "/ZF:XCBT" then 1
else if GetSymbol() == "/ZT:XCBT" then 1
else if GetSymbol() == "/UB:XCBT" then 1
else if GetSymbol() == "/TN:XCBT" then 1
else if GetSymbol() == "/GE:XCME" then 1
else if GetSymbol() == "/ZQ:XCBT" then 1
else if GetSymbol() == "/GLB:XCME" then 1
else if GetSymbol() == "/6A:XCME" then 1
else if GetSymbol() == "/M6A:XCME" then 1
else if GetSymbol() == "/6B:XCME" then 1
else if GetSymbol() == "/M6B:XCME" then 1
else if GetSymbol() == "/6C:XCME" then 1
else if GetSymbol() == "/6E:XCME" then 1
else if GetSymbol() == "/E7:XCME" then 1
else if GetSymbol() == "/M6E:XCME" then 1
else if GetSymbol() == "/6J:XCME" then 1
else if GetSymbol() == "/J7:XCME" then 1
else if GetSymbol() == "/6M:XCME" then 1
else if GetSymbol() == "/6N:XCME" then 1
else if GetSymbol() == "/6S:XCME" then 1
else if GetSymbol() == "/ZC:XCBT" then 1
else if GetSymbol() == "/XC:XCBT" then 1
else if GetSymbol() == "/ZS:XCBT" then 1
else if GetSymbol() == "/XK:XCBT" then 1
else if GetSymbol() == "/ZW:XCBT" then 1
else if GetSymbol() == "/XW:XCBT" then 1
else if GetSymbol() == "/KE:XCBT" then 1
else if GetSymbol() == "/ZM:XCBT" then 1
else if GetSymbol() == "/ZL:XCBT" then 1
else if GetSymbol() == "/ZO:XCBT" then 1
else if GetSymbol() == "/HE:XCME" then 1
else if GetSymbol() == "/GF:XCME" then 1
else if GetSymbol() == "/LE:XCME" then 1
else if GetSymbol() == "/SB:IFUS" then 1
else if GetSymbol() == "/OJ:IFUS" then 1
else if GetSymbol() == "/LBS:XCME" then 1
else if GetSymbol() == "/FNG:IFUS" then 1
else if GetSymbol() == "/MME:IFUS" then 1
else if GetSymbol() == "/DX:IFUS" then 1
else if GetSymbol() == "/YG:IFUS" then 1
else if GetSymbol() == "/YI:IFUS" then 1
else if GetSymbol() == "/CT:IFUS" then 1
else if GetSymbol() == "/CC:IFUS" then 1
else if GetSymbol() == "/KC:IFUS" then 1
else 0);




def AggPeriod = GetAggregationPeriod();
def lessthanfifteen = if AggPeriod < AggregationPeriod.FIFTEEN_MIN then 5 else 0;
def lessthandaily = if AggPeriod < AggregationPeriod.HOUR and AggPeriod >= AggregationPeriod.FIFTEEN_MIN then 1 else 0;
def lessthanweekly = if AggPeriod < AggregationPeriod.DAY and AggPeriod >= AggregationPeriod.HOUR  then 2 else 0;
def lessthanmonthly = if AggPeriod < AggregationPeriod.WEEK and AggPeriod >= AggregationPeriod.DAY  then 3 else 0;
def lessthanyearly = if AggPeriod <= AggregationPeriod.MONTH and AggPeriod >= AggregationPeriod.WEEK then 4 else 0;

def periodselect = lessthanfifteen + lessthandaily + lessthanweekly + lessthanmonthly + lessthanyearly;

AddLabel(shows_labels, if periodselect == 5 then "Daily Profiles" else if periodselect == 1 then "Daily Profiles" else if periodselect == 2 then "Weekly Profiles" else if periodselect == 3 then "Monthly Profiles" else if periodselect == 4 then "Yearly Profiles" else "WTF What Time Frame is this??" ,StudyLabelColor.Color("Labels and Bubbles"));



# =================================
# Volume Profile Definition Section 
# =================================

def profiles = 500;
def multiplier = 1;
def onExpansion = 0;
def yyyymmdd = GetYYYYMMDD();
def seconds = SecondsFromTime(0);



def week = GetWeek();
def month = GetMonth();
def year = GetYear();
def day_number = DaysFromDate(First(yyyymmdd)) + GetDayOfWeek(First(yyyymmdd));
def dom = GetDayOfMonth(yyyymmdd);
def dow = GetDayOfWeek(yyyymmdd - dom + 1);
def expthismonth = (if dow > 5 then 27 else 20) - dow;
def exp_opt = month + (dom > expthismonth);
def height = PricePerRow.TICKSIZE;


def periodA = {default daily, weekly, monthly, yearly, lessthan15};
periodA = if (periodselect == 1) then periodA.daily
    else if (periodselect == 2) then periodA.weekly
    else if (periodselect == 3) then periodA.monthly
    else if (periodselect == 4) then periodA.yearly
    else if (periodselect == 5) then periodA.lessthan15
    else periodA[1];
def period;
switch (periodA) {
case daily:
    period = CountTradingDays(Min(First(yyyymmdd), yyyymmdd), yyyymmdd);
case weekly:
    period = Floor(day_number / 7) - 1;
case monthly:
    period = Floor(month - First(month)) - 1;
case yearly:
    period = Floor(year - First(year)) - 1;
case lessthan15:
    period = CountTradingDays(Min(First(yyyymmdd), yyyymmdd), yyyymmdd);#SecondsFromTime(rthbegin) > 0 and SecondsTillTime(rthend) > 0;
}






rec count = CompoundValue(1, if period != period[1] then (count[1] + period - period[1]) % multiplier else count[1], 0);
def cond = count < count[1] + period - period[1];
 
def count6 = SecondsFromTime(rthbegin) >= 0 and SecondsTillTime(if symbol_check then ahend else if !symbol_check then rthend else double.nan) > 0;# added in this if than statement to handle if symbol is futures or equity and to swap between ending time of trading


def cond6 = count6 != count6[1] or yyyymmdd != yyyymmdd[1]; #added in or yyyymmdd != yyyymmdd[1] to split profiles for overnight equities, since futures use next day once afterhours open only equities will be split by afterhours vs premarket





def condfinal2;
switch (SplitVolumeProfile){
case "No":
    condfinal2 = cond;
case "Yes":
    condfinal2 = cond6;
}
def condfinal1;
switch (periodA){
case "lessthan15":
    condfinal1 = condfinal2;
case "daily":
    condfinal1 = cond;
case "weekly":
    condfinal1 = cond;
case "monthly":
    condfinal1 = cond;
case "yearly":
    condfinal1 = cond;
}




#============================
# Plot POC VAH VAL Section
#============================

profile vol1 = VolumeProfile("startNewProfile" = condfinal1, "onExpansion" = onExpansion, "numberOfProfiles" = profiles, "pricePerRow" = height, "value area percent" = valueAreaPercent);

profile vol2 = (TimeProfile("startNewProfile" = condfinal1, "onExpansion" = onExpansion, "numberOfProfiles" = profiles, "pricePerRow" = height, "value area percent" = valueAreaPercent));

profile vol3 = (if !show_volume_time_profile then VolumeProfile("startNewProfile" = condfinal1, "onExpansion" = onExpansion, "numberOfProfiles" = profiles, "pricePerRow" = height, "value area percent" = valueAreaPercent) else TimeProfile("startNewProfile" = condfinal1, "onExpansion" = onExpansion, "numberOfProfiles" = profiles, "pricePerRow" = height, "value area percent" = valueAreaPercent));
#profile vol1 = TimeProfile("startNewProfile" = condfinal1, "onExpansion" = onExpansion, "numberOfProfiles" = profiles, "pricePerRow" = height, "value area percent" = valueAreaPercent);




rec PC = if cond == 1 then vol1.GetPointOfControl()[1] else PC[1];
rec PC_2 = if cond == 1 then vol2.GetPointOfControl()[1] else PC_2[1];
rec PC_Split = if cond6 == 1 then vol1.GetPointOfControl()[1] else PC_Split[1];
rec PC_Split_2 = if cond6 == 1 then vol2.GetPointOfControl()[1] else PC_Split_2[1];
def PC_Final;
def PC_Final_2;
switch (SplitVolumeProfile){
case "No":
    PC_Final = PC;
    PC_Final_2 = PC_2;
case "Yes":
    PC_Final = PC_Split;
    PC_Final_2 = PC_Split_2;
}

def PCFinal1;
def PCFinal2;
switch (periodA){
case "lessthan15":
    PCFinal1 = PC_Final;
    PCFinal2 = PC_Final_2;
case "daily":
    PCFinal1 = PC;
    PCFinal2 = PC_2;
case "weekly":
    PCFinal1 = PC;
    PCFinal2 = PC_2;
case "monthly":
    PCFinal1 = PC;
    PCFinal2 = PC_2;
case "yearly":
    PCFinal1 = PC;
    PCFinal2 = PC_2;
}

def PC_Final_ = (if poc_calculations == 0 then PCFinal1 else if poc_calculations == 1 then PCFinal2 else if poc_calculations == 2 then ((PCFinal1 + PCFinal2)/2) else Double.NaN);
plot POC = if PC_Final == 0 then double.nan else Round(PC_Final_ / TickSize(), 0) * TickSize();
POC.SetDefaultColor(CreateColor(155,12,231));

        


rec hVA = if cond == 1 then vol1.GetHighestValueArea()[1] else hVA[1];
rec hVA_2 = if cond == 1 then vol2.GetHighestValueArea()[1] else hVA_2[1];
rec hVA_Split = if cond6 == 1 then vol1.GetHighestValueArea()[1] else hVA_Split[1];
rec hVA_Split_2 = if cond6 == 1 then vol2.GetHighestValueArea()[1] else hVA_Split_2[1];
def hVA_Final;
def hVA_Final_2;
switch (SplitVolumeProfile){
case "No":
    hVA_Final = hVA;
    hVA_Final_2 = hVA_2;
case "Yes":
    hVA_Final = hVA_Split;
    hVA_Final_2 = hVA_Split_2;
}

def hVAFinal1;
def hVAFinal2;
switch (periodA){
case "lessthan15":
    hVAFinal1 = hVA_Final;
    hVAFinal2 = hVA_Final_2;
case "daily":
    hVAFinal1 = hVA;
    hVAFinal2 = hVA_2;
case "weekly":
    hVAFinal1 = hVA;
    hVAFinal2 = hVA_2;
case "monthly":
    hVAFinal1 = hVA;
    hVAFinal2 = hVA_2;
case "yearly":
    hVAFinal1 = hVA;
    hVAFinal2 = hVA_2;
}

def hVA_Final_ = (if poc_calculations == 0 then hVAFinal1 else if poc_calculations == 1 then hVAFinal2 else if poc_calculations == 2 then ((hVAFinal1 + hVAFinal2)/2) else Double.NaN);
plot VAH = if hVA_Final == 0 then double.nan else Round(hVA_Final_ / TickSize(), 0) * TickSize();

VAH.SetDefaultColor(CreateColor(224,7,104));


rec lVA = if cond == 1 then vol1.GetLowestValueArea()[1] else lVA[1];
rec lVA_2 = if cond == 1 then vol2.GetLowestValueArea()[1] else lVA_2[1];
rec lVA_Split = if cond6 == 1 then vol1.GetLowestValueArea()[1] else lVA_Split[1];
rec lVA_Split_2 = if cond6 == 1 then vol2.GetLowestValueArea()[1] else lVA_Split_2[1];
def lVA_Final;
def lVA_Final_2;
switch (SplitVolumeProfile){
case "No":
    lVA_Final = lVA;
    lVA_Final_2 = lVA_2;
case "Yes":
    lVA_Final = lVA_Split;
    lVA_Final_2 = lVA_Split_2;
}

def lVAFinal1;
def lVAFinal2;
switch (periodA){
case "lessthan15":
    lVAFinal1 = lVA_Final;
    lVAFinal2 = lVA_Final_2;
case "daily":
    lVAFinal1 = lVA;
    lVAFinal2 = lVA_2;
case "weekly":
    lVAFinal1 = lVA;
    lVAFinal2 = lVA_2;
case "monthly":
    lVAFinal1 = lVA;
    lVAFinal2 = lVA_2;
case "yearly":
    lVAFinal1 = lVA;
    lVAFinal2 = lVA_2;
}

def lVA_Final_ = (if poc_calculations == 0 then lVAFinal1 else if poc_calculations == 1 then lVAFinal2 else if poc_calculations == 2 then ((lVAFinal1 + lVAFinal2)/2) else Double.NaN);
plot VAL = if lVA_Final == 0 then double.nan else Round(lVA_Final_ / TickSize(), 0) * TickSize();
VAL.SetDefaultColor(CreateColor(81,160,86));


POC.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
VAH.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
VAL.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);

#=============================
#Display todays volume profile
#=============================

input showcurrentPointOfControl = no; #Hint showcurrentPointOfControl: Shows the current period's/profiles Point of Control, change color in Globals if needed
input showValueArea = no; #Hint showValueArea: Shows the current period's/profile's Value Area, change color in Globals if needed
input opacity = 25; #Hint opacity: Opacity for displayed Volume Profile

def cloudvah = if !show_cloud then VAH else double.nan;
AddCloud(cloudvah, VAL, GlobalColor("Previous Value Area Cloud"),GlobalColor("Previous Value Area Cloud"));


vol3.Show(GlobalColor("Profile"), if showcurrentPointOfControl then GlobalColor("Today's Point Of Control") else Color.CURRENT, if showValueArea then GlobalColor("Today's Value Area") else Color.CURRENT, opacity);






def firstBarOfDay = if condfinal1[-1] != condfinal1 and condfinal1 != condfinal1 [1] then 1 else 0;

def lastBarOfDay = if condfinal1 [-1] == 1 and condfinal1 == 0 then 1 else 0;

script first_vpoc{
input POC = 0;
input first_bar = 0;
input last_bar = 0;
input poc_counter = 0;
input poc_counter_bar_ago = 0;
def AggPeriod = GetAggregationPeriod();
def price = close(period= AggPeriod);
def price1 = open(period= AggPeriod);
def price2 = high(period= AggPeriod);
def price3 = low(period= AggPeriod);

def vpoc_ = if POC == 0 then double.nan else if last_bar and !poc_counter then POC else vpoc_[1];



plot vpoc = vpoc_;
}

script vpoc_period_price_cross_price_cross_counter{
input POC = 0;
input first_bar = 0;
input last_bar = 0;
def AggPeriod = GetAggregationPeriod();
def price = close(period= AggPeriod);
def price1 = open(period= AggPeriod);
def price2 = high(period= AggPeriod);
def price3 = low(period= AggPeriod);
def count2 = if ((price < POC and price1 > POC) or (price2 > POC and price3 < POC and price < price1)) then 1 else 0;
def count3 = if ((price > POC and price1 < POC) or (price3 < POC and price2 > POC and price > price1)) then 1 else 0;



rec counter_price_cross_counter =if first_bar and (!count2 or !count3) then 0 else if first_bar and (count2 or count3) then 1 else if count2 or count3 then counter_price_cross_counter[1]+1 else counter_price_cross_counter[1];



plot vpoc_counter = counter_price_cross_counter;
}
script virgin_plot_handoff{

input vpoc = 0;
input last_vpoc_date = 0;
input counter_price_cross_counter = 0;
input counter_price_cross_counter_from_bar_ago = 0;

def vpoc_2_ =  if last_vpoc_date != vpoc and counter_price_cross_counter_from_bar_ago == 0 then last_vpoc_date else vpoc_2_[1];


plot vpoc_2 = vpoc_2_;

}

script virgin_plot_price_cross_counter{
input vpoc_2 = 0;
input vpoc_2_bar_ago = 0;

def AggPeriod = GetAggregationPeriod();
def price = close(period= AggPeriod);
def price1 = open(period= AggPeriod);
def price2 = high(period= AggPeriod);
def price3 = low(period= AggPeriod);
def crossing_vpoc_2 = if (price < vpoc_2 and price1 > vpoc_2) then 1 else if (price2 > vpoc_2 and price3 < vpoc_2 and price < price1) then 1 else if (price > vpoc_2 and price1 < vpoc_2) then 1 else if (price3 < vpoc_2 and price2 > vpoc_2 and price > price1) then 1 else 0;

def counter_price_cross_counter_vpoc_2 =if isNaN(vpoc_2_bar_ago) then 0 else if vpoc_2 != vpoc_2_bar_ago then 0 else if crossing_vpoc_2 then counter_price_cross_counter_vpoc_2[1]+1 else counter_price_cross_counter_vpoc_2[1];

plot output = counter_price_cross_counter_vpoc_2;

}


def counter_poc = vpoc_period_price_cross_price_cross_counter(POC, firstBarOfDay, lastBarOfDay);


def first_vpoc_value = first_vpoc(POC,firstBarOfDay,lastBarOfDay,counter_poc,counter_poc[1]);

def vpoc_1_counter = virgin_plot_price_cross_counter(first_vpoc_value, first_vpoc_value[1]);

plot vpoc =  if !vpoc_1_counter and shows_vpocs then first_vpoc_value else Double.NaN;

vpoc.AssignValueColor(VPOC_Color.Color("VPOC Color"));
vpoc.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
vpoc.SetLineWeight(3);


def vpocdate_2 = virgin_plot_handoff(first_vpoc_value,first_vpoc_value[1],vpoc_1_counter, vpoc_1_counter[1]);

def price_cross_counter1 = virgin_plot_price_cross_counter(vpocdate_2,vpocdate_2[1]);

plot vpoc2 = if !price_cross_counter1 and shows_vpocs then vpocdate_2 else Double.NaN;

vpoc2.AssignValueColor(VPOC_Color.Color("VPOC Color"));
vpoc2.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
vpoc2.SetLineWeight(3);

def vpocdate_3 = virgin_plot_handoff(vpocdate_2,vpocdate_2[1],price_cross_counter1,price_cross_counter1[1]);
def price_cross_counter3 = virgin_plot_price_cross_counter(vpocdate_3,vpocdate_3[1]);
plot vpoc3 = if !price_cross_counter3 and shows_vpocs then vpocdate_3 else Double.NaN;
vpoc3.AssignValueColor(VPOC_Color.Color("VPOC Color"));
vpoc3.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
vpoc3.SetLineWeight(3);

def vpocdate_4 = virgin_plot_handoff(vpocdate_3,vpocdate_3[1],price_cross_counter3,price_cross_counter3[1]);
def price_cross_counter4 = virgin_plot_price_cross_counter(vpocdate_4,vpocdate_4[1]);
plot vpoc4 = if !price_cross_counter4 and shows_vpocs then vpocdate_4 else Double.NaN;
vpoc4.AssignValueColor(VPOC_Color.Color("VPOC Color"));
vpoc4.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
vpoc4.SetLineWeight(3);

def vpocdate_5 = virgin_plot_handoff(vpocdate_4,vpocdate_4[1],price_cross_counter4,price_cross_counter4[1]);
def price_cross_counter5 = virgin_plot_price_cross_counter(vpocdate_5,vpocdate_5[1]);
plot vpoc5 = if !price_cross_counter5 and shows_vpocs then vpocdate_5 else Double.NaN;
vpoc5.AssignValueColor(VPOC_Color.Color("VPOC Color"));
vpoc5.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
vpoc5.SetLineWeight(3);

def vpocdate_6 = virgin_plot_handoff(vpocdate_5,vpocdate_5[1],price_cross_counter5,price_cross_counter5[1]);
def price_cross_counter6 = virgin_plot_price_cross_counter(vpocdate_6,vpocdate_6[1]);
plot vpoc6 = if !price_cross_counter6 and shows_vpocs then vpocdate_6 else Double.NaN;
vpoc6.AssignValueColor(VPOC_Color.Color("VPOC Color"));
vpoc6.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
vpoc6.SetLineWeight(3);

def vpocdate_7 = virgin_plot_handoff(vpocdate_6,vpocdate_6[1],price_cross_counter6,price_cross_counter6[1]);
def price_cross_counter7 = virgin_plot_price_cross_counter(vpocdate_7,vpocdate_7[1]);
plot vpoc7 = if !price_cross_counter7 and shows_vpocs then vpocdate_7 else Double.NaN;
vpoc7.AssignValueColor(VPOC_Color.Color("VPOC Color"));
vpoc7.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
vpoc7.SetLineWeight(3);

def vpocdate_8 = virgin_plot_handoff(vpocdate_7,vpocdate_7[1],price_cross_counter7,price_cross_counter7[1]);
def price_cross_counter8 = virgin_plot_price_cross_counter(vpocdate_8,vpocdate_8[1]);
plot vpoc8 = if !price_cross_counter8 and shows_vpocs then vpocdate_8 else Double.NaN;
vpoc8.AssignValueColor(VPOC_Color.Color("VPOC Color"));
vpoc8.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
vpoc8.SetLineWeight(3);

def vpocdate_9 = virgin_plot_handoff(vpocdate_8,vpocdate_8[1],price_cross_counter8,price_cross_counter8[1]);
def price_cross_counter9 = virgin_plot_price_cross_counter(vpocdate_9,vpocdate_9[1]);
plot vpoc9 = if !price_cross_counter9 and shows_vpocs then vpocdate_9 else Double.NaN;
vpoc9.AssignValueColor(VPOC_Color.Color("VPOC Color"));
vpoc9.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
vpoc9.SetLineWeight(3);

def vpocdate_10 = virgin_plot_handoff(vpocdate_9,vpocdate_9[1],price_cross_counter9,price_cross_counter9[1]);
def price_cross_counter10 = virgin_plot_price_cross_counter(vpocdate_10,vpocdate_10[1]);
plot vpoc10 = if !price_cross_counter10 and shows_vpocs then vpocdate_10 else Double.NaN;
vpoc10.AssignValueColor(VPOC_Color.Color("VPOC Color"));
vpoc10.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
vpoc10.SetLineWeight(3);

def counter_vah = vpoc_period_price_cross_price_cross_counter(VAH, firstBarOfDay, lastBarOfDay);


def first_vvah_value = first_vpoc(VAH,firstBarOfDay,lastBarOfDay,counter_vah,counter_vah[1]);

def vvah_1_counter = virgin_plot_price_cross_counter(first_vvah_value, first_vvah_value[1]);

plot vvah =  if !vvah_1_counter and shows_vvah then first_vvah_value else Double.NaN;

vvah.AssignValueColor(VVAH_Color.Color("VVAH Color"));
vvah.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
vvah.SetLineWeight(3);

def vvahdate_2 = virgin_plot_handoff(first_vvah_value,first_vvah_value[1],vvah_1_counter, vvah_1_counter[1]);

def vvah_price_cross_counter1 = virgin_plot_price_cross_counter(vvahdate_2,vvahdate_2[1]);

plot vvah2 = if !vvah_price_cross_counter1 and shows_vvah then vvahdate_2 else Double.NaN;

vvah2.AssignValueColor(VVAH_Color.Color("VVAH Color"));
vvah2.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
vvah2.SetLineWeight(3);

def vvahdate_3 = virgin_plot_handoff(vvahdate_2,vvahdate_2[1],vvah_price_cross_counter1,vvah_price_cross_counter1[1]);
def vvah_price_cross_counter3 = virgin_plot_price_cross_counter(vvahdate_3,vvahdate_3[1]);
plot vvah3 = if !vvah_price_cross_counter3 and shows_vvah then vvahdate_3 else Double.NaN;
vvah3.AssignValueColor(VVAH_Color.Color("VVAH Color"));
vvah3.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
vvah3.SetLineWeight(3);

def vvahdate_4 = virgin_plot_handoff(vvahdate_3,vvahdate_3[1],vvah_price_cross_counter3,vvah_price_cross_counter3[1]);
def vvah_price_cross_counter4 = virgin_plot_price_cross_counter(vvahdate_4,vvahdate_4[1]);
plot vvah4 = if !vvah_price_cross_counter4 and shows_vvah then vvahdate_4 else Double.NaN;
vvah4.AssignValueColor(VVAH_Color.Color("VVAH Color"));
vvah4.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
vvah4.SetLineWeight(3);


def vvahdate_5 = virgin_plot_handoff(vvahdate_4,vvahdate_4[1],vvah_price_cross_counter4,vvah_price_cross_counter4[1]);
def vvah_price_cross_counter5 = virgin_plot_price_cross_counter(vvahdate_5,vvahdate_5[1]);
plot vvah5 = if !vvah_price_cross_counter5 and shows_vvah then vvahdate_5 else Double.NaN;
vvah5.AssignValueColor(VVAH_Color.Color("VVAH Color"));
vvah5.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
vvah5.SetLineWeight(3);


def vvahdate_6 = virgin_plot_handoff(vvahdate_5,vvahdate_5[1],vvah_price_cross_counter5,vvah_price_cross_counter5[1]);
def vvah_price_cross_counter6 = virgin_plot_price_cross_counter(vvahdate_6,vvahdate_6[1]);
plot vvah6 = if !vvah_price_cross_counter6 and shows_vvah then vvahdate_6 else Double.NaN;
vvah6.AssignValueColor(VVAH_Color.Color("VVAH Color"));
vvah6.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
vvah6.SetLineWeight(3);

def vvahdate_7 = virgin_plot_handoff(vvahdate_6,vvahdate_6[1],vvah_price_cross_counter6,vvah_price_cross_counter6[1]);
def vvah_price_cross_counter7 = virgin_plot_price_cross_counter(vvahdate_7,vvahdate_7[1]);
plot vvah7 = if !vvah_price_cross_counter7 and shows_vvah then vvahdate_7 else Double.NaN;
vvah7.AssignValueColor(VVAH_Color.Color("VVAH Color"));
vvah7.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
vvah7.SetLineWeight(3);


def vvahdate_8 = virgin_plot_handoff(vvahdate_7,vvahdate_7[1],vvah_price_cross_counter7,vvah_price_cross_counter7[1]);
def vvah_price_cross_counter8 = virgin_plot_price_cross_counter(vvahdate_8,vvahdate_8[1]);
plot vvah8 = if !vvah_price_cross_counter8 and shows_vvah then vvahdate_8 else Double.NaN;
vvah8.AssignValueColor(VVAH_Color.Color("VVAH Color"));
vvah8.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
vvah8.SetLineWeight(3);


def vvahdate_9 = virgin_plot_handoff(vvahdate_8,vvahdate_8[1],vvah_price_cross_counter8,vvah_price_cross_counter8[1]);
def vvah_price_cross_counter9 = virgin_plot_price_cross_counter(vvahdate_9,vvahdate_9[1]);
plot vvah9 = if !vvah_price_cross_counter9 and shows_vvah then vvahdate_9 else Double.NaN;
vvah9.AssignValueColor(VVAH_Color.Color("VVAH Color"));
vvah9.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
vvah9.SetLineWeight(3);


def vvahdate_10 = virgin_plot_handoff(vvahdate_9,vvahdate_9[1],vvah_price_cross_counter9,vvah_price_cross_counter9[1]);
def vvah_price_cross_counter10 = virgin_plot_price_cross_counter(vvahdate_10,vvahdate_10[1]);
plot vvah10 = if !vvah_price_cross_counter10 and shows_vvah then vvahdate_10 else Double.NaN;
vvah10.AssignValueColor(VVAH_Color.Color("VVAH Color"));
vvah10.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
vvah10.SetLineWeight(3);

def counter_val = vpoc_period_price_cross_price_cross_counter(val, firstBarOfDay, lastBarOfDay);


def first_vval_value = first_vpoc(val,firstBarOfDay,lastBarOfDay,counter_val,counter_val[1]);

def vval_1_counter = virgin_plot_price_cross_counter(first_vval_value, first_vval_value[1]);

plot vval =  if !vval_1_counter and shows_vval then first_vval_value else Double.NaN;

vval.AssignValueColor(VVAL_Color.Color("VVAL Color"));
vval.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
vval.SetLineWeight(3);

def vvaldate_2 = virgin_plot_handoff(first_vval_value,first_vval_value[1],vval_1_counter, vval_1_counter[1]);

def vval_price_cross_counter1 = virgin_plot_price_cross_counter(vvaldate_2,vvaldate_2[1]);

plot vval2 = if !vval_price_cross_counter1 and shows_vval then vvaldate_2 else Double.NaN;

vval2.AssignValueColor(VVAL_Color.Color("VVAL Color"));
vval2.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
vval2.SetLineWeight(3);

def vvaldate_3 = virgin_plot_handoff(vvaldate_2,vvaldate_2[1],vval_price_cross_counter1,vval_price_cross_counter1[1]);
def vval_price_cross_counter3 = virgin_plot_price_cross_counter(vvaldate_3,vvaldate_3[1]);
plot vval3 = if !vval_price_cross_counter3 and shows_vval then vvaldate_3 else Double.NaN;
vval3.AssignValueColor(VVAL_Color.Color("VVAL Color"));
vval3.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
vval3.SetLineWeight(3);

def vvaldate_4 = virgin_plot_handoff(vvaldate_3,vvaldate_3[1],vval_price_cross_counter3,vval_price_cross_counter3[1]);
def vval_price_cross_counter4 = virgin_plot_price_cross_counter(vvaldate_4,vvaldate_4[1]);
plot vval4 = if !vval_price_cross_counter4 and shows_vval then vvaldate_4 else Double.NaN;
vval4.AssignValueColor(VVAL_Color.Color("VVAL Color"));
vval4.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
vval4.SetLineWeight(3);

def vvaldate_5 = virgin_plot_handoff(vvaldate_4,vvaldate_4[1],vval_price_cross_counter4,vval_price_cross_counter4[1]);
def vval_price_cross_counter5 = virgin_plot_price_cross_counter(vvaldate_5,vvaldate_5[1]);
plot vval5 = if !vval_price_cross_counter5 and shows_vval then vvaldate_5 else Double.NaN;
vval5.AssignValueColor(VVAL_Color.Color("VVAL Color"));
vval5.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
vval5.SetLineWeight(3);

def vvaldate_6 = virgin_plot_handoff(vvaldate_5,vvaldate_5[1],vval_price_cross_counter5,vval_price_cross_counter5[1]);
def vval_price_cross_counter6 = virgin_plot_price_cross_counter(vvaldate_6,vvaldate_6[1]);
plot vval6 = if !vval_price_cross_counter6 and shows_vval then vvaldate_6 else Double.NaN;
vval6.AssignValueColor(VVAL_Color.Color("VVAL Color"));
vval6.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
vval6.SetLineWeight(3);

def vvaldate_7 = virgin_plot_handoff(vvaldate_6,vvaldate_6[1],vval_price_cross_counter6,vval_price_cross_counter6[1]);
def vval_price_cross_counter7 = virgin_plot_price_cross_counter(vvaldate_7,vvaldate_7[1]);
plot vval7 = if !vval_price_cross_counter7 and shows_vval then vvaldate_7 else Double.NaN;
vval7.AssignValueColor(VVAL_Color.Color("VVAL Color"));
vval7.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
vval7.SetLineWeight(3);

def vvaldate_8 = virgin_plot_handoff(vvaldate_7,vvaldate_7[1],vval_price_cross_counter7,vval_price_cross_counter7[1]);
def vval_price_cross_counter8 = virgin_plot_price_cross_counter(vvaldate_8,vvaldate_8[1]);
plot vval8 = if !vval_price_cross_counter8 and shows_vval then vvaldate_8 else Double.NaN;
vval8.AssignValueColor(VVAL_Color.Color("VVAL Color"));
vval8.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
vval8.SetLineWeight(3);

def vvaldate_9 = virgin_plot_handoff(vvaldate_8,vvaldate_8[1],vval_price_cross_counter8,vval_price_cross_counter8[1]);
def vval_price_cross_counter9 = virgin_plot_price_cross_counter(vvaldate_9,vvaldate_9[1]);
plot vval9 = if !vval_price_cross_counter9 and shows_vval then vvaldate_9 else Double.NaN;
vval9.AssignValueColor(VVAL_Color.Color("VVAL Color"));
vval9.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
vval9.SetLineWeight(3);

def vvaldate_10 = virgin_plot_handoff(vvaldate_9,vvaldate_9[1],vval_price_cross_counter9,vval_price_cross_counter9[1]);
def vval_price_cross_counter10 = virgin_plot_price_cross_counter(vvaldate_10,vvaldate_10[1]);
plot vval10 = if !vval_price_cross_counter10 and shows_vval then vvaldate_10 else Double.NaN;
vval10.AssignValueColor(VVAL_Color.Color("VVAL Color"));
vval10.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
vval10.SetLineWeight(3);



def profilebubbles;
if (IsNaN(close[4]) and !IsNaN(close[5]) and bubbles_profiles_number)
then {
    profilebubbles = yes;
} else {
    profilebubbles = no;
}


def vahbubble = if IsNaN(VAH[-1]) then VAH[5] else VAH[-1];
def valbubble = if IsNaN(VAL[-1]) then VAL[5] else VAL[-1];
def pocbubble = if IsNaN(POC[-1]) then POC[5] else POC[-1];



AddChartBubble( profilebubbles, vahbubble, "VAH: " + vahbubble,StudyLabelColor.Color("Labels and Bubbles"), no);
AddChartBubble( profilebubbles, valbubble, "VAL: " + valbubble, StudyLabelColor.Color("Labels and Bubbles"), yes);
AddChartBubble( profilebubbles, pocbubble, "POC: " + pocbubble, StudyLabelColor.Color("Labels and Bubbles"), yes);

def vpoc_count = if isNaN(vpoc) then 0 else 1;
def vpoc_count2 = if !isNaN(vpoc2) then 1 else 0;
def vpoc_count3 = if !isNaN(vpoc3) then 1 else 0;
def vpoc_count4 = if !isNaN(vpoc4) then 1 else 0;
def vpoc_count5 = if !isNaN(vpoc5) then 1 else 0;
def vpoc_count6 = if !isNaN(vpoc6) then 1 else 0;
def vpoc_count7 = if !isNaN(vpoc7) then 1 else 0;
def vpoc_count8 = if !isNaN(vpoc8) then 1 else 0;
def vpoc_count9 = if !isNaN(vpoc9) then 1 else 0;
def vpoc_count10 = if !isNaN(vpoc10) then 1 else 0;

def vpoc_count_total = vpoc_count + vpoc_count2 + vpoc_count3 +vpoc_count4 + vpoc_count5 + vpoc_count6 + vpoc_count7 + vpoc_count8 + vpoc_count9 + vpoc_count10;

AddLabel(shows_stats_labels,"Number of Virgin Point of Controls in Use: " + vpoc_count_total,StudyLabelColor.Color("Labels and Bubbles"));

def vvah_count = if isNaN(vvah) then 0 else 1;
def vvah_count2 = if !isNaN(vvah2) then 1 else 0;
def vvah_count3 = if !isNaN(vvah3) then 1 else 0;
def vvah_count4 = if !isNaN(vvah4) then 1 else 0;
def vvah_count5 = if !isNaN(vvah5) then 1 else 0;
def vvah_count6 = if !isNaN(vvah6) then 1 else 0;
def vvah_count7 = if !isNaN(vvah7) then 1 else 0;
def vvah_count8 = if !isNaN(vvah8) then 1 else 0;
def vvah_count9 = if !isNaN(vvah9) then 1 else 0;
def vvah_count10 = if !isNaN(vvah10) then 1 else 0;

def vvah_count_total = vvah_count + vvah_count2 + vvah_count3 +vvah_count4 + vvah_count5 + vvah_count6 + vvah_count7 + vvah_count8 + vvah_count9 + vvah_count10;


AddLabel(shows_stats_labels,"Number of Virgin Value Area High in Use: " + vvah_count_total,StudyLabelColor.Color("Labels and Bubbles"));

def vval_count = if isNaN(vval) then 0 else 1;
def vval_count2 = if !isNaN(vval2) then 1 else 0;
def vval_count3 = if !isNaN(vval3) then 1 else 0;
def vval_count4 = if !isNaN(vval4) then 1 else 0;
def vval_count5 = if !isNaN(vval5) then 1 else 0;
def vval_count6 = if !isNaN(vval6) then 1 else 0;
def vval_count7 = if !isNaN(vval7) then 1 else 0;
def vval_count8 = if !isNaN(vval8) then 1 else 0;
def vval_count9 = if !isNaN(vval9) then 1 else 0;
def vval_count10 = if !isNaN(vval10) then 1 else 0;

def vval_count_total = vval_count + vval_count2 + vval_count3 +vval_count4 + vval_count5 + vval_count6 + vval_count7 + vval_count8 + vval_count9 + vval_count10;

AddLabel(shows_stats_labels,"Number of Virgin Value Area Low in Use: " + vval_count_total,StudyLabelColor.Color("Labels and Bubbles"));

