"use client";

import React, { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";


// ── Session logic ─────────────────────────────────────────────────────────────

interface SessionInfo {
  name: string;
  isOpen: boolean;
  description: string;
}

function getCurrentSession(): SessionInfo {
  const now = new Date();
  // Convert UTC to CT (UTC-6 standard / UTC-5 daylight — use fixed UTC-5 for CDT coverage)
  // We compute the CT offset properly via toLocaleString trick to avoid DST issues
  const ctString = now.toLocaleString("en-US", { timeZone: "America/Chicago" });
  const ct = new Date(ctString);

  const day = ct.getDay(); // 0=Sun, 6=Sat
  const hour = ct.getHours();
  const minute = ct.getMinutes();
  const totalMinutes = hour * 60 + minute;

  // RTH: 8:30 AM – 3:15 PM CT (510 – 915 minutes)
  const RTH_OPEN = 8 * 60 + 30;   // 510
  const RTH_CLOSE = 15 * 60 + 15; // 915

  // Settlement: 3:15 PM – 5:00 PM CT (915 – 1020 minutes)
  const SETTLEMENT_CLOSE = 17 * 60; // 1020

  if (day === 0 || day === 6) {
    return { name: "WEEKEND", isOpen: false, description: "Markets closed" };
  }

  if (totalMinutes >= RTH_OPEN && totalMinutes < RTH_CLOSE) {
    return {
      name: "RTH",
      isOpen: true,
      description: "Regular Trading Hours 8:30AM–3:15PM CT",
    };
  }

  if (totalMinutes >= RTH_CLOSE && totalMinutes < SETTLEMENT_CLOSE) {
    return {
      name: "SETTLEMENT",
      isOpen: false,
      description: "Daily settlement 3:15–5:00PM CT",
    };
  }

  // Extended / overnight (before 8:30 AM or after 5 PM CT on weekdays)
  return {
    name: "EXTENDED",
    isOpen: true,
    description: "Futures extended session active",
  };
}

// ── Next-event calculation ────────────────────────────────────────────────────

function formatDuration(totalMs: number): string {
  if (totalMs <= 0) return "now";
  const totalSec = Math.floor(totalMs / 1000);
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function getNextEvent(session: SessionInfo): string {
  const now = new Date();
  const ctString = now.toLocaleString("en-US", { timeZone: "America/Chicago" });
  const ct = new Date(ctString);

  const day = ct.getDay();
  const hour = ct.getHours();
  const minute = ct.getMinutes();
  const totalMinutes = hour * 60 + minute;

  const RTH_OPEN = 8 * 60 + 30;
  const RTH_CLOSE = 15 * 60 + 15;

  if (day === 0 || day === 6) {
    // Find next Monday RTH open
    const daysUntilMon = day === 0 ? 1 : 2;
    return `RTH opens in ${daysUntilMon * 24}h+ (Monday)`;
  }

  if (session.name === "RTH") {
    // Until RTH close
    const minRemaining = RTH_CLOSE - totalMinutes;
    const ms = minRemaining * 60 * 1000;
    return `RTH closes in ${formatDuration(ms)}`;
  }

  if (session.name === "SETTLEMENT") {
    // Until RTH open tomorrow (or today if before midnight somehow)
    const minUntilMidnight = (24 * 60) - totalMinutes;
    const minFromMidnightToRTH = RTH_OPEN;
    const totalMin = minUntilMidnight + minFromMidnightToRTH;
    // But if it's Friday settlement, next RTH is Monday
    if (day === 5) {
      return "RTH opens Monday 8:30AM CT";
    }
    const ms = totalMin * 60 * 1000;
    return `RTH opens in ${formatDuration(ms)}`;
  }

  // EXTENDED: show time until RTH open
  if (totalMinutes < RTH_OPEN) {
    const minRemaining = RTH_OPEN - totalMinutes;
    const ms = minRemaining * 60 * 1000;
    return `RTH opens in ${formatDuration(ms)}`;
  }

  // Extended after settlement (after 5 PM on weekday)
  if (day === 5) {
    return "RTH opens Monday 8:30AM CT";
  }
  const minUntilMidnight = (24 * 60) - totalMinutes;
  const minFromMidnightToRTH = RTH_OPEN;
  const totalMin = minUntilMidnight + minFromMidnightToRTH;
  const ms = totalMin * 60 * 1000;
  return `RTH opens in ${formatDuration(ms)}`;
}

// ── CT time string ────────────────────────────────────────────────────────────

function getCTTimeString(): string {
  return new Date().toLocaleTimeString("en-US", {
    timeZone: "America/Chicago",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: true,
  });
}

// ── Badge variant + label helpers ────────────────────────────────────────────

function sessionBadgeVariant(name: string): "bull" | "info" | "neutral" | "bear" {
  if (name === "RTH") return "bull";
  if (name === "EXTENDED") return "info";
  if (name === "SETTLEMENT") return "neutral";
  return "neutral"; // WEEKEND
}

function sessionLabel(session: SessionInfo): string {
  if (session.name === "RTH") return "RTH OPEN";
  if (session.name === "EXTENDED") return "EXTENDED";
  if (session.name === "SETTLEMENT") return "SETTLEMENT";
  return "WEEKEND";
}

// ── SessionTodayData ──────────────────────────────────────────────────────────

interface SessionTodayData {
  session: string;
  date: string;
  closed_trades: number;
  open_trades: number;
  gross_pnl: number;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function MarketSessionStatusCard() {
  // Initialize with stable, SSR-safe values — no new Date() during render — so the
  // server-rendered markup matches the client's first paint. Real values are filled
  // in the mount effect (tick()). Prevents React hydration error #418.
  const [ctTime, setCTTime] = useState<string>("");
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [nextEvent, setNextEvent] = useState<string>("");
  const [sessionData, setSessionData] = useState<SessionTodayData | null>(null);
  const [fetchError, setFetchError] = useState<boolean>(false);

  function tick() {
    const s = getCurrentSession();
    setCTTime(getCTTimeString());
    setSession(s);
    setNextEvent(getNextEvent(s));
  }

  async function fetchSessionData() {
    try {
      const data = await fetchEngine(`/portfolio/stats/session-today`);
      setSessionData(data);
      setFetchError(false);
    } catch {
      setFetchError(true);
    }
  }

  useEffect(() => {
    tick();
    fetchSessionData();

    const clockInterval = setInterval(tick, 1000);
    const fetchInterval = setInterval(fetchSessionData, 60_000);

    return () => {
      clearInterval(clockInterval);
      clearInterval(fetchInterval);
    };
  }, []);

  const badgeVariant = sessionBadgeVariant(session?.name ?? "");
  const label = session ? sessionLabel(session) : "—";

  return (
    <Card className="border-[#1a1a2e] bg-[#0a0a0a]">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="font-mono text-xs font-bold tracking-[0.15em] uppercase text-neutral-400">
            Market Session
          </CardTitle>
          {/* Live pulse dot when market open */}
          {session?.isOpen && (
            <span className="relative flex h-2.5 w-2.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-500" />
            </span>
          )}
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Big status badge */}
        <div className="flex items-center gap-3">
          <Badge variant={badgeVariant} className="text-sm font-mono font-bold px-3 py-1 tracking-widest">
            {label}
          </Badge>
        </div>

        {/* Description */}
        <p className="font-mono text-xs text-neutral-500 leading-relaxed">
          {session?.description ?? ""}
        </p>

        {/* CT clock */}
        <div className="flex items-center justify-between rounded-lg border border-[#1a1a2e] bg-[#0d0d0d] px-3 py-2">
          <span className="font-mono text-[11px] text-neutral-600 uppercase tracking-wider">
            CT Time
          </span>
          <span className="font-mono text-sm text-neutral-200 tabular-nums">
            {ctTime || "—"}
          </span>
        </div>

        {/* Next event */}
        {nextEvent && (
          <div className="flex items-center gap-2 font-mono text-[11px] text-neutral-500">
            <span className="text-neutral-700">&#x25B6;</span>
            <span>{nextEvent}</span>
          </div>
        )}

        {/* Engine session data (if available) */}
        {sessionData && !fetchError && (
          <div className="grid grid-cols-3 gap-2 rounded-lg border border-[#1a1a2e] bg-[#0d0d0d] p-3">
            <div className="text-center">
              <p className="font-mono text-[10px] text-neutral-600 uppercase tracking-wider">
                Trades
              </p>
              <p className="font-mono text-sm font-semibold text-neutral-200 tabular-nums">
                {sessionData.closed_trades}
              </p>
            </div>
            <div className="text-center">
              <p className="font-mono text-[10px] text-neutral-600 uppercase tracking-wider">
                Open
              </p>
              <p className="font-mono text-sm font-semibold text-neutral-200 tabular-nums">
                {sessionData.open_trades}
              </p>
            </div>
            <div className="text-center">
              <p className="font-mono text-[10px] text-neutral-600 uppercase tracking-wider">
                P&amp;L
              </p>
              <p
                className={`font-mono text-sm font-semibold tabular-nums ${
                  sessionData.gross_pnl > 0
                    ? "text-emerald-400"
                    : sessionData.gross_pnl < 0
                    ? "text-red-400"
                    : "text-neutral-400"
                }`}
              >
                {sessionData.gross_pnl >= 0 ? "+" : ""}
                {sessionData.gross_pnl.toFixed(2)}
              </p>
            </div>
          </div>
        )}

        {sessionData && !fetchError && (
          <p className="font-mono text-[10px] text-amber-500/70 leading-relaxed">
            Session trades &amp; P&amp;L are from the raw engine record (not deduped) —
            may include re-logged duplicates.
          </p>
        )}

        {fetchError && (
          <p className="font-mono text-[10px] text-neutral-700">
            Engine offline — showing client-side session only
          </p>
        )}

        {/* MES contract note */}
        <p className="font-mono text-[10px] text-neutral-700 border-t border-[#1a1a2e] pt-3 leading-relaxed">
          MES Futures &middot; 24hr nearly continuous &middot; RTH: 8:30AM–3:15PM CT
        </p>
      </CardContent>
    </Card>
  );
}
