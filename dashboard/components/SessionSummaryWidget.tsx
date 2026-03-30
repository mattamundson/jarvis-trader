"use client";

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";

export function SessionSummaryWidget() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Session Summary</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-muted-foreground">Session summary coming soon...</p>
      </CardContent>
    </Card>
  );
}
