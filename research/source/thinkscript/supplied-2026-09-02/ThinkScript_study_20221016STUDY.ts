input anchorDate = 20200422;
input anchorTime = 2030;

def revisedDate = anchorDate;

def postAnchorDate = if GetYYYYMMDD() > revisedDate then 1 else if GetYYYYMMDD () == revisedDate and anchorTime >= 1800 and SecondsTillTime (anchorTime) <=0 then 1 else if GetYYYYMMDD() == revisedDate and anchorTime <= 1700 and SecondsFromTime (1700) <= 0 and SecondsTillTime (anchorTime) <= 0 then 1 else 0;


plot anchoredVWAP = TotalSum(if postAnchorDate then ((high+low+close)/3)*(volume) else 0)/TotalSum(if postAnchorDate then volume else 0);

anchoredVWAP.setStyle(Curve.Firm);
anchoredVWAP.SetLineWeight(3);
anchoredVWAP.SetDefaultColor(Color.Cyan);

#AddChartBubble(yes,close, revisedDate, color.yellow);

