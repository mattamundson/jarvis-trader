"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/** Placeholder: validation page imports this; MES revalidation workflow UI TBD. */
export function MESRevalidationTracker() {
  return (
    <Card className="border-dashed border-zinc-700 bg-zinc-950/40">
      <CardHeader className="py-3">
        <CardTitle className="text-sm font-medium text-zinc-300">MES revalidation</CardTitle>
      </CardHeader>
      <CardContent className="pb-3 text-xs text-zinc-500">
        Scaffold — DO NOT TRADE MES until Tier 3 sign-off.
      </CardContent>
    </Card>
  );
}
