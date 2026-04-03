def hyg_diff = close("HYG")- close("HYG")[2];
def spx_diff = close("SPX")-close("SPX")[2];

#AssignPriceColor(if hyg_diff < 0 and spx_diff > 0 then Color.ORANGE else Color.GRAY);
AssignPriceColor(if (low[1] - high) > 0.10 then Color.CYAN else if (high[1] - low) < 0.10 then Color.ORANGE else Color.GRAY);
#(if close("VIX")< open("VIX") and close("/VX")> open("/VX") then Color.ORANGE else
