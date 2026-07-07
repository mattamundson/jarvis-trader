input price = close;
input displace = 0;
input length = 21;
input period = AggregationPeriod.FIVE_MIN;
input averageType1 = AverageType.Simple;
input averageType2 = AverageType.expoNENTIAL;


plot MA_SMA = MovingAverage(averageType1, close(period = period) [-displace], length = length); 


MA_SMA.AssignValueColor(Color.dark_oRANGE);

plot MA_EMA = MovingAverage(averageType2, close(period = period) [-displace], length = length); 


MA_EMA.AssignValueColor(Color.orange);

AddCloud(MA_EMA,MA_SMA,Color.light_gray,Color.grAY);

plot MID = (MA_SMA+MA_EMA)/2;
MID.AssignValueColor(Color.dark_GRAY);
