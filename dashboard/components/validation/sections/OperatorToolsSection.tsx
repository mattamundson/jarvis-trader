"use client";

// Validation workspace — "summary" section, operator-tools cluster.
//
// Split out of SummarySection.tsx (task-3 review Finding 2, fix round) so no
// single file absorbs all 11 of the former page's non-drill-down sections.
// Holds trading-phase status plus the tools that don't belong to a specific
// drill-down section: simulate trade, position sizing, go-live roadmap.
// Extracted verbatim from the former app/validation/page.tsx Sections D, E,
// G, J (PRB dashboard-hardening Task 3) — no calculation, label, or
// error-handling behavior changed, only relocated.

import React, { useState } from "react";
import { CheckCircle2, XCircle, Clock, Lock, Play } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { formatCurrency } from "@/lib/utils";
import type { ValidationReport } from "@/lib/api";
import { simulateTrade } from "@/lib/settings-api";
import type { SimulateTradePayload, SimulateTradeResult } from "@/lib/settings-api";
import { PositionSizingCalculator } from "@/components/PositionSizingCalculator";
import { GoLivePlanCard } from "@/components/GoLivePlanCard";
import { fmtBaselineNum, type ScorecardBacktestBaseline } from "@/lib/scorecardBaseline";
import {
  DEFAULT_BRIEFING_SYMBOLS,
  ALL_TRACKED_SYMBOLS,
  PREFERRED_BASELINE_LABEL,
} from "@/lib/approvedSymbols";
import { SectionLabel, THRESHOLDS } from "@/components/validation/shared";

// ── Phase Status Card ─────────────────────────────────────────────────────────

function PhaseStatusCard({
  report,
  baseline,
}: {
  report: ValidationReport | null;
  baseline: ScorecardBacktestBaseline | null;
}) {
  const phase2Status = !report
    ? "loading"
    : report.status === "PASS"
    ? "pass"
    : report.status === "FAIL"
    ? "fail"
    : "in-progress";

  const pfChip = fmtBaselineNum(baseline?.profitFactor ?? null);
  const srChip = fmtBaselineNum(baseline?.sharpeRatio ?? null);
  const retChip = baseline?.totalReturnLabel ?? "—";

  return (
    <Card>
      <CardContent className="pt-5 pb-5">
        <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-4">
          Trading Roadmap
        </p>

        <div className="space-y-3">
          <div className="flex items-start gap-3 rounded-lg border border-bull/20 bg-bull/5 px-4 py-3">
            <CheckCircle2 className="h-5 w-5 text-bull shrink-0 mt-0.5" />
            <div className="min-w-0">
              <p className="text-sm font-semibold text-bull">Phase 1 — Backtest</p>
              <p className="text-xs text-muted-foreground mt-0.5">
                Complete — saved baseline ({PREFERRED_BASELINE_LABEL} preferred); metrics from engine JSON when loaded
              </p>
              <div className="flex flex-wrap gap-2 mt-2">
                <span className="rounded-md bg-bull/10 border border-bull/20 px-2 py-0.5 text-[10px] font-mono text-bull">
                  PF {pfChip}
                </span>
                <span className="rounded-md bg-accent/10 border border-accent/20 px-2 py-0.5 text-[10px] font-mono text-accent">
                  Sharpe {srChip}
                </span>
                <span className="rounded-md bg-muted px-2 py-0.5 text-[10px] font-mono text-muted-foreground">
                  {retChip}
                </span>
              </div>
            </div>
          </div>

          <div
            className={`flex items-start gap-3 rounded-lg border px-4 py-3 ${
              phase2Status === "pass"
                ? "border-bull/20 bg-bull/5"
                : phase2Status === "fail"
                ? "border-bear/20 bg-bear/5"
                : "border-warn/20 bg-warn/5"
            }`}
          >
            {phase2Status === "pass" ? (
              <CheckCircle2 className="h-5 w-5 text-bull shrink-0 mt-0.5" />
            ) : phase2Status === "fail" ? (
              <XCircle className="h-5 w-5 text-bear shrink-0 mt-0.5" />
            ) : (
              <Clock className="h-5 w-5 text-warn shrink-0 mt-0.5" />
            )}
            <div className="min-w-0">
              <p
                className={`text-sm font-semibold ${
                  phase2Status === "pass"
                    ? "text-bull"
                    : phase2Status === "fail"
                    ? "text-bear"
                    : "text-warn"
                }`}
              >
                Phase 2 — Paper Trading
              </p>
              <p className="text-xs text-muted-foreground mt-0.5">
                Ongoing — Forward-test with live market data
              </p>
              <div className="flex flex-wrap gap-2 mt-2">
                <span className="rounded-md bg-muted px-2 py-0.5 text-[10px] font-mono text-muted-foreground">
                  Need PF {`>`} {THRESHOLDS.profitFactor}
                </span>
                <span className="rounded-md bg-muted px-2 py-0.5 text-[10px] font-mono text-muted-foreground">
                  Need Sharpe {`>`} {THRESHOLDS.sharpeRatio}
                </span>
                <span className="rounded-md bg-muted px-2 py-0.5 text-[10px] font-mono text-muted-foreground">
                  Min {THRESHOLDS.minTrades} trades
                </span>
              </div>
            </div>
          </div>

          <div className="flex items-start gap-3 rounded-lg border border-border bg-muted/30 px-4 py-3 opacity-60">
            <Lock className="h-5 w-5 text-muted-foreground shrink-0 mt-0.5" />
            <div className="min-w-0">
              <p className="text-sm font-semibold text-muted-foreground">
                Phase 3 — Live Trading
              </p>
              <p className="text-xs text-muted-foreground mt-0.5">
                TBD, pending Amo decision — Locked until Phase 2 passes
              </p>
              <div className="flex flex-wrap gap-2 mt-2">
                <span className="rounded-md bg-muted px-2 py-0.5 text-[10px] font-mono text-muted-foreground">
                  Requires Phase 2 PASS
                </span>
              </div>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// ── Simulate Trade Panel ──────────────────────────────────────────────────────

// Derived from the shared instrument constants (D2-03-v2, 2026-07-24) so this
// selector's default can't drift back to a halted symbol — was hardcoded
// ["MCL","MNQ","MES"] defaulting to MCL, which is DO_NOT_TRADE. All four
// symbols stay selectable (this panel is a manual-simulation tool, so
// testing a halted symbol's behavior is still a valid use case); only the
// default changes to the actively-traded pair.
const SYMBOLS = ALL_TRACKED_SYMBOLS;
type Symbol = (typeof SYMBOLS)[number];

const ACTIONS = ["LONG", "SHORT"] as const;
type Action = (typeof ACTIONS)[number];

function SimulateTradePanel() {
  const [symbol, setSymbol] = useState<Symbol>(DEFAULT_BRIEFING_SYMBOLS[0]);
  const [action, setAction] = useState<Action>("LONG");
  const [entryPrice, setEntryPrice] = useState<string>("5000");
  const [stopLoss, setStopLoss] = useState<string>("4990");
  const [quantity, setQuantity] = useState<string>("1");
  const [result, setResult] = useState<SimulateTradeResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  // GT-41: submission is disabled below (button `disabled`) because no backend
  // endpoint implements a non-persisting trade simulation -- see simulateTrade()
  // in settings-api.ts for the full explanation. handleSubmit is kept functional
  // (rather than deleted) purely as a defensive fallback: if the button's
  // `disabled` attribute is ever bypassed, simulateTrade() throws a clear
  // "not yet implemented" error that lands in the existing error UI below
  // instead of silently 404ing or touching live portfolio state.
  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setResult(null);
    setError(null);

    const payload: SimulateTradePayload = {
      symbol,
      action,
      entry_price: parseFloat(entryPrice) || 0,
      stop_loss: parseFloat(stopLoss) || 0,
      quantity: Math.min(2, Math.max(1, parseInt(quantity, 10) || 1)),
    };

    try {
      const res = await simulateTrade(payload);
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Simulation failed");
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
            <Play className="h-4 w-4 text-accent" />
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-accent">
              Simulate Trade
            </p>
            <p className="text-[10px] text-muted-foreground">
              Manual paper trade simulation — not yet implemented (GT-41)
            </p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
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
                    {s}
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-1">
              <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Action
              </label>
              <select
                className={selectCls}
                value={action}
                onChange={(e) => setAction(e.target.value as Action)}
              >
                {ACTIONS.map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-1">
              <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Quantity (1-2)
              </label>
              <input
                type="number"
                className={inputCls}
                min={1}
                max={2}
                step={1}
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
              />
            </div>

            <div className="space-y-1">
              <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Entry Price
              </label>
              <input
                type="number"
                className={inputCls}
                step="0.25"
                value={entryPrice}
                onChange={(e) => setEntryPrice(e.target.value)}
              />
            </div>

            <div className="space-y-1">
              <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Stop Loss
              </label>
              <input
                type="number"
                className={inputCls}
                step="0.25"
                value={stopLoss}
                onChange={(e) => setStopLoss(e.target.value)}
              />
            </div>
          </div>

          <button
            type="submit"
            disabled
            title="Disabled (GT-41): the backend endpoint this panel depended on (/test/simulate-trade) was never registered on the engine, and no equivalent non-persisting simulate endpoint exists. Repointing to the real manual-trade route would open an actual paper position instead of a dry-run estimate."
            className="flex items-center gap-2 rounded-md bg-accent px-4 py-2 text-sm font-semibold text-accent-foreground hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <Play className="h-3.5 w-3.5" />
            Simulate Trade (not yet implemented)
          </button>
          <p className="text-[10px] text-muted-foreground">
            Disabled — GT-41: no backend endpoint implements a non-persisting trade
            simulation. See settings-api.ts simulateTrade() for details.
          </p>
        </form>

        {result && (
          <div className="mt-4 rounded-lg border border-bull/20 bg-bull/5 px-4 py-3 space-y-1">
            <p className="text-xs font-semibold text-bull uppercase tracking-wider mb-1">
              Simulation Result
            </p>
            {result.trade_id && (
              <p className="text-xs text-muted-foreground font-mono">
                Trade ID: <span className="text-foreground">{result.trade_id}</span>
              </p>
            )}
            {result.message && (
              <p className="text-xs text-foreground">{result.message}</p>
            )}
            {result.pnl_estimate !== undefined && (
              <p className="text-xs text-muted-foreground font-mono">
                Est. P&L:{" "}
                <span className={result.pnl_estimate >= 0 ? "text-bull" : "text-bear"}>
                  {formatCurrency(result.pnl_estimate)}
                </span>
              </p>
            )}
            {result.risk_amount !== undefined && (
              <p className="text-xs text-muted-foreground font-mono">
                Risk: <span className="text-warn">{formatCurrency(result.risk_amount)}</span>
              </p>
            )}
            <p className="text-xs text-muted-foreground font-mono">
              Status:{" "}
              <span className="text-foreground font-semibold">{result.status}</span>
            </p>
          </div>
        )}

        {error && (
          <div className="mt-4 rounded-lg border border-bear/20 bg-bear/5 px-4 py-3 flex items-start gap-2">
            <XCircle className="h-4 w-4 text-bear shrink-0 mt-0.5" />
            <p className="text-xs text-bear">{error}</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Cluster — top-level composition ───────────────────────────────────────────

export default function OperatorToolsSection({
  report,
  baseline,
}: {
  report: ValidationReport | null;
  baseline: ScorecardBacktestBaseline | null;
}) {
  return (
    <div className="space-y-6">
      {/* Section D: Phase Status */}
      <section>
        <SectionLabel>D — Trading Phase Status</SectionLabel>
        <PhaseStatusCard report={report} baseline={baseline} />
      </section>

      {/* Section E: Simulate Trade */}
      <section>
        <SectionLabel>E — Simulate Trade</SectionLabel>
        <SimulateTradePanel />
      </section>

      {/* Section G: Position Sizing Calculator */}
      <section>
        <SectionLabel>G — Position Sizing Calculator</SectionLabel>
        <PositionSizingCalculator />
      </section>

      {/* Section J: Go-Live Roadmap */}
      <section>
        <SectionLabel>J — Go-Live Roadmap</SectionLabel>
        <GoLivePlanCard />
      </section>
    </div>
  );
}
