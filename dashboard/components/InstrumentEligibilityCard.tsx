"use client";

// Shared live trading-eligibility card. Extracted from
// app/trading-eligibility/page.tsx (PRB-25) so PRB-36's /validation section
// 1B fix could reuse the exact same live-sourced, zero-hardcoded-symbol-table
// rendering instead of reinventing it (both consumers now import this file).
// See lib/tradingEligibility.ts for the pure data transform this renders --
// every field comes straight off GET /paper/validation/approved-paper-gates,
// no per-symbol override table, no fabricated fallback status.

import { CheckCircle2, XCircle } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatGateValue, type EligibilityRow } from "@/lib/tradingEligibility";

export function EligibilityBadge({ row }: { row: EligibilityRow }) {
  return (
    <Badge variant={row.tone}>
      <span className="inline-flex items-center gap-1">
        {row.overallPass ? (
          <CheckCircle2 className="h-3 w-3" />
        ) : (
          <XCircle className="h-3 w-3" />
        )}
        {row.label}
      </span>
    </Badge>
  );
}

export function InstrumentEligibilityCard({ row }: { row: EligibilityRow }) {
  return (
    <Card
      className={row.overallPass ? "border-bull/20 bg-bull/5" : "border-bear/20 bg-bear/5"}
    >
      <CardContent className="pt-5 pb-5">
        <div className="flex items-center gap-2 mb-4">
          <div>
            <p className="font-mono text-lg font-bold text-foreground">{row.symbol}</p>
            <p className="text-[10px] text-muted-foreground">
              {row.tradeCount} closed trade{row.tradeCount !== 1 ? "s" : ""} ·{" "}
              {row.daysWithTrades} distinct trading day{row.daysWithTrades !== 1 ? "s" : ""}
            </p>
          </div>
          <span className="ml-auto">
            <EligibilityBadge row={row} />
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border">
                <th className="pb-2 pr-4 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                  Gate
                </th>
                <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                  Current
                </th>
                <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                  Target
                </th>
                <th className="pb-2 text-center font-semibold text-muted-foreground uppercase tracking-wider">
                  Pass
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/50">
              {row.gates.map((gate) => (
                <tr key={gate.name} className="hover:bg-muted/20 transition-colors">
                  <td className="py-2 pr-4 font-medium text-foreground whitespace-nowrap">
                    {gate.name.replace(/_/g, " ")}
                  </td>
                  <td
                    className={`py-2 pr-4 text-right font-mono tabular-nums font-semibold ${
                      gate.passes ? "text-bull" : "text-bear"
                    }`}
                  >
                    {formatGateValue(gate.current, gate.unit)}
                  </td>
                  <td className="py-2 pr-4 text-right font-mono tabular-nums text-muted-foreground">
                    {formatGateValue(gate.target, gate.unit)}
                  </td>
                  <td className="py-2 text-center">
                    {gate.passes ? (
                      <CheckCircle2 className="h-3.5 w-3.5 text-bull mx-auto" />
                    ) : (
                      <XCircle className="h-3.5 w-3.5 text-bear mx-auto" />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
