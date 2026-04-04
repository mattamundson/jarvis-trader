"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/** Placeholder: validation page imports this; replace with chart + live P&L series. */
export function PortfolioPLChart() {
  return (
    <Card className="border-dashed border-zinc-700 bg-zinc-950/40">
      <CardHeader className="py-3">
        <CardTitle className="text-sm font-medium text-zinc-300">P&L chart</CardTitle>
      </CardHeader>
      <CardContent className="pb-3 text-xs text-zinc-500">
        Scaffold — connect paper validation history endpoint.
      </CardContent>
    </Card>
  );
}
