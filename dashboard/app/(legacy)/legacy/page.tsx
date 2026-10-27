"use client";

import Link from "next/link";
import { Archive, AlertTriangle } from "lucide-react";
import { Badge } from "@/components/ui/badge";

interface LegacyPage {
  path: string;
  name: string;
  reason: string;
  status: "dead" | "superseded";
}

const LEGACY_PAGES: LegacyPage[] = [
  {
    path: "/domflow",
    name: "DOM Flow",
    reason: "Backend service on port 8030 is down",
    status: "dead",
  },
  {
    path: "/jarvis",
    name: "Ask Jarvis",
    reason: "Folded into command center",
    status: "superseded",
  },
  {
    path: "/journal-review",
    name: "Journal Review",
    reason: "Folded into performance and journal tabs",
    status: "superseded",
  },
  {
    path: "/parallel-paper",
    name: "Parallel Paper",
    reason: "Folded into paper trading as tab",
    status: "superseded",
  },
];

export default function LegacyIndexPage() {
  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border bg-card">
        <div className="mx-auto max-w-[1400px] px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-muted">
              <Archive className="h-5 w-5 text-muted-foreground" />
            </div>
            <div>
              <h1 className="font-bold text-foreground">Legacy Pages</h1>
              <p className="text-xs text-muted-foreground">
                Dead or superseded pages archived for reference
              </p>
            </div>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1400px] px-6 py-6 space-y-4">
        <div className="rounded-lg border border-warn/40 bg-warn/5 px-4 py-3 flex items-start gap-2">
          <AlertTriangle className="h-4 w-4 text-warn mt-0.5 flex-shrink-0" />
          <div>
            <p className="text-sm text-warn font-medium">
              These pages are archived and may not function correctly
            </p>
            <p className="text-xs text-warn/80 mt-1">
              Dead pages have non-functional backends. Superseded pages have been
              replaced by newer implementations.
            </p>
          </div>
        </div>

        <div className="space-y-2">
          {LEGACY_PAGES.map((page) => (
            <Link
              key={page.path}
              href={page.path}
              className="block rounded-lg border border-border bg-card p-4 hover:bg-muted/40 transition-colors"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <h3 className="text-sm font-semibold text-foreground">
                      {page.name}
                    </h3>
                    <Badge
                      variant={page.status === "dead" ? "bear" : "warn"}
                    >
                      {page.status}
                    </Badge>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {page.reason}
                  </p>
                  <p className="text-[10px] text-muted-foreground/60 mt-1 font-mono">
                    {page.path}
                  </p>
                </div>
              </div>
            </Link>
          ))}
        </div>

        <div className="text-center pt-4">
          <Link
            href="/"
            className="text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            ← Back to Dashboard
          </Link>
        </div>
      </main>
    </div>
  );
}
