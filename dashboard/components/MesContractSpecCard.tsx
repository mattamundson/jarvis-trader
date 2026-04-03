"use client";

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export function MesContractSpecCard() {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>MES Contract Specs</CardTitle>
          <Badge variant="info">Micro E-mini S&P 500</Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

          {/* Section 1: Contract Details */}
          <div className="space-y-2">
            <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest mb-3">
              Contract Details
            </p>
            <div className="space-y-1.5">
              {[
                ["Symbol", "/MES"],
                ["Exchange", "CME Group"],
                ["Tick Size", "0.25 points ($1.25 value)"],
                ["Contract Value", "$5 × S&P 500 Index"],
                ["Margin (Intraday)", "~$1,320 (typical)"],
                ["Margin (Overnight)", "~$2,640 (typical)"],
                ["Trading Hours", "Sun 5PM – Fri 4PM CT (nearly 24hr)"],
                ["RTH", "8:30AM – 3:15PM CT"],
                ["Daily Settlement", "3:00PM CT"],
                ["Contract Months", "Mar, Jun, Sep, Dec (H, M, U, Z)"],
              ].map(([label, value]) => (
                <div key={label} className="flex justify-between items-baseline gap-4">
                  <span className="text-[11px] text-muted-foreground shrink-0">{label}</span>
                  <span className="text-[11px] font-mono text-foreground text-right">{value}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Section 2: Strategy Context */}
          <div className="space-y-2">
            <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest mb-3">
              Strategy Context
            </p>
            <div className="rounded-lg border border-info/20 bg-info/5 p-4 space-y-1.5">
              {[
                ["Instrument", "MES (1 contract = 1/10 ES)"],
                ["Risk per tick", "$1.25"],
                ["Typical stop", "4–8 ticks ($5–$10)"],
                ["ATR-based stop", "0.70× daily ATR"],
                ["Target", "1.50× ATR"],
                ["Max contracts", "per config (default: 2)"],
              ].map(([label, value]) => (
                <div key={label} className="flex justify-between items-baseline gap-4">
                  <span className="text-[11px] text-muted-foreground shrink-0">{label}</span>
                  <span className="text-[11px] font-mono text-foreground text-right">{value}</span>
                </div>
              ))}
            </div>
          </div>

        </div>
      </CardContent>
    </Card>
  );
}
