"use client";

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export function SessionSummaryWidget() {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Session Summary
          <Badge variant="neutral">Not wired</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {/* Placeholder, not a live panel — must not read as data about to populate. */}
        <p className="text-muted-foreground">
          Placeholder — not yet wired to a data source. This panel shows no live
          session data.
        </p>
      </CardContent>
    </Card>
  );
}
