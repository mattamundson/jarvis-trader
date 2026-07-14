"use client";

import React, { useState, useCallback, useEffect } from "react";
import { AlertTriangle, ChevronDown, BarChart3, Check, X } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { fetchEngine, postEngine } from "@/lib/api";
import { cn, formatCurrency, formatPercent } from "@/lib/utils";

const DEFAULT_SYMBOLS = ["MES", "MNQ", "SPY", "QQQ"];

type OrderDirection = "BUY" | "SELL";
type OrderType = "MARKET" | "LIMIT";
type FeedbackState = "none" | "loading" | "success" | "error";

interface OrderEntryPanelProps {
  onOrderSubmitted?: () => void;
}

export function OrderEntryPanel({ onOrderSubmitted }: OrderEntryPanelProps) {
  // Form state
  const [symbol, setSymbol] = useState<string>("MES");
  const [direction, setDirection] = useState<OrderDirection>("BUY");
  const [quantity, setQuantity] = useState<number>(1);
  const [orderType, setOrderType] = useState<OrderType>("MARKET");
  const [limitPrice, setLimitPrice] = useState<number | null>(null);
  const [stopLoss, setStopLoss] = useState<number | null>(null);
  const [takeProfit, setTakeProfit] = useState<number | null>(null);

  // UI state
  const [expanded, setExpanded] = useState(true);
  const [showSymbolDropdown, setShowSymbolDropdown] = useState(false);
  const [feedback, setFeedback] = useState<FeedbackState>("none");
  const [feedbackMessage, setFeedbackMessage] = useState("");
  const [confirmSubmit, setConfirmSubmit] = useState(false);
  const [atrLoading, setAtrLoading] = useState(false);
  const [atrData, setAtrData] = useState<{ atr: number; currentPrice: number } | null>(null);

  // Clear feedback after 5s
  useEffect(() => {
    if (feedback === "success" || feedback === "error") {
      const timer = setTimeout(() => setFeedback("none"), 5000);
      return () => clearTimeout(timer);
    }
  }, [feedback]);

  // Clear confirmation after 5s
  useEffect(() => {
    if (confirmSubmit) {
      const timer = setTimeout(() => setConfirmSubmit(false), 5000);
      return () => clearTimeout(timer);
    }
  }, [confirmSubmit]);

  // Calculate risk in dollars
  const estimatedRisk = stopLoss && orderType === "MARKET"
    ? Math.abs(5000 - (stopLoss || 5000)) * quantity
    : null;

  // Calculate risk:reward ratio
  const rrRatio = estimatedRisk && stopLoss && takeProfit
    ? Math.abs((takeProfit - 5000) * quantity) / estimatedRisk
    : null;

  // Check if position size exceeds safety limits
  const notionalValue = (limitPrice || 5000) * quantity * 50; // MES multiplier
  const exceedsLimit = notionalValue > 250000; // Safety limit

  const handleCalculateATR = useCallback(async () => {
    if (!symbol) return;

    setAtrLoading(true);
    try {
      const response = await fetchEngine<{
        atr: number;
        close: number;
      }>(`/analyze/bars/${symbol}`);

      const currentPrice = response.close || 5000;
      const atr = response.atr || 0;

      setAtrData({ atr, currentPrice });

      // Calculate stop loss and take profit
      if (direction === "BUY") {
        setStopLoss(currentPrice - atr);
        setTakeProfit(currentPrice + atr * 2);
      } else {
        setStopLoss(currentPrice + atr);
        setTakeProfit(currentPrice - atr * 2);
      }

      setFeedback("success");
      setFeedbackMessage(`ATR: ${atr.toFixed(2)} | Price: ${currentPrice.toFixed(2)}`);
    } catch (e) {
      console.error("ATR calculation failed:", e);
      setFeedback("error");
      setFeedbackMessage("Failed to fetch ATR data");
    } finally {
      setAtrLoading(false);
    }
  }, [symbol, direction]);

  const handleSubmitOrder = useCallback(async () => {
    if (!confirmSubmit) {
      setConfirmSubmit(true);
      return;
    }

    if (quantity < 1 || quantity > 10) {
      setFeedback("error");
      setFeedbackMessage("Quantity must be between 1 and 10");
      return;
    }

    setFeedback("loading");
    try {
      const orderPayload = {
        symbol,
        direction,
        quantity,
        order_type: orderType,
        limit_price: orderType === "LIMIT" ? limitPrice : null,
        stop_loss: stopLoss,
        take_profit: takeProfit,
      };

      await postEngine("/orders/place", orderPayload);

      setFeedback("success");
      setFeedbackMessage("Order submitted successfully");

      // Reset form
      setSymbol("MES");
      setDirection("BUY");
      setQuantity(1);
      setOrderType("MARKET");
      setLimitPrice(null);
      setStopLoss(null);
      setTakeProfit(null);
      setConfirmSubmit(false);

      onOrderSubmitted?.();
    } catch (e) {
      console.error("Order submission failed:", e);
      setFeedback("error");
      setFeedbackMessage(e instanceof Error ? e.message : "Failed to submit order");
    }
  }, [confirmSubmit, symbol, direction, quantity, orderType, limitPrice, stopLoss, takeProfit, onOrderSubmitted]);

  if (!expanded) {
    return (
      <button
        onClick={() => setExpanded(true)}
        className="w-full rounded-xl border border-border bg-card p-4 text-left text-xs font-semibold uppercase tracking-wider text-accent hover:bg-card/80 transition-colors"
      >
        + Order Entry
      </button>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Order Entry</CardTitle>
          <button
            onClick={() => setExpanded(false)}
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            ×
          </button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Feedback banner */}
        {feedback === "success" && (
          <div className="rounded-lg bg-bull/20 border border-bull/40 p-3 flex items-center gap-2">
            <Check className="h-4 w-4 text-bull shrink-0" />
            <span className="text-xs text-bull font-medium">{feedbackMessage}</span>
          </div>
        )}
        {feedback === "error" && (
          <div className="rounded-lg bg-bear/30 border border-bear/50 p-3 flex items-center gap-2">
            <X className="h-4 w-4 text-bear shrink-0" />
            <span className="text-xs text-bear font-medium">{feedbackMessage}</span>
          </div>
        )}

        {/* Symbol selector */}
        <div className="space-y-2">
          <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Symbol
          </label>
          <div className="relative">
            <button
              onClick={() => setShowSymbolDropdown(!showSymbolDropdown)}
              className="w-full rounded-lg border border-border bg-background px-3 py-2 text-left text-sm font-mono font-semibold uppercase flex items-center justify-between hover:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent"
            >
              {symbol}
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            </button>
            {showSymbolDropdown && (
              <div className="absolute top-full left-0 right-0 mt-1 border border-border bg-background rounded-lg z-10 overflow-hidden shadow-lg">
                {DEFAULT_SYMBOLS.map((sym) => (
                  <button
                    key={sym}
                    onClick={() => {
                      setSymbol(sym);
                      setShowSymbolDropdown(false);
                    }}
                    className={cn(
                      "w-full text-left px-3 py-2 text-sm font-mono font-semibold uppercase transition-colors hover:bg-muted/40",
                      symbol === sym ? "bg-muted/60 text-accent" : ""
                    )}
                  >
                    {sym}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Direction toggle */}
        <div className="space-y-2">
          <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Direction
          </label>
          <div className="flex gap-2">
            <button
              onClick={() => setDirection("BUY")}
              className={cn(
                "flex-1 rounded-lg py-2 text-sm font-semibold transition-colors",
                direction === "BUY"
                  ? "bg-bull text-white"
                  : "border border-bull/40 text-bull hover:bg-bull/10"
              )}
            >
              BUY
            </button>
            <button
              onClick={() => setDirection("SELL")}
              className={cn(
                "flex-1 rounded-lg py-2 text-sm font-semibold transition-colors",
                direction === "SELL"
                  ? "bg-bear text-white"
                  : "border border-bear/40 text-bear hover:bg-bear/10"
              )}
            >
              SELL
            </button>
          </div>
        </div>

        {/* Quantity */}
        <div className="space-y-2">
          <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Quantity
          </label>
          <div className="flex gap-2 items-center">
            <button
              onClick={() => setQuantity(Math.max(1, quantity - 1))}
              className="rounded-lg border border-border bg-background px-2 py-1 text-sm font-mono hover:bg-muted transition-colors"
            >
              -
            </button>
            <input
              type="number"
              min="1"
              max="10"
              value={quantity}
              onChange={(e) => setQuantity(Math.max(1, Math.min(10, parseInt(e.target.value) || 1)))}
              className="flex-1 rounded-lg border border-border bg-background px-3 py-1 text-center text-sm font-mono font-semibold focus:outline-none focus:ring-1 focus:ring-accent"
            />
            <button
              onClick={() => setQuantity(Math.min(10, quantity + 1))}
              className="rounded-lg border border-border bg-background px-2 py-1 text-sm font-mono hover:bg-muted transition-colors"
            >
              +
            </button>
          </div>
        </div>

        {/* Order Type */}
        <div className="space-y-2">
          <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Order Type
          </label>
          <select
            value={orderType}
            onChange={(e) => setOrderType(e.target.value as OrderType)}
            className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm font-mono font-semibold uppercase focus:outline-none focus:ring-1 focus:ring-accent"
          >
            <option value="MARKET">Market</option>
            <option value="LIMIT">Limit</option>
          </select>
        </div>

        {/* Limit Price (conditional) */}
        {orderType === "LIMIT" && (
          <div className="space-y-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Limit Price
            </label>
            <input
              type="number"
              step="0.01"
              value={limitPrice || ""}
              onChange={(e) => setLimitPrice(e.target.value ? parseFloat(e.target.value) : null)}
              className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm font-mono font-semibold focus:outline-none focus:ring-1 focus:ring-accent"
              placeholder="e.g., 5000.00"
            />
          </div>
        )}

        {/* Stop Loss */}
        <div className="space-y-2">
          <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Stop Loss
          </label>
          <input
            type="number"
            step="0.01"
            value={stopLoss || ""}
            onChange={(e) => setStopLoss(e.target.value ? parseFloat(e.target.value) : null)}
            className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm font-mono font-semibold focus:outline-none focus:ring-1 focus:ring-accent"
            placeholder="e.g., 4950.00"
          />
        </div>

        {/* Take Profit */}
        <div className="space-y-2">
          <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Take Profit
          </label>
          <input
            type="number"
            step="0.01"
            value={takeProfit || ""}
            onChange={(e) => setTakeProfit(e.target.value ? parseFloat(e.target.value) : null)}
            className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm font-mono font-semibold focus:outline-none focus:ring-1 focus:ring-accent"
            placeholder="e.g., 5050.00"
          />
        </div>

        {/* Calculate from ATR button */}
        <button
          onClick={handleCalculateATR}
          disabled={atrLoading || !symbol}
          className="w-full rounded-lg border border-border bg-background/50 px-3 py-2 text-xs font-semibold text-muted-foreground uppercase hover:bg-background disabled:opacity-40 transition-colors flex items-center justify-center gap-2"
        >
          <BarChart3 className="h-3.5 w-3.5" />
          {atrLoading ? "Fetching ATR..." : "Calculate from ATR"}
        </button>

        {/* Order Preview */}
        <div className="rounded-lg bg-muted/40 p-3 space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Order Preview
          </p>
          <div className="space-y-1 text-xs">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Direction</span>
              <span className={`font-mono font-semibold ${direction === "BUY" ? "text-bull" : "text-bear"}`}>
                {direction}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Symbol × Qty</span>
              <span className="font-mono font-semibold">{symbol} × {quantity}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Order Type</span>
              <span className="font-mono font-semibold">{orderType}</span>
            </div>
            {orderType === "LIMIT" && limitPrice && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">Price</span>
                <span className="font-mono font-semibold">${limitPrice.toFixed(2)}</span>
              </div>
            )}
            {stopLoss && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">Stop Loss</span>
                <span className="font-mono font-semibold text-bear">${stopLoss.toFixed(2)}</span>
              </div>
            )}
            {takeProfit && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">Take Profit</span>
                <span className="font-mono font-semibold text-bull">${takeProfit.toFixed(2)}</span>
              </div>
            )}
            {estimatedRisk && (
              <div className="flex justify-between pt-1 border-t border-border/50">
                <span className="text-muted-foreground">Est. Risk ($)</span>
                <span className="font-mono font-semibold">${estimatedRisk.toFixed(0)}</span>
              </div>
            )}
            {rrRatio && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">R:R Ratio</span>
                <span className="font-mono font-semibold">{rrRatio.toFixed(2)}:1</span>
              </div>
            )}
          </div>
        </div>

        {/* Risk warning */}
        {exceedsLimit && (
          <div className="rounded-lg bg-bear/20 border border-bear/40 p-3 flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-bear shrink-0" />
            <span className="text-xs text-bear font-medium">
              Position size exceeds safety limits ($250k notional)
            </span>
          </div>
        )}

        {/* Submit button */}
        <button
          onClick={handleSubmitOrder}
          disabled={feedback === "loading" || exceedsLimit}
          className={cn(
            "w-full rounded-lg py-2 text-sm font-semibold transition-all",
            confirmSubmit
              ? "bg-accent text-white animate-pulse"
              : "bg-accent/20 text-accent hover:bg-accent/30",
            "disabled:opacity-50 disabled:cursor-not-allowed"
          )}
        >
          {feedback === "loading"
            ? "Submitting…"
            : confirmSubmit
            ? "⚠ CLICK AGAIN TO CONFIRM"
            : "Submit Order"}
        </button>
      </CardContent>
    </Card>
  );
}
