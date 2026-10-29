"use client";

import React from "react";
import { BarChart3, Target, Clock, Award } from "lucide-react";
import { Badge } from "@/components/ui/badge";

export default function SetupScorecardPage() {
  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-50 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto max-w-[1400px] px-6 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/10">
              <Target className="h-5 w-5 text-accent" />
            </div>
            <div>
              <h1 className="font-bold text-foreground">Setup Scorecard</h1>
              <p className="text-xs text-muted-foreground">
                Paper trade setup performance tracking
              </p>
            </div>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1400px] px-6 py-6 space-y-6">
        <div className="rounded-lg border border-warn/40 bg-warn/5 px-4 py-2.5">
          <p className="text-xs text-warn">
            Setup scorecard not yet wired to live data. Check back after setup log integration is complete.
          </p>
        </div>

        <div className="rounded-xl border border-border bg-card p-12 text-center">
          <Target className="h-16 w-16 text-muted-foreground mx-auto mb-4 opacity-50" />
          <h2 className="text-lg font-semibold text-foreground mb-2">No Setup Data</h2>
          <p className="text-sm text-muted-foreground max-w-md mx-auto">
            The setup scorecard will track pre-trade setups by type, time, and R multiples 
            once the setup log integration is complete. No demo data is shown.
          </p>
        </div>

        <p className="text-[11px] text-muted-foreground text-center pb-4">
          Setup scorecard tracks pre-trade setups by type, time, and R multiples.
          No account info or dollar amounts.
        </p>
      </main>
    </div>
  );
}
