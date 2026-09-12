def trin_price = close("$trin");
def trin_price2 = high("$trin");
def vvix_price = close("vvix");

AssignPriceColor(if trin_price < 0.6 and trin_price2 < 1.00 and vvix_price < 120 then color.MAGENTA else if trin_price > 2.0 and low("$trin")>1.00 and close("VIX")>30 then Color.CYAN else Color.CURRENT);
