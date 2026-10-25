"use client";

import { useEffect, useState } from "react";
import { TrendingUp, TrendingDown, Activity, Shield } from "lucide-react";
import { fetchEngine } from "@/lib/api";
import { WidgetErrorBoundary } from "@/components/WidgetErrorBoundary";

// ── Types ──────────────────────────────────────────────────────────────────

interface PaperStatusSymbol {
  symbol: string;
  status: string;
  wfe: number;
  wfe_label: string;
  gate: string;
  authorized: boolean;
  verdict: string;
  paper_config?: { enabled: boolean };
}

interface PaperStatusResponse {
  [key: string]: PaperStatusSymbol;
}

interface PnlTruthResponse {
  status: string;
  realized_pnl: number;
  closed_trades: number;
  excluded_trades: number;
  trusted: boolean;
  sources_present: string[];
}

// ── Card ───────────────────────────────────────────────────────────────────

function formatCurrency(n: number): string {
  const sign = n >= 0 ? "+" : "";
  return `${sign}$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function PaperTradeAuditCard() {
  const [mes, setMes] = useState<PaperStatusSymbol | null>(null);
  const [pnl, setPnl] = useState<PnlTruthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const [paperStatus, pnlTruth] = await Promise.all([
          fetchEngine<PaperStatusResponse>("/backtest/paper-status"),
          fetchEngine<PnlTruthResponse>("/pnl/truth"),
        ]);
        if (cancelled) return;
        setMes(paperStatus?.["MES_1h"] ?? null);
        setPnl(pnlTruth);
        setError(null);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load");
      }
    }

    load();
    const interval = setInterval(load, 30_000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  if (error) {
    return (
      <div className="rounded-lg border border-border bg-card p-4">
        <p className="text-sm text-muted-foreground">Trade audit unavailable: {error}</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Activity className="h-4 w-4 text-accent" />
        <h3 className="text-sm font-semibold text-foreground">Paper Trade Audit</h3>
        {pnl?.trusted && (
          <span className="ml-auto rounded bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-medium text-emerald-400">
            TRUSTED
          </span>
        )}
      </div>

      {/* P&L row */}
      {pnl && (
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground">Realized P&amp;L</span>
          <span className={`text-sm font-mono font-bold ${pnl.realized_pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
            {formatCurrency(pnl.realized_pnl)}
          </span>
        </div>
      )}

      {/* Trade counts */}
      {pnl && (
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground">Trades</span>
          <span className="text-xs text-foreground font-mono">
            {pnl.closed_trades} closed
            {pnl.excluded_trades > 0 && (
              <span className="text-muted-foreground"> · {pnl.excluded_trades} excluded</span>
            )}
          </span>
        </div>
      )}

      {/* MES status */}
      {mes && (
        <div className="flex items-center justify-between border-t border-border pt-2">
          <span className="text-xs text-muted-foreground">{mes.symbol}</span>
          <div className="flex items-center gap-2">
            <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
              mes.authorized ? "bg-emerald-500/10 text-emerald-400" : "bg-red-500/10 text-red-400"
            }`}>
              {mes.verdict}
            </span>
            <span className="text-[10px] text-muted-foreground font-mono">
              WFE {mes.wfe.toFixed(3)}
            </span>
          </div>
        </div>
      )}

      {/* Empty state */}
      {!mes && !pnl && (
        <p className="text-xs text-muted-foreground">Loading trade data…</p>
      )}
    </div>
  );
}