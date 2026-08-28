"use client";

import React, { useState } from "react";
import { DollarSign } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { fetchEngine } from "@/lib/api";
import { ALL_TRACKED_SYMBOLS, type TrackedSymbol } from "@/lib/approvedSymbols";

// ── Types ──────────────────────────────────────────────────────────────────

type Symbol = TrackedSymbol;

// Mirrors the actual fields returned by GET /position-sizing/calculate
// (engine/routers/settings_router.py:calculate_position_size_alias) — that
// handler currently ignores all query params and always sizes MES; the form
// inputs below reflect what a caller COULD request, not what the response
// reflects, until the backend accepts them.
interface PositionSizingResponse {
  symbol: string;
  account_value: number;
  contracts: number;
  risk_per_trade: number;
  stop_distance: number;
  dollar_risk_per_contract: number;
  reasoning: string;
}

// Active MES first, then halted symbols shown for informational sizing. This is
// a purely informational what-if calculator (GET /position-sizing/calculate
// doesn't execute trades or touch broker/execution paths), so keeping the
// halted symbols selectable is fine.
const SYMBOLS: Symbol[] = [...ALL_TRACKED_SYMBOLS];

const MULTIPLIER_LABELS: Record<Symbol, string> = {
  MES: "$5/pt",
  MGC: "$10/pt",
  MNQ: "$2/pt",
  MCL: "$100/pt",
};

// ── Component ──────────────────────────────────────────────────────────────

export function PositionSizingCalculator() {
  const [symbol, setSymbol] = useState<Symbol>("MES");
  const [accountValue, setAccountValue] = useState<string>("10000");
  const [atr, setAtr] = useState<string>("4.0");
  const [riskPct, setRiskPct] = useState<string>("1");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<PositionSizingResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleCalculate(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setResult(null);
    setError(null);

    const params = new URLSearchParams({
      symbol,
      account_value: accountValue,
      atr,
      risk_pct: String(parseFloat(riskPct) / 100),
    });

    try {
      const data = await fetchEngine<PositionSizingResponse>(
        `/position-sizing/calculate?${params.toString()}`
      );
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Calculation failed");
    } finally {
      setLoading(false);
    }
  }

  const inputCls =
    "w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-accent";
  const selectCls =
    "w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-accent";

  return (
    <Card className="border-accent/20">
      <CardContent className="pt-5 pb-5">
        <div className="flex items-center gap-2 mb-4">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-accent/10">
            <DollarSign className="h-4 w-4 text-accent" />
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-accent">
              Position Sizing Calculator
            </p>
            <p className="text-[10px] text-muted-foreground">
              Fixed-fractional 1%-risk formula — GET /position-sizing/calculate
            </p>
          </div>
        </div>

        <form onSubmit={handleCalculate} className="space-y-3">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="space-y-1">
              <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Symbol
              </label>
              <select
                className={selectCls}
                value={symbol}
                onChange={(e) => setSymbol(e.target.value as Symbol)}
              >
                {SYMBOLS.map((s) => (
                  <option key={s} value={s}>
                    {s} — {MULTIPLIER_LABELS[s]}
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-1">
              <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Account Value ($)
              </label>
              <input
                type="number"
                className={inputCls}
                min={1000}
                step={500}
                value={accountValue}
                onChange={(e) => setAccountValue(e.target.value)}
              />
            </div>

            <div className="space-y-1">
              <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                ATR (pts)
              </label>
              <input
                type="number"
                className={inputCls}
                min={0.01}
                step={0.25}
                value={atr}
                onChange={(e) => setAtr(e.target.value)}
              />
            </div>

            <div className="space-y-1">
              <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Risk % (default 1)
              </label>
              <input
                type="number"
                className={inputCls}
                min={0.1}
                max={10}
                step={0.1}
                value={riskPct}
                onChange={(e) => setRiskPct(e.target.value)}
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="flex items-center gap-2 rounded-md bg-accent px-4 py-2 text-sm font-semibold text-accent-foreground hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? (
              <span className="h-3.5 w-3.5 rounded-full border-2 border-accent-foreground border-t-transparent animate-spin" />
            ) : (
              <DollarSign className="h-3.5 w-3.5" />
            )}
            {loading ? "Calculating..." : "Calculate"}
          </button>
        </form>

        {error && (
          <div className="mt-4 rounded-lg border border-bear/20 bg-bear/5 px-4 py-3">
            <p className="text-xs font-semibold text-bear uppercase tracking-wider mb-1">
              Error
            </p>
            <p className="text-xs text-foreground">{error}</p>
          </div>
        )}

        {result && (
          <div className="mt-4 rounded-lg border border-bull/20 bg-bull/5 px-4 py-3 space-y-3">
            <p className="text-xs font-semibold text-bull uppercase tracking-wider">
              Sizing Result — {result.symbol}
            </p>

            <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-2">
              <div>
                <p className="text-[10px] text-muted-foreground uppercase tracking-wider">
                  Account Value
                </p>
                <p className="text-sm font-semibold text-foreground font-mono">
                  ${result.account_value.toFixed(2)}
                </p>
              </div>
              <div>
                <p className="text-[10px] text-muted-foreground uppercase tracking-wider">
                  Risk / Trade
                </p>
                <p className="text-sm font-semibold text-foreground font-mono">
                  ${result.risk_per_trade.toFixed(2)}
                </p>
              </div>
              <div>
                <p className="text-[10px] text-muted-foreground uppercase tracking-wider">
                  Stop Distance
                </p>
                <p className="text-sm font-semibold text-foreground font-mono">
                  {result.stop_distance.toFixed(4)} pts
                </p>
              </div>
              <div>
                <p className="text-[10px] text-muted-foreground uppercase tracking-wider">
                  Risk / Contract
                </p>
                <p className="text-sm font-semibold text-foreground font-mono">
                  ${result.dollar_risk_per_contract.toFixed(2)}
                </p>
              </div>
              <div>
                <p className="text-[10px] text-muted-foreground uppercase tracking-wider">
                  Calculated Contracts
                </p>
                <p className="text-sm font-bold text-bull font-mono">
                  {result.contracts}
                </p>
              </div>
            </div>

            <div className="pt-1 border-t border-bull/10">
              <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-0.5">
                Reasoning
              </p>
              <p className="text-xs text-foreground font-mono break-all">
                {result.reasoning}
              </p>
            </div>

            <p className="text-[10px] text-muted-foreground italic">
              Note: the engine endpoint currently always sizes MES with server-default
              inputs — the symbol/account/ATR/risk% fields above are not yet honored server-side.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
