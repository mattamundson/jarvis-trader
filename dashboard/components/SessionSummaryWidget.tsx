"use client";

import useSWR from "swr";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useHonestTrades } from "@/lib/useHonestTrades";
import { isHonestUnavailable, dailyPnl } from "@/lib/honestTrades";
import { fetchPnlTruth, type PnlTruthResponse } from "@/lib/api";
import { formatCurrency } from "@/lib/utils";

/**
 * Today's closed-trade P&L, sourced from the honest deduped trade record
 * (lib/honestTrades.ts) rather than the raw, over-counting engine
 * session-today endpoint (TodaySummaryWidget.tsx uses that raw source and is
 * labeled as such via RawRecordBadge — this widget is its honest/deduped
 * counterpart, same two-scoreboard convention as HonestPnlCard.tsx vs the raw
 * /master history).
 *
 * When the honest record is unavailable (master-api down), falls back to the
 * engine-native `/pnl/truth` aggregate with an explicit `ENGINE-LOCAL` static
 * badge. That endpoint has no date filter, so the fallback figure is an
 * all-time realized aggregate, not "today's" number, and the copy says so
 * rather than presenting it as the session figure.
 */

function todayLocalDate(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function signed(n: number): string {
  return `${n >= 0 ? "+" : ""}${formatCurrency(n)}`;
}

export function SessionSummaryWidget() {
  const { honest, isLoading: loadingHonest } = useHonestTrades();
  const unavailable = isHonestUnavailable(honest, loadingHonest);

  // Fallback source — SWR key stays null (no fetch) unless the honest record
  // has settled unavailable, so this never races the primary source.
  const { data: truth } = useSWR<PnlTruthResponse>(
    unavailable ? "pnl-truth-fallback-session-summary" : null,
    fetchPnlTruth,
    { refreshInterval: 60_000, shouldRetryOnError: false, errorRetryCount: 0 },
  );

  // ── Primary: honest deduped record, filtered to today's local close date ──
  if (honest) {
    const today = dailyPnl(honest.trades).find((d) => d.date === todayLocalDate());
    const count = today?.count ?? 0;
    const pnl = today?.pnl ?? 0;

    return (
      <Card>
        <CardHeader>
          <CardTitle>Session Summary</CardTitle>
        </CardHeader>
        <CardContent>
          {count === 0 ? (
            <p className="text-muted-foreground">No closed trades this session</p>
          ) : (
            <div className="space-y-1">
              <p
                className={`font-mono text-2xl font-bold tabular-nums ${
                  pnl >= 0 ? "text-bull" : "text-bear"
                }`}
              >
                {signed(pnl)}
              </p>
              <p className="text-xs text-muted-foreground">
                {count} closed trade{count === 1 ? "" : "s"} today (deduped)
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    );
  }

  // ── Loading: honest record still resolving, not yet settled unavailable ──
  if (loadingHonest) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Session Summary</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground">Loading session record…</p>
        </CardContent>
      </Card>
    );
  }

  // ── Fallback: honest record unavailable — engine-native /pnl/truth
  // (all-time, not date-scoped; labeled ENGINE-LOCAL so it never reads as
  // "today's" figure) ─────────────────────────────────────────────────────
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Session Summary
          <Badge
            variant="static"
            title="Honest deduped record unavailable — showing the engine's own /pnl/truth ledger instead (all-time, not scoped to today)."
          >
            ENGINE-LOCAL
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {!truth ? (
          <p className="text-muted-foreground">Reading engine ledger…</p>
        ) : truth.closed_trades === 0 ? (
          <p className="text-muted-foreground">No closed trades this session</p>
        ) : (
          <div className="space-y-1">
            <p
              className={`font-mono text-2xl font-bold tabular-nums ${
                truth.realized_pnl == null
                  ? "text-warn"
                  : truth.realized_pnl >= 0
                    ? "text-bull"
                    : "text-bear"
              }`}
            >
              {truth.realized_pnl == null ? "—" : signed(truth.realized_pnl)}
            </p>
            <p className="text-xs text-muted-foreground">
              {truth.closed_trades} closed trade
              {truth.closed_trades === 1 ? "" : "s"} · engine ledger, all-time
              — deduped session record unavailable
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
