"use client";

import useSWR from "swr";
import {
  AlertCircle,
  RefreshCw,
  ShieldCheck,
  WifiOff,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchApprovedPaperGates } from "@/lib/api";
import type { ApprovedPaperGatesResponse } from "@/lib/api";
import { eligibilityRows, eligibleCount } from "@/lib/tradingEligibility";
import { InstrumentEligibilityCard } from "@/components/InstrumentEligibilityCard";
import { TradingStatusReconciliation } from "@/components/TradingStatusReconciliation";
import { WidgetErrorBoundary } from "@/components/WidgetErrorBoundary";

// Polled well under the 5-minute dashboard market-data-freshness bar; matches
// the cadence /validation section 1B (PRB-36) uses for this same endpoint.
const REFRESH_MS = 30_000;

function fetcher(): Promise<ApprovedPaperGatesResponse> {
  return fetchApprovedPaperGates();
}

export default function TradingEligibilityPage() {
  const { data, error, isLoading, mutate } = useSWR<ApprovedPaperGatesResponse>(
    "/paper/validation/approved-paper-gates",
    fetcher,
    { refreshInterval: REFRESH_MS, revalidateOnFocus: false }
  );

  const rows = eligibilityRows(data);
  const nEligible = eligibleCount(rows);

  return (
    <div className="flex flex-col gap-6 p-8 max-w-6xl mx-auto">
      <div className="flex items-start justify-between border-b border-border pb-4">
        <div>
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-6 w-6 text-accent" />
            <h1 className="text-2xl font-bold tracking-tight text-foreground">
              Trading Eligibility
            </h1>
          </div>
          <p className="text-sm text-muted-foreground mt-1 max-w-2xl">
            Live from <code className="font-mono text-xs">GET /paper/validation/approved-paper-gates</code>{" "}
            — this is the single source of truth for paper-trading eligibility.
            It cannot go stale the way a hand-maintained doc can: every row
            below is read straight from the engine on each refresh, not from
            a snapshot anyone has to remember to update.
          </p>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          {data && (
            <Badge variant={nEligible > 0 ? "bull" : "neutral"}>
              {nEligible}/{rows.length} eligible
            </Badge>
          )}
          <button
            onClick={() => mutate()}
            className="p-2 hover:bg-secondary rounded-full transition-colors"
            title="Refresh now"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      <WidgetErrorBoundary name="Trading Status Reconciliation">
        <TradingStatusReconciliation />
      </WidgetErrorBoundary>

      {error && (
        <div className="flex items-center gap-2 p-4 bg-bear/10 border border-bear/20 text-bear rounded-lg text-sm">
          <WifiOff className="h-4 w-4 shrink-0" />
          /paper/validation/approved-paper-gates unreachable — engine may be
          down or restarting. Not showing stale data.
        </div>
      )}

      {isLoading && !data && !error && (
        <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
          <RefreshCw className="w-4 h-4 animate-spin mr-2" /> Loading live eligibility gates…
        </div>
      )}

      {data && rows.length === 0 && !error && (
        <div className="p-6 border border-border rounded-xl text-center text-sm text-muted-foreground">
          The engine returned no instruments. Nothing is currently tracked by
          this endpoint.
        </div>
      )}

      {rows.length > 0 && (
        <div className="grid gap-6 md:grid-cols-2">
          {rows.map((row) => (
            <InstrumentEligibilityCard key={row.symbol} row={row} />
          ))}
        </div>
      )}

      {data?.thresholds && (
        <Card>
          <CardContent className="pt-5 pb-5">
            <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-3">
              Gate thresholds (live from engine)
            </p>
            <div className="flex flex-wrap gap-2">
              {Object.entries(data.thresholds).map(([key, val]) => (
                <span
                  key={key}
                  className="rounded-md bg-muted px-2 py-1 text-[11px] font-mono text-muted-foreground"
                >
                  {key.replace(/_/g, " ")}: {String(val)}
                </span>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {data?.note && (
        <div className="flex items-start gap-2 p-3 rounded-lg border border-border bg-muted/30 text-[11px] text-muted-foreground leading-relaxed">
          <AlertCircle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
          <span>
            <strong className="text-foreground">Engine note:</strong> {data.note} A
            symbol that trades through a different path than this endpoint&apos;s
            scope (e.g. it is not currently in the engine&apos;s
            APPROVED_PAPER_SYMBOLS list) will not appear above — that is a gap
            in the endpoint&apos;s coverage, not a false &quot;eligible&quot; claim by
            this page.
          </span>
        </div>
      )}
    </div>
  );
}
