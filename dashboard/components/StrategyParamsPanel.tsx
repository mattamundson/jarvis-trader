"use client";

import React, { useState } from "react";
import useSWR from "swr";
import { ChevronDown, ChevronUp, AlertCircle, RefreshCw } from "lucide-react";
import { fetchEngine, postEngine } from "@/lib/api";

interface StrategyParams {
  current: {
    stc_oversold: number;
    stc_overbought: number;
    atr_stop_multiplier: number;
    atr_target1_multiplier: number;
    regime_filter_enabled: boolean;
  };
  optimizer_recommended: {
    stc_oversold: number;
    stc_overbought: number;
    atr_stop_multiplier: number;
    atr_target1_multiplier: number;
    regime_filter_enabled: boolean;
  };
}

interface AdjustmentRequest {
  stc_oversold?: number;
  stc_overbought?: number;
  atr_stop_multiplier?: number;
  atr_target1_multiplier?: number;
  regime_filter_enabled?: boolean;
}

function fetcher<T = unknown>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

export function StrategyParamsPanel() {
  const { data: params, mutate: mutateParams, isLoading } = useSWR<StrategyParams>(
    "/strategy/params",
    fetcher,
    { refreshInterval: 30000 }
  );

  const [isExpanded, setIsExpanded] = useState(false);
  const [showAdjustment, setShowAdjustment] = useState(false);
  const [isApplying, setIsApplying] = useState(false);
  const [adjustments, setAdjustments] = useState<AdjustmentRequest>({});
  const [confirmDialog, setConfirmDialog] = useState(false);

  const handleAdjustment = (key: keyof AdjustmentRequest, value: number | boolean) => {
    setAdjustments((prev) => ({ ...prev, [key]: value }));
  };

  const handleApply = async () => {
    setIsApplying(true);
    try {
      const result = await postEngine<StrategyParams>("/strategy/params", adjustments);
      mutateParams(result);
      setAdjustments({});
      setShowAdjustment(false);
      setConfirmDialog(false);
    } catch (e) {
      console.error("Failed to apply strategy params:", e);
    } finally {
      setIsApplying(false);
    }
  };

  const handleReset = async () => {
    setIsApplying(true);
    try {
      const result = await postEngine<StrategyParams>("/strategy/params/reset", {});
      mutateParams(result);
      setAdjustments({});
      setShowAdjustment(false);
    } catch (e) {
      console.error("Failed to reset strategy params:", e);
    } finally {
      setIsApplying(false);
    }
  };

  if (!params) {
    return (
      <div className="rounded-xl border border-border bg-card p-4">
        <p className="text-xs text-muted-foreground">Loading strategy parameters...</p>
      </div>
    );
  }

  const current = params.current;
  const recommended = params.optimizer_recommended;

  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between p-4 hover:bg-accent/5 transition-colors"
      >
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Strategy Parameters
        </p>
        {isExpanded ? (
          <ChevronUp className="h-4 w-4 text-muted-foreground" />
        ) : (
          <ChevronDown className="h-4 w-4 text-muted-foreground" />
        )}
      </button>

      {isExpanded && (
        <div className="border-t border-border p-4 space-y-4">
          {/* Display Section */}
          <div className="space-y-3 pb-4 border-b border-border">
            <div className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-3">
              Current Values
            </div>

            {/* STC Oversold */}
            <div className="grid grid-cols-3 gap-2 items-center text-xs">
              <span className="text-muted-foreground">STC Oversold</span>
              <div className="bg-muted/50 rounded px-2 py-1 font-mono font-bold text-accent">
                {current.stc_oversold}
              </div>
              <span className="text-[9px] text-muted-foreground text-right">
                rec: {recommended.stc_oversold}
              </span>
            </div>

            {/* STC Overbought */}
            <div className="grid grid-cols-3 gap-2 items-center text-xs">
              <span className="text-muted-foreground">STC Overbought</span>
              <div className="bg-muted/50 rounded px-2 py-1 font-mono font-bold text-accent">
                {current.stc_overbought}
              </div>
              <span className="text-[9px] text-muted-foreground text-right">
                rec: {recommended.stc_overbought}
              </span>
            </div>

            {/* ATR Stop Multiplier */}
            <div className="grid grid-cols-3 gap-2 items-center text-xs">
              <span className="text-muted-foreground">ATR Stop</span>
              <div className="bg-muted/50 rounded px-2 py-1 font-mono font-bold text-accent">
                {current.atr_stop_multiplier.toFixed(2)}x
              </div>
              <span className="text-[9px] text-muted-foreground text-right">
                rec: {recommended.atr_stop_multiplier.toFixed(2)}x
              </span>
            </div>

            {/* ATR Target 1 Multiplier */}
            <div className="grid grid-cols-3 gap-2 items-center text-xs">
              <span className="text-muted-foreground">ATR Target 1</span>
              <div className="bg-muted/50 rounded px-2 py-1 font-mono font-bold text-accent">
                {current.atr_target1_multiplier.toFixed(2)}x
              </div>
              <span className="text-[9px] text-muted-foreground text-right">
                rec: {recommended.atr_target1_multiplier.toFixed(2)}x
              </span>
            </div>

            {/* Regime Filter */}
            <div className="grid grid-cols-3 gap-2 items-center text-xs">
              <span className="text-muted-foreground">Regime Filter</span>
              <div className={`rounded px-2 py-1 font-mono font-bold ${
                current.regime_filter_enabled ? "bg-bull/10 text-bull" : "bg-bear/10 text-bear"
              }`}>
                {current.regime_filter_enabled ? "ON" : "OFF"}
              </div>
              <span className="text-[9px] text-muted-foreground text-right">
                rec: {recommended.regime_filter_enabled ? "ON" : "OFF"}
              </span>
            </div>
          </div>

          {/* Adjustment Section */}
          {showAdjustment && (
            <div className="space-y-3 pb-4 border-b border-border">
              <div className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-3">
                New Values
              </div>

              {/* STC Oversold Adjustment */}
              <div className="space-y-1.5">
                <label className="text-[9px] font-semibold text-muted-foreground">
                  STC Oversold (5-30)
                </label>
                <div className="flex items-center gap-2">
                  <input
                    type="range"
                    min="5"
                    max="30"
                    step="1"
                    value={adjustments.stc_oversold ?? current.stc_oversold}
                    onChange={(e) => handleAdjustment("stc_oversold", parseInt(e.target.value))}
                    className="flex-1 h-1.5 bg-border rounded-full appearance-none cursor-pointer"
                  />
                  <span className="w-8 text-right text-xs font-mono font-bold text-accent">
                    {adjustments.stc_oversold ?? current.stc_oversold}
                  </span>
                </div>
              </div>

              {/* STC Overbought Adjustment */}
              <div className="space-y-1.5">
                <label className="text-[9px] font-semibold text-muted-foreground">
                  STC Overbought (70-95)
                </label>
                <div className="flex items-center gap-2">
                  <input
                    type="range"
                    min="70"
                    max="95"
                    step="1"
                    value={adjustments.stc_overbought ?? current.stc_overbought}
                    onChange={(e) => handleAdjustment("stc_overbought", parseInt(e.target.value))}
                    className="flex-1 h-1.5 bg-border rounded-full appearance-none cursor-pointer"
                  />
                  <span className="w-8 text-right text-xs font-mono font-bold text-accent">
                    {adjustments.stc_overbought ?? current.stc_overbought}
                  </span>
                </div>
              </div>

              {/* ATR Stop Adjustment */}
              <div className="space-y-1.5">
                <label className="text-[9px] font-semibold text-muted-foreground">
                  ATR Stop (0.30-1.50)
                </label>
                <div className="flex items-center gap-2">
                  <input
                    type="range"
                    min="0.30"
                    max="1.50"
                    step="0.05"
                    value={adjustments.atr_stop_multiplier ?? current.atr_stop_multiplier}
                    onChange={(e) => handleAdjustment("atr_stop_multiplier", parseFloat(e.target.value))}
                    className="flex-1 h-1.5 bg-border rounded-full appearance-none cursor-pointer"
                  />
                  <span className="w-10 text-right text-xs font-mono font-bold text-accent">
                    {(adjustments.atr_stop_multiplier ?? current.atr_stop_multiplier).toFixed(2)}x
                  </span>
                </div>
              </div>

              {/* ATR Target 1 Adjustment */}
              <div className="space-y-1.5">
                <label className="text-[9px] font-semibold text-muted-foreground">
                  ATR Target 1 (0.50-3.00)
                </label>
                <div className="flex items-center gap-2">
                  <input
                    type="range"
                    min="0.50"
                    max="3.00"
                    step="0.10"
                    value={adjustments.atr_target1_multiplier ?? current.atr_target1_multiplier}
                    onChange={(e) => handleAdjustment("atr_target1_multiplier", parseFloat(e.target.value))}
                    className="flex-1 h-1.5 bg-border rounded-full appearance-none cursor-pointer"
                  />
                  <span className="w-10 text-right text-xs font-mono font-bold text-accent">
                    {(adjustments.atr_target1_multiplier ?? current.atr_target1_multiplier).toFixed(2)}x
                  </span>
                </div>
              </div>

              {/* Regime Filter Toggle */}
              <div className="space-y-1.5">
                <label className="text-[9px] font-semibold text-muted-foreground">
                  Regime Filter
                </label>
                <button
                  onClick={() => handleAdjustment("regime_filter_enabled",
                    !(adjustments.regime_filter_enabled ?? current.regime_filter_enabled)
                  )}
                  className={`w-full rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
                    (adjustments.regime_filter_enabled ?? current.regime_filter_enabled)
                      ? "bg-bull/20 text-bull border border-bull/30"
                      : "bg-bear/20 text-bear border border-bear/30"
                  }`}
                >
                  {(adjustments.regime_filter_enabled ?? current.regime_filter_enabled) ? "ON" : "OFF"}
                </button>
              </div>
            </div>
          )}

          {/* Confirmation Dialog */}
          {confirmDialog && (
            <div className="p-3 rounded-lg bg-warn/10 border border-warn/30 space-y-3">
              <div className="flex gap-2">
                <AlertCircle className="h-4 w-4 text-warn flex-shrink-0 mt-0.5" />
                <div className="text-xs text-warn space-y-1">
                  <p className="font-semibold">This will change live strategy parameters.</p>
                  <p>Are you sure? This affects all future signals.</p>
                </div>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={handleApply}
                  disabled={isApplying}
                  className="flex-1 bg-warn/20 hover:bg-warn/30 text-warn font-semibold text-xs py-1.5 rounded transition-colors disabled:opacity-50"
                >
                  {isApplying ? "Applying..." : "Confirm"}
                </button>
                <button
                  onClick={() => setConfirmDialog(false)}
                  disabled={isApplying}
                  className="flex-1 bg-muted/50 hover:bg-muted text-muted-foreground font-semibold text-xs py-1.5 rounded transition-colors disabled:opacity-50"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {/* Action Buttons */}
          <div className="flex gap-2 pt-2">
            {!showAdjustment ? (
              <>
                <button
                  onClick={() => setShowAdjustment(true)}
                  className="flex-1 bg-accent/20 hover:bg-accent/30 text-accent font-semibold text-xs py-1.5 rounded transition-colors"
                >
                  Adjust Parameters
                </button>
                <button
                  onClick={handleReset}
                  disabled={isApplying}
                  className="flex-1 bg-muted/50 hover:bg-muted text-muted-foreground font-semibold text-xs py-1.5 rounded transition-colors disabled:opacity-50"
                >
                  {isApplying ? "Resetting..." : "Reset to Defaults"}
                </button>
              </>
            ) : (
              <>
                <button
                  onClick={() => setConfirmDialog(true)}
                  disabled={isApplying || Object.keys(adjustments).length === 0}
                  className="flex-1 bg-accent/20 hover:bg-accent/30 text-accent font-semibold text-xs py-1.5 rounded transition-colors disabled:opacity-50"
                >
                  {isApplying ? <RefreshCw className="h-3 w-3 animate-spin mx-auto" /> : "Apply"}
                </button>
                <button
                  onClick={() => {
                    setShowAdjustment(false);
                    setAdjustments({});
                    setConfirmDialog(false);
                  }}
                  disabled={isApplying}
                  className="flex-1 bg-muted/50 hover:bg-muted text-muted-foreground font-semibold text-xs py-1.5 rounded transition-colors disabled:opacity-50"
                >
                  Cancel
                </button>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
