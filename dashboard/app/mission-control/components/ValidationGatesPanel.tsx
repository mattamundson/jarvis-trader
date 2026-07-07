"use client";

import useSWR from "swr";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { LedgerEntry, LedgerResponse } from "@/lib/api";
import { fetcher, LoadingRows, UnreachableNote } from "./shared";

// GET /validate/proactive-suite?symbol=X —
// engine/routers/proactive_validation_router.py ProactiveValidationReport
interface ValidationCheckLive {
  name: string;
  status: "pass" | "warn" | "fail" | "insufficient_data";
  value: string;
  threshold: string;
  message: string;
}

interface ProactiveReportLive {
  symbol: string;
  generated_at: string;
  overall: "READY" | "CAUTION" | "NOT_READY" | "INSUFFICIENT_DATA";
  checks: ValidationCheckLive[];
  summary: string;
  next_milestone: string;
}

const SYMBOLS = ["MCL", "MNQ"] as const;

function overallBadgeVariant(
  overall: ProactiveReportLive["overall"] | undefined
): "bull" | "warn" | "bear" | "neutral" {
  switch (overall) {
    case "READY":
      return "bull";
    case "CAUTION":
      return "warn";
    case "NOT_READY":
      return "bear";
    default:
      return "neutral";
  }
}

function SymbolSuite({ symbol }: { symbol: (typeof SYMBOLS)[number] }) {
  const { data, error, isLoading } = useSWR<ProactiveReportLive>(
    `/validate/proactive-suite?symbol=${symbol}`,
    fetcher,
    { refreshInterval: 60_000 } // heavier endpoint (8 live checks) — poll slower
  );

  if (error) return <UnreachableNote endpoint={`/validate/proactive-suite?symbol=${symbol}`} />;
  if (isLoading) return <LoadingRows rows={2} />;

  const notPassing = (data?.checks ?? []).filter(
    (c) => c.status === "fail" || c.status === "warn"
  );

  return (
    <div className="rounded-lg border border-border bg-muted/20 p-3 space-y-2">
      <div className="flex items-center gap-2">
        <span className="font-mono text-xs font-bold text-foreground">{symbol}</span>
        <Badge variant={overallBadgeVariant(data?.overall)}>{data?.overall ?? "UNKNOWN"}</Badge>
      </div>
      {data?.summary && <p className="text-[11px] text-muted-foreground">{data.summary}</p>}
      {notPassing.length > 0 && (
        <ul className="space-y-1">
          {notPassing.map((c) => (
            <li key={c.name} className="flex items-start gap-1.5 text-[11px]">
              <Badge variant={c.status === "fail" ? "bear" : "warn"} className="shrink-0">
                {c.status.toUpperCase()}
              </Badge>
              <span className="text-muted-foreground">
                <span className="text-foreground font-medium">{c.name}</span> — {c.value}{" "}
                <span className="font-mono">({c.threshold})</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function latestVerdictPerSymbol(entries: LedgerEntry[]): LedgerEntry[] {
  const bySymbol = new Map<string, LedgerEntry>();
  for (const e of entries) {
    const sym = e.symbol?.toUpperCase();
    if (!sym) continue;
    const ts = e.created_at ? new Date(e.created_at).getTime() : 0;
    const prev = bySymbol.get(sym);
    const prevTs = prev?.created_at ? new Date(prev.created_at).getTime() : -1;
    if (!prev || ts > prevTs) bySymbol.set(sym, e);
  }
  return Array.from(bySymbol.values()).sort((a, b) =>
    (a.symbol ?? "").localeCompare(b.symbol ?? "")
  );
}

export function ValidationGatesPanel() {
  const {
    data: ledger,
    error: ledgerError,
    isLoading: ledgerLoading,
  } = useSWR<LedgerResponse>("/strategy/ledger", fetcher, { refreshInterval: 60_000 });

  const verdicts = latestVerdictPerSymbol(ledger?.entries ?? []);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Validation &amp; Gates</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {SYMBOLS.map((sym) => (
            <SymbolSuite key={sym} symbol={sym} />
          ))}
        </div>

        {/* Gate-v2 verdicts (strategy ledger) */}
        <div className="border-t border-border pt-3 space-y-2">
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
            Gate-v2 verdicts (strategy ledger)
          </p>
          {ledgerError ? (
            <UnreachableNote endpoint="/strategy/ledger" />
          ) : ledgerLoading ? (
            <LoadingRows rows={2} />
          ) : verdicts.length === 0 ? (
            <p className="text-xs text-muted-foreground">No ledger entries.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {verdicts.map((v) => (
                <div
                  key={v.symbol}
                  className="flex items-center gap-1.5 rounded-lg border border-border bg-muted/30 px-2.5 py-1.5"
                >
                  <span className="font-mono text-xs font-semibold text-foreground">{v.symbol}</span>
                  <Badge variant={v.verdict === "PASS" ? "bull" : "bear"}>{v.verdict ?? "?"}</Badge>
                  {v.passed_via && (
                    <span className="text-[10px] text-muted-foreground">via {v.passed_via}</span>
                  )}
                  {v.pf_ci_lower != null && (
                    <span className="font-mono text-[10px] text-muted-foreground">
                      PF↓ {v.pf_ci_lower.toFixed(2)}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
