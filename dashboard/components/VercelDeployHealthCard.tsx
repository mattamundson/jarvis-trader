"use client";

import { Cloud, CheckCircle2, AlertTriangle, XCircle, Clock } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { useVercelDeployHealth } from "@/hooks/useVercelDeployHealth";

export function VercelDeployHealthCard() {
  const { data, error, isLoading } = useVercelDeployHealth();

  const offline = !!error || !data;
  const status = data?.status ?? "UNKNOWN";

  const tone: "ok" | "warn" | "bad" | "unknown" =
    status === "READY"
      ? "ok"
      : status === "ERROR"
      ? "bad"
      : status === "BUILDING"
      ? "warn"
      : "unknown";

  const TONE = {
    ok: { bg: "rgba(21,128,61,0.12)", border: "#15803d", fg: "#86efac" },
    warn: { bg: "rgba(180,83,9,0.14)", border: "#b45309", fg: "#fcd34d" },
    bad: { bg: "rgba(185,28,28,0.14)", border: "#b91c1c", fg: "#fca5a5" },
    unknown: { bg: "rgba(120,120,120,0.10)", border: "#6b7280", fg: "#cbd5e1" },
  };

  const t = TONE[tone];

  const icon =
    status === "READY" ? (
      <CheckCircle2 className="h-4 w-4" />
    ) : status === "ERROR" ? (
      <XCircle className="h-4 w-4" />
    ) : status === "BUILDING" ? (
      <AlertTriangle className="h-4 w-4" />
    ) : (
      <Clock className="h-4 w-4" />
    );

  const badgeVariant: "bull" | "bear" | "warn" | "neutral" =
    status === "READY" ? "bull" : status === "ERROR" ? "bear" : status === "BUILDING" ? "warn" : "neutral";

  const badgeLabel =
    status === "READY" ? "Ready" : status === "ERROR" ? "Error" : status === "BUILDING" ? "Building" : "Unknown";

  return (
    <div className="border border-border rounded-lg p-4 bg-card">
      <div className="flex items-baseline justify-between gap-3 mb-3">
        <h2 className="font-mono text-sm font-bold text-foreground">Vercel Production Deploy</h2>
        <Badge variant={badgeVariant}>
          <span className="flex items-center gap-1">
            {icon}
            {badgeLabel}
          </span>
        </Badge>
      </div>
      <div className="grid grid-cols-1 gap-2">
        <div
          className="rounded-md px-3 py-2 flex flex-col gap-0.5 min-w-0"
          style={{ backgroundColor: t.bg, border: `1px solid ${t.border}` }}
        >
          <span className="font-mono text-[10px] uppercase tracking-wide text-muted-foreground">
            Latest production deploy state from Vercel
          </span>
          <span className="font-mono text-sm font-bold truncate" style={{ color: t.border }}>
            {isLoading ? "Loading..." : offline ? "—" : status}
          </span>
          {data?.url && (
            <span className="font-mono text-[10px] text-muted-foreground truncate">{data.url}</span>
          )}
        </div>
      </div>
    </div>
  );
}
