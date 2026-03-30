"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const ENGINE_URL = process.env.NEXT_PUBLIC_ENGINE_URL || "http://localhost:8010";

// ── Types ──────────────────────────────────────────────────────────────────────

interface AlertHistoryItem {
  id: string;
  level: string;
  message: string;
  timestamp: string;
  category?: string;
}

interface ActiveAlert {
  id: string;
  level: string;
  message: string;
  timestamp: string;
}

type BadgeVariant = "bull" | "bear" | "warn" | "info" | "neutral";

// ── Helpers ────────────────────────────────────────────────────────────────────

function levelToVariant(level: string): BadgeVariant {
  const l = (level ?? "").toUpperCase();
  if (l === "CRITICAL" || l === "ERROR") return "bear";
  if (l === "WARNING" || l === "WARN") return "warn";
  if (l === "INFO") return "info";
  return "neutral";
}

function activeBorderClass(level: string): string {
  const l = (level ?? "").toUpperCase();
  if (l === "CRITICAL" || l === "ERROR") return "border-l-4 border-l-bear bg-bear/5";
  if (l === "WARNING" || l === "WARN") return "border-l-4 border-l-warn bg-warn/5";
  if (l === "INFO") return "border-l-4 border-l-info bg-info/5";
  return "border-l-4 border-l-border bg-muted/30";
}

function relativeTime(isoString: string): string {
  try {
    const diffMs = Date.now() - new Date(isoString).getTime();
    const diffSec = Math.floor(diffMs / 1_000);
    if (diffSec < 60) return "just now";
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHr = Math.floor(diffMin / 60);
    if (diffHr < 24) return `${diffHr}h ago`;
    const diffDay = Math.floor(diffHr / 24);
    return `${diffDay}d ago`;
  } catch {
    return "";
  }
}

function isWithin24h(isoString: string): boolean {
  try {
    const ts = new Date(isoString).getTime();
    if (isNaN(ts)) return false;
    return Date.now() - ts <= 24 * 60 * 60 * 1_000;
  } catch {
    return false;
  }
}

// ── Component ──────────────────────────────────────────────────────────────────

export function AlertSummaryWidget() {
  const [history, setHistory] = useState<AlertHistoryItem[]>([]);
  const [active, setActive] = useState<ActiveAlert[]>([]);
  const [loading, setLoading] = useState(true);

  async function fetchData() {
    try {
      const [historyRes, activeRes] = await Promise.allSettled([
        fetch(`${ENGINE_URL}/alerts/history?limit=50`),
        fetch(`${ENGINE_URL}/alerts/active`),
      ]);

      if (historyRes.status === "fulfilled" && historyRes.value.ok) {
        const data: AlertHistoryItem[] = await historyRes.value.json();
        setHistory(Array.isArray(data) ? data : []);
      }

      // /alerts/active may return 404 when no active alerts — handle gracefully
      if (activeRes.status === "fulfilled") {
        if (activeRes.value.status === 404) {
          setActive([]);
        } else if (activeRes.value.ok) {
          const data: ActiveAlert[] = await activeRes.value.json();
          setActive(Array.isArray(data) ? data : []);
        } else {
          setActive([]);
        }
      } else {
        setActive([]);
      }
    } catch {
      // Keep previous state on network error
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30_000);
    return () => clearInterval(interval);
  }, []);

  // ── Summary counts (last 24h) ────────────────────────────────────────────────
  const recent24h = history.filter((a) => isWithin24h(a.timestamp));

  const criticalCount = recent24h.filter((a) => {
    const l = (a.level ?? "").toUpperCase();
    return l === "CRITICAL" || l === "ERROR";
  }).length;

  const warningCount = recent24h.filter((a) => {
    const l = (a.level ?? "").toUpperCase();
    return l === "WARNING" || l === "WARN";
  }).length;

  const infoCount = recent24h.filter((a) => {
    const l = (a.level ?? "").toUpperCase();
    return l === "INFO";
  }).length;

  const last5History = history.slice(0, 5);

  // ── Render ───────────────────────────────────────────────────────────────────
  return (
    <Card className="border-border bg-card">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle>Alert Summary</CardTitle>
          <span className="font-mono text-[10px] text-muted-foreground/50">
            Refreshes every 30s
          </span>
        </div>
      </CardHeader>

      <CardContent className="pt-0 space-y-4">
        {/* ── Loading skeleton ─────────────────────────────────────────────── */}
        {loading && (
          <div className="flex items-center justify-center py-8 font-mono text-xs text-muted-foreground/50">
            Loading alerts…
          </div>
        )}

        {!loading && (
          <>
            {/* ── 3-col summary cards (last 24h) ───────────────────────────── */}
            <div className="grid grid-cols-3 gap-3">
              <div className="rounded-lg border border-bear/20 bg-bear/5 p-3 text-center">
                <p className="font-mono text-[10px] text-muted-foreground uppercase tracking-wider mb-1">
                  Critical
                </p>
                <p
                  className={cn(
                    "font-mono text-2xl font-bold tabular-nums",
                    criticalCount > 0 ? "text-bear" : "text-muted-foreground/40"
                  )}
                >
                  {criticalCount}
                </p>
                <p className="f