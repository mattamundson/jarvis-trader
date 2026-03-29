plot priceLine = highestAll(if isNaN(close[-1]) 
                            then close
                            else Double.NaN);
priceLine.SetStyle(Curve.Short_Dash);
priceLine.SetLineWeight(1);
priceLine.SetDefaultColor(CreateColor(233,21,89));

