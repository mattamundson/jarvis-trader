"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/** Placeholder: command-center imports this; wire to engine when correlation API is stable. */
export function PortfolioCorrelationWidget() {
  return (
    <Card className="border-dashed border-zinc-700 bg-zinc-950/40">
      <CardHeader className="py-3">
        <CardTitle className="text-sm font-medium text-zinc-300">Portfolio correlation</CardTitle>
      </CardHeader>
      <CardContent className="pb-3 text-xs text-zinc-500">
        Scaffold — hook to orchestrator exposure when ready.
      </CardContent>
    </Card>
  );
}
