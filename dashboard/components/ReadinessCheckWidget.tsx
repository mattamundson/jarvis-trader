"use client";

import React from "react";
import useSWR from "swr";
import { CheckCircle2, RefreshCw, ShieldCheck, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

interface ReadinessCheck {
  name: string;
  passed: boolean;
  value: string;
  requirement: string;
  critical: boolean;
}

interface ReadinessReport {
  ready_for_live: boolean;
  all_checks_pass: boolean;
  checks: ReadinessCheck[];
  passed: number;
  total: number;
  summary: "READY" | "NOT READY";
}

// ── Fetcher ───────────────────────────────────────────────────────────────────

const fetchReadiness = () =>
  fetchEngine<ReadinessReport>("/validation/readiness-check");

// ── Component ─────────────────────────────────────────────────────────────────

export function ReadinessCheckWidget() {
  const { data, isLoading, mutate } = useSWR<ReadinessReport>(
    "validation/readiness-check",
    fetchReadiness,
    { refreshInterval: 120_000 }
  );

  const isReady = data?.ready_for_live ?? false;
  const summary = data?.summary ?? "NOT READY";

  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      {/* Header */}
      <div className="px-5 py-4 border-b border-border flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-4 w-4 text-muted-foreground" />
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Pre-Live Readiness Check
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Overall badge */}
          {isLoading ? (
            <div className="h-5 w-20 rounded-full bg-muted animate-pulse" />
          ) : (
            <Badge variant={isReady ? "bull" : "bear"}>
              {isReady ? (
                <CheckCircle2 className="h-3 w-3 mr-1" />
              ) : (
                <XCircle className="h-3 w-3 mr-1" />
              )}
              {summary}
            </Badge>
          )}

          {/* Score */}
          {data && !isLoading && (
            <span className="text-xs text-muted-foreground font-mono">
              {data.passed}/{data.total}
            </span>
          )}

          {/* Manual refresh */}
          <button
            onClick={() => mutate()}
            disabled={isLoading}
            className="flex items-center gap-1 rounded-lg border border-border px-2 py-1 text-xs text-muted-foreground hover:text-foreground transition-colors disabled:opacity-40"
          >
            <RefreshCw className={`h-3 w-3 ${isLoading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {/* Check rows */}
      <div className="divide-y divide-border">
        {isLoading
          ? Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="flex items-center gap-3 px-5 py-3 animate-pulse">
                <div className="h-4 w-4 rounded-full bg-muted flex-shrink-0" />
                <div className="flex-1 h-3 bg-muted rounded" />
                <div className="h-3 w-12 bg-muted rounded" />
                <div className="h-3 w-16 bg-muted rounded" />
              </div>
            ))
          : (data?.checks ?? []).map((check) => (
              <div
                key={check.name}
                className={`flex items-center gap-3 px-5 py-3 ${
                  !check.critical ? "opacity-70" : ""
                }`}
              >
                {/* Pass / fail icon */}
                {check.passed ? (
                  <CheckCircle2 className="h-4 w-4 text-bull flex-shrink-0" />
                ) : (
                  <XCircle className="h-4 w-4 text-bear flex-shrink-0" />
                )}

                {/* Check name */}
                <span
                  className={`flex-1 text-xs font-medium ${
                    check.passed ? "text-foreground" : "text-muted-foreground"
                  }`}
                >
                  {check.name}
                  {!check.critical && (
                    <span className="ml-1 text-[10px] text-muted-foreground font-normal">
                      (optional)
                    </span>
                  )}
                </span>

                {/* Current value */}
                <span
                  className={`text-xs font-mono font-bold w-20 text-right ${
                    check.passed ? "text-bull" : "text-bear"
                  }`}
                >
                  {check.value}
                </span>

                {/* Requirement */}
                <span className="text-xs text-muted-foreground w-24 text-right">
                  {check.requirement}
                </span>
              </div>
            ))}
      </div>

      {/* Footer note */}
      {data && !isLoading && (
        <div className="px-5 py-2.5 border-t border-border bg-muted/20">
          <p className="text-[10px] text-muted-foreground">
            Critical checks must all pass to advance to live trading &mdash; auto-refresh every 2 min
          </p>
        </div>
      )}
    </div>
  );
}
