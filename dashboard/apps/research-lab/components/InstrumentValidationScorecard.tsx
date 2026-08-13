"use client";

import React from "react";
import useSWR from "swr";
import { Activity, AlertCircle, TrendingUp } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";
import type { ApprovedPaperGatesResponse } from "@/lib/api";
import { buildInstrumentValidationRows } from "@/lib/instrumentValidation";

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

  // Rows are derived entirely from live approved-paper-gates data (whatever
  // APPROVED_PAPER_SYMBOLS currently is) -- no hardcoded symbol list here.
  const rows = React.useMemo(() => buildInstrumentValidationRows(data), [data]);

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
              Approval gates for currently approved paper instruments
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

        {!isLoading && rows.length === 0 && (
          <p className="text-xs text-muted-foreground py-4 text-center">
            No approved paper instruments reported by the engine.
          </p>
        )}

        {!isLoading && rows.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border">
                  <th className="pb-2 pr-4 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                    Symbol
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
                  <tr key={row.symbol} className="hover:bg-muted/20 transition-colors">
                    <td className="py-2.5 pr-4 font-bold text-foreground">
                      {row.symbol}
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
                        ? `${row.wr.toFixed(0)}%`
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
              {data?.note ??
                "Gates apply only to currently approved paper instruments (APPROVED_PAPER_SYMBOLS). Halted instruments are never listed here."}
            </span>
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

export { InstrumentValidationScorecard };
