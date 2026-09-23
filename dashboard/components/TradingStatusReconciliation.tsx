"use client";

// Split-brain trading-status reconciliation panel (Plan Phase 8 row 2).
//
// WHY: three independent authorities decide whether a symbol actually
// trades right now -- backtest/paper_config.py PAPER_CONFIGS[symbol].enabled,
// backtest/signals.py DO_NOT_TRADE_SYMBOLS (the blocklist), and the latest
// gate-v2 verdict on the strategy ledger. They have disagreed before (the
// exact defect class engine/tests/test_paper_config_donottrade_sync.py
// guards against at the config level, and MES gate-v2 bypass PR #564 showed
// the runtime cost of a layer being skipped). The engine's
// GET /trading-status endpoint (engine/routers/trading_status_router.py ->
// services/trading_status.py, Phase 1c) already reconciles all three into
// one per-symbol row and flags any disagreement -- this component is a
// thin, honest render of that reconciliation, not a second implementation
// of the split-brain logic. Mounted on both /trading-eligibility and
// /mission-control so there is exactly one "what's actually trading" answer
// visible from either entry point.
import useSWR from "swr";
import { AlertTriangle, RefreshCw, WifiOff } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";

const ENDPOINT = "/trading-status";
const REFRESH_MS = 30_000;

// Mirrors engine services/trading_status.py SymbolStatus.to_dict().
interface TradingStatusSymbol {
  symbol: string;
  enabled: boolean;
  authorized: boolean;
  verdict: string | null;
  verdict_family: string | null;
  verdict_created_at: string | null;
  verdict_age_days: number | null;
  oos_trades: number | null;
  tradeable: boolean;
  config_agrees: boolean;
  disagreements: string[];
}

// Mirrors trading_status_router.get_trading_status()'s summarize() output.
interface TradingStatusSummary {
  total: number;
  tradeable: number;
  enabled: number;
  disagreements: number;
}

interface TradingStatusResponse {
  summary: TradingStatusSummary;
  symbols: TradingStatusSymbol[];
}

function fetcher(): Promise<TradingStatusResponse> {
  return fetchEngine<TradingStatusResponse>(ENDPOINT);
}

function SourceBadge({
  label,
  ok,
  okLabel,
  badLabel,
}: {
  label: string;
  ok: boolean;
  okLabel: string;
  badLabel: string;
}) {
  return (
    <Badge variant={ok ? "bull" : "neutral"} className="font-mono text-[10px]">
      {label}: {ok ? okLabel : badLabel}
    </Badge>
  );
}

function SymbolRow({ row }: { row: TradingStatusSymbol }) {
  const hasSplitBrain = !row.config_agrees;

  return (
    <div
      className={`rounded-lg border p-3 space-y-2 ${
        hasSplitBrain ? "border-warn/40 bg-warn/5" : "border-border bg-muted/20"
      }`}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-mono text-sm font-bold text-foreground">{row.symbol}</span>
        <Badge variant={row.tradeable ? "bull" : "neutral"}>
          {row.tradeable ? "TRADING NOW" : "NOT TRADING"}
        </Badge>
        {hasSplitBrain && (
          <Badge variant="warn">
            <span className="inline-flex items-center gap-1">
              <AlertTriangle className="h-3 w-3" />
              SPLIT-BRAIN
            </span>
          </Badge>
        )}
        <span className="ml-auto flex flex-wrap gap-1.5">
          <SourceBadge label="paper_config" ok={row.enabled} okLabel="enabled" badLabel="disabled" />
          <Badge variant={row.authorized ? "bull" : "bear"} className="font-mono text-[10px]">
            do-not-trade: {row.authorized ? "clear" : "BLOCKED"}
          </Badge>
          <Badge
            variant={row.verdict === "PASS" ? "bull" : row.verdict ? "bear" : "neutral"}
            className="font-mono text-[10px]"
          >
            gate-v2: {row.verdict ?? "no verdict"}
          </Badge>
        </span>
      </div>

      {hasSplitBrain && (
        <ul className="space-y-1 border-t border-warn/20 pt-2">
          {row.disagreements.map((d) => (
            <li key={d} className="flex items-start gap-1.5 text-[11px] text-warn">
              <AlertTriangle className="h-3 w-3 mt-0.5 shrink-0" />
              <span>{d}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function TradingStatusReconciliation() {
  const { data, error, isLoading, mutate } = useSWR<TradingStatusResponse>(
    ENDPOINT,
    fetcher,
    { refreshInterval: REFRESH_MS, revalidateOnFocus: false }
  );

  const rows = data?.symbols ?? [];
  const disagreementCount = data?.summary.disagreements ?? 0;

  return (
    <Card className={disagreementCount > 0 ? "border-warn/40" : undefined}>
      <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0">
        <CardTitle>Trading Status Reconciliation</CardTitle>
        <div className="flex items-center gap-2">
          {data && (
            <Badge variant={disagreementCount > 0 ? "warn" : "bull"}>
              {disagreementCount > 0
                ? `${disagreementCount} split-brain`
                : "all sources agree"}
            </Badge>
          )}
          <button
            onClick={() => mutate()}
            className="p-1.5 hover:bg-secondary rounded-full transition-colors"
            title="Refresh now"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-xs text-muted-foreground">
          Live from <code className="font-mono text-[11px]">GET /trading-status</code> — reconciles{" "}
          <code className="font-mono text-[11px]">PAPER_CONFIGS.enabled</code> ×{" "}
          <code className="font-mono text-[11px]">DO_NOT_TRADE_SYMBOLS</code> × the latest gate-v2
          verdict into one per-symbol truth. Any disagreement between the three sources is flagged
          below, never silently resolved.
        </p>

        {error && (
          <div className="flex items-center gap-2 p-3 bg-bear/10 border border-bear/20 text-bear rounded-lg text-xs">
            <WifiOff className="h-4 w-4 shrink-0" />
            {ENDPOINT} unreachable — engine may be down or restarting. Not showing stale data.
          </div>
        )}

        {isLoading && !data && !error && (
          <div className="flex items-center justify-center py-8 text-xs text-muted-foreground">
            <RefreshCw className="w-4 h-4 animate-spin mr-2" /> Loading live trading status…
          </div>
        )}

        {data && rows.length === 0 && !error && (
          <p className="text-xs text-muted-foreground">No symbols tracked by this endpoint.</p>
        )}

        {rows.length > 0 && (
          <div className="grid gap-2 sm:grid-cols-2">
            {rows.map((row) => (
              <SymbolRow key={row.symbol} row={row} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
