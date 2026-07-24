"use client";

import React from "react";
import useSWR from "swr";
import { Activity, AlertCircle, TrendingUp } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";
import type {
  ApprovedPaperGatesResponse,
  ApprovedInstrumentGateRow,
} from "@/lib/api";
import { DEFAULT_BRIEFING_SYMBOLS, HALTED_SYMBOLS, ALL_TRACKED_SYMBOLS } from "@/lib/approvedSymbols";
import { buildInstrumentRow, type InstrumentRow } from "@/lib/instrumentValidationRows";

function fetcher<T>(path: string): Promise<T> {
  return fetchEngine<T>(path);
}

function InstrumentValidationScorecard() {
  const { data, error, isLoading } = useSWR<ApprovedPaperGatesResponse>(
    "/paper/validation/approved-paper-gates",
    fetcher,
    {
      refreshInterval: 30000,
      revalidateOnFocus: false,
    }
  );

  // Build instrument rows from approved gates data — one row per tracked
  // symbol (active pair first, then halted pair), via buildInstrumentRow so
  // MES/MGC always read APPROVED and MCL/MNQ always read HALTED regardless
  // of what the live endpoint returns.
  const rows: InstrumentRow[] = React.useMemo(() => {
    const instrumentMap = new Map<string, ApprovedInstrumentGateRow>();
    data?.instruments?.forEach((inst) => {
      instrumentMap.set(inst.symbol, inst);
    });
    return ALL_TRACKED_SYMBOLS.map((symbol) => buildInstrumentRow(symbol, instrumentMap));
  }, [data]);

  return (
    <Card>
      <CardContent className="pt-5 pb-5">
        <div className="flex items-center gap-2 mb-4">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-info/20">
            <Activity className="h-4 w-4 text-info" />
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-info">
              Instrument Validation Scorecard
            </p>
            <p className="text-[10px] text-muted-foreground">
              Walk-forward efficiency and approval gates for active instruments
            </p>
          </div>
          {error && (
            <div className="ml-auto flex items-center gap-1 text-[10px] text-warn">
              <AlertCircle className="h-3 w-3" />
              <span>API unavailable</span>
            </div>
          )}
        </div>

        {isLoading && (
          <p className="text-xs text-muted-foreground py-4 text-center">
            Loading instrument gates...
          </p>
        )}

        {!isLoading && (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border">
                  <th className="pb-2 pr-4 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                    Symbol
                  </th>
                  <th className="pb-2 pr-4 text-center font-semibold text-muted-foreground uppercase tracking-wider">
                    TF
                  </th>
                  <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                    WFE
                  </th>
                  <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                    PF
                  </th>
                  <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                    Sharpe
                  </th>
                  <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                    WR
                  </th>
                  <th className="pb-2 text-center font-semibold text-muted-foreground uppercase tracking-wider">
                    Status
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/50">
                {rows.map((row) => (
                  <tr
                    key={row.symbol}
                    className={`hover:bg-muted/20 transition-colors ${
                      row.badgeVariant === "warn"
                        ? "bg-muted/20"
                        : ""
                    }`}
                  >
                    <td className="py-2.5 pr-4 font-bold text-foreground">
                      {row.symbol}
                    </td>
                    <td className="py-2.5 pr-4 text-center font-mono text-muted-foreground">
                      {row.timeframe}
                    </td>
                    <td className="py-2.5 pr-4 text-right font-mono tabular-nums text-foreground">
                      {typeof row.wfe === "number"
                        ? row.wfe.toFixed(2)
                        : row.wfe}
                    </td>
                    <td className="py-2.5 pr-4 text-right font-mono tabular-nums text-muted-foreground">
                      {row.pf !== null
                        ? row.pf.toFixed(2)
                        : "—"}
                    </td>
                    <td className="py-2.5 pr-4 text-right font-mono tabular-nums text-muted-foreground">
                      {row.sharpe !== null
                        ? row.sharpe.toFixed(2)
                        : "—"}
                    </td>
                    <td className="py-2.5 pr-4 text-right font-mono tabular-nums text-muted-foreground">
                      {row.wr !== null
                        ? `${(row.wr * 100).toFixed(0)}%`
                        : "—"}
                    </td>
                    <td className="py-2.5 text-center">
                      <Badge variant={row.badgeVariant}>
                        {row.status}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="mt-3 pt-3 border-t border-border/30 text-[10px] text-muted-foreground space-y-1">
          <p className="flex items-start gap-2">
            <TrendingUp className="h-3 w-3 mt-0.5 flex-shrink-0" />
            <span>
              <strong>WFE ≥ 0.40</strong> required for APPROVED status.{" "}
              {DEFAULT_BRIEFING_SYMBOLS.join(" and ")} are approved and trading.{" "}
              {HALTED_SYMBOLS.join(" and ")} are HALTED (routing-blocked, DO_NOT_TRADE).
            </span>
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

export { InstrumentValidationScorecard };