"use client";

import useSWR from "swr";
import { Radar, TrendingDown, TrendingUp, ShieldAlert, Clock } from "lucide-react";
import { fetchEngine } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

// The autonomous pipeline ticks every 30 minutes; refresh well inside that so
// a fresh candidate appears within seconds of being enqueued.
const REFRESH_MS = 30_000;
const HISTORY_DAYS = 7;

interface SignalCandidate {
  id: number;
  created_at: string;
  symbol: string;
  direction: "LONG" | "SHORT" | string;
  confidence: number | null;
  expires_at: string;
  status: string;
  reviewed_at: string | null;
  reviewer_notes: string | null;
  order_id: string | null;
  stark_signal: string | null;
  validation_only: boolean;
}

interface PendingResponse {
  count: number;
  candidates: SignalCandidate[];
}

interface HistoryResponse {
  days: number;
  count: number;
  history: SignalCandidate[];
}

function fetcher<T = unknown>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

function fmtTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString("en-US", {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function minutesLeft(expiresIso: string): number | null {
  try {
    const ms = new Date(expiresIso).getTime() - Date.now();
    return Math.max(0, Math.round(ms / 60_000));
  } catch {
    return null;
  }
}

/**
 * Confidence is the pipeline's model-derived probability that the setup works
 * (Brier-tracked; see /health brier_30d_rolling). Rendered as a bar so weak
 * and strong candidates read at a glance.
 */
function ConfidenceBar({ value }: { value: number | null }) {
  if (value == null) {
    return <span className="font-mono text-[11px] text-muted-foreground">—</span>;
  }
  const pct = Math.round(value * 100);
  return (
    <div className="flex items-center gap-2 min-w-[110px]">
      <div className="h-1.5 w-16 rounded-full bg-border overflow-hidden">
        <div
          className={`h-full rounded-full ${pct >= 75 ? "bg-emerald-500" : pct >= 60 ? "bg-amber-500" : "bg-muted-foreground"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="font-mono text-[11px] text-foreground">{pct}%</span>
    </div>
  );
}

function DirectionBadge({ direction }: { direction: string }) {
  const long = direction === "LONG";
  return (
    <Badge variant={long ? "bull" : "bear"} className="font-mono text-[10px] gap-1">
      {long ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
      {direction}
    </Badge>
  );
}

function StatusBadge({ c }: { c: SignalCandidate }) {
  if (c.validation_only) {
    return (
      <Badge variant="warn" className="font-mono text-[10px] gap-1">
        <ShieldAlert className="h-3 w-3" /> GATED
      </Badge>
    );
  }
  const variant =
    c.status === "approved" ? "bull"
    : c.status === "rejected" ? "bear"
    : c.status === "expired" ? "neutral"
    : "info";
  return (
    <Badge variant={variant} className="font-mono text-[10px]">
      {c.status.toUpperCase()}
    </Badge>
  );
}

function SignalRow({ c, showTtl }: { c: SignalCandidate; showTtl: boolean }) {
  const ttl = showTtl ? minutesLeft(c.expires_at) : null;
  return (
    <TableRow>
      <TableCell className="font-mono text-xs">{fmtTime(c.created_at)}</TableCell>
      <TableCell className="font-mono text-xs font-semibold">{c.symbol}</TableCell>
      <TableCell><DirectionBadge direction={c.direction} /></TableCell>
      <TableCell className="font-mono text-[11px] text-muted-foreground">
        {c.stark_signal ?? "—"}
      </TableCell>
      <TableCell><ConfidenceBar value={c.confidence} /></TableCell>
      <TableCell><StatusBadge c={c} /></TableCell>
      {showTtl && (
        <TableCell className="font-mono text-[11px] text-muted-foreground">
          {ttl != null ? (
            <span className="flex items-center gap-1">
              <Clock className="h-3 w-3" /> {ttl}m
            </span>
          ) : "—"}
        </TableCell>
      )}
    </TableRow>
  );
}

export default function SignalsPage() {
  const { data: pending, error: pendingError, isLoading: pendingLoading } =
    useSWR<PendingResponse>("/approvals/pending", fetcher, { refreshInterval: REFRESH_MS });
  const { data: history, error: historyError } =
    useSWR<HistoryResponse>(`/approvals/history?days=${HISTORY_DAYS}`, fetcher, {
      refreshInterval: 5 * 60_000,
    });

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-50 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] flex items-center gap-3 px-6 py-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/10">
            <Radar className="h-5 w-5 text-accent" />
          </div>
          <div>
            <h1 className="font-bold text-foreground tracking-tight">Trade Signals</h1>
            <p className="text-xs text-muted-foreground">
              Autonomous pipeline candidates with model probabilities — futures now, options/equities next
            </p>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] px-6 py-6 space-y-6">
        <Card>
          <CardHeader>
            <CardTitle className="font-mono text-sm flex items-center justify-between">
              <span>Live candidates</span>
              <span className="text-[11px] font-normal text-muted-foreground">
                pipeline ticks every 30 min · auto-refresh {REFRESH_MS / 1000}s
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            {pendingLoading && (
              <p className="font-mono text-xs text-muted-foreground italic">Loading signals…</p>
            )}
            {pendingError && (
              <p className="font-mono text-xs text-muted-foreground italic">
                Engine unreachable — no live signals available.
              </p>
            )}
            {pending && pending.candidates.length === 0 && (
              <p className="font-mono text-xs text-muted-foreground italic">
                No live candidates right now. The next pipeline tick is at most 30 minutes out.
              </p>
            )}
            {pending && pending.candidates.length > 0 && (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="font-mono text-[10px]">TIME</TableHead>
                    <TableHead className="font-mono text-[10px]">SYMBOL</TableHead>
                    <TableHead className="font-mono text-[10px]">SIDE</TableHead>
                    <TableHead className="font-mono text-[10px]">STRATEGY</TableHead>
                    <TableHead className="font-mono text-[10px]">P(WIN)</TableHead>
                    <TableHead className="font-mono text-[10px]">STATUS</TableHead>
                    <TableHead className="font-mono text-[10px]">TTL</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pending.candidates.map((c) => (
                    <SignalRow key={c.id} c={c} showTtl />
                  ))}
                </TableBody>
              </Table>
            )}
            <p className="mt-3 font-mono text-[10px] text-muted-foreground">
              GATED = strategy is in VALIDATION_ONLY_STRATEGIES (blocked from execution until
              WFO validation + gate v2 PASS). Probabilities are the pipeline&apos;s
              Brier-tracked confidence, not a guarantee.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="font-mono text-sm flex items-center justify-between">
              <span>Signal history ({HISTORY_DAYS}d)</span>
              <span className="text-[11px] font-normal text-muted-foreground">
                {history ? `${history.count} resolved` : ""}
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            {historyError && (
              <p className="font-mono text-xs text-muted-foreground italic">
                History unavailable — engine unreachable.
              </p>
            )}
            {history && history.history.length === 0 && (
              <p className="font-mono text-xs text-muted-foreground italic">
                No resolved candidates in the last {HISTORY_DAYS} days.
              </p>
            )}
            {history && history.history.length > 0 && (
              <div className="max-h-[480px] overflow-y-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="font-mono text-[10px]">TIME</TableHead>
                      <TableHead className="font-mono text-[10px]">SYMBOL</TableHead>
                      <TableHead className="font-mono text-[10px]">SIDE</TableHead>
                      <TableHead className="font-mono text-[10px]">STRATEGY</TableHead>
                      <TableHead className="font-mono text-[10px]">P(WIN)</TableHead>
                      <TableHead className="font-mono text-[10px]">OUTCOME</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {history.history.map((c) => (
                      <SignalRow key={c.id} c={c} showTtl={false} />
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </CardContent>
        </Card>
      </main>
    </div>
  );
}
