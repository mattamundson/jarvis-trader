"use client";

import React, { useState, useEffect } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";


// ── ET time helpers ────────────────────────────────────────────────────────

interface ETTime {
  year: number;
  month: number;   // 1–12
  day: number;     // 1–31
  hour: number;    // 0–23
  minute: number;  // 0–59
  second: number;  // 0–59
  weekday: number; // 0 = Sunday, 6 = Saturday
  timeString: string; // "10:32:45 AM ET"
}

function getETTime(now: Date): ETTime {
  const fmtParts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    weekday: "short",
  });

  const parts = fmtParts.formatToParts(now);
  const get = (type: string) => {
    const p = parts.find((x) => x.type === type);
    return p ? parseInt(p.value, 10) : 0;
  };
  const getStr = (type: string) => parts.find((x) => x.type === type)?.value ?? "";

  // hour12:false can return 24 for midnight; normalize
  const rawHour = get("hour");
  const hour = rawHour === 24 ? 0 : rawHour;
  const minute = get("minute");
  const second = get("second");

  const weekdayStr = getStr("weekday");
  const weekdayMap: Record<string, number> = {
    Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6,
  };
  const weekday = weekdayMap[weekdayStr] ?? 0;

  // Build display string using 12-hour format
  const displayFmt = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    hour12: true,
  });
  const timeString = displayFmt.format(now) + " ET";

  return {
    year: get("year"),
    month: get("month"),
    day: get("day"),
    hour,
    minute,
    second,
    weekday,
    timeString,
  };
}

// Convert ET h:m to total minutes since midnight
function toMin(h: number, m: number): number {
  return h * 60 + m;
}

// ── ET offset helpers ──────────────────────────────────────────────────────

// Get ET offset vs UTC in minutes (e.g. -300 for EST, -240 for EDT)
function getETOffsetMinutes(now: Date): number {
  const ref = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    hour: "numeric",
    hour12: false,
  }).formatToParts(now);
  const rawHour = parseInt(ref.find((p) => p.type === "hour")?.value ?? "0", 10);
  const etHour = rawHour === 24 ? 0 : rawHour;
  const utcHour = now.getUTCHours();
  let diff = etHour - utcHour;
  if (diff > 12) diff -= 24;
  if (diff < -12) diff += 24;
  return diff * 60;
}

// Build UTC epoch ms for a given ET date + h:m
function sameDayET(et: ETTime, etOffsetMin: number, h: number, m: number): number {
  const pad = (n: number) => String(n).padStart(2, "0");
  const etStr = `${et.year}-${pad(et.month)}-${pad(et.day)}T${pad(h)}:${pad(m)}:00`;
  return new Date(etStr + "Z").getTime() + etOffsetMin * 60 * 1000;
}

// Build UTC epoch ms for the next occurrence of a weekday at h:m ET
function nextWeekdayET(now: Date, et: ETTime, etOffsetMin: number, targetWeekday: number, h: number, m: number): number {
  let daysAhead = targetWeekday - et.weekday;
  if (daysAhead <= 0) daysAhead += 7;
  const pad = (n: number) => String(n).padStart(2, "0");
  const targetDate = new Date(Date.UTC(et.year, et.month - 1, et.day) + daysAhead * 86400000);
  const y = targetDate.getUTCFullYear();
  const mo = targetDate.getUTCMonth() + 1;
  const d = targetDate.getUTCDate();
  const etStr = `${y}-${pad(mo)}-${pad(d)}T${pad(h)}:${pad(m)}:00`;
  // Re-compute offset at target date for DST accuracy
  const approxMs = new Date(etStr + "Z").getTime() + etOffsetMin * 60 * 1000;
  const offsetAtTarget = getETOffsetMinutes(new Date(approxMs));
  void now;
  return new Date(etStr + "Z").getTime() + offsetAtTarget * 60 * 1000;
}

// ── Session logic ──────────────────────────────────────────────────────────

type SessionStatus = "RTH" | "GLOBEX" | "MAINTENANCE" | "WEEKEND";

interface SessionInfo {
  status: SessionStatus;
  label: string;
  badgeVariant: "bull" | "bear" | "warn" | "info" | "neutral";
  countdownLabel: string;
  nextBoundaryMs: number;
}

function computeSession(now: Date, et: ETTime): SessionInfo {
  const { hour, minute, weekday } = et;
  const etOffsetMin = getETOffsetMinutes(now);
  const minOfDay = toMin(hour, minute);

  // Saturday: all-day WEEKEND
  if (weekday === 6) {
    const nextOpen = nextWeekdayET(now, et, etOffsetMin, 0, 18, 0); // Sunday 18:00
    return { status: "WEEKEND", label: "WEEKEND", badgeVariant: "neutral", countdownLabel: "Globex opens in", nextBoundaryMs: nextOpen };
  }

  // Sunday before 18:00: WEEKEND
  if (weekday === 0 && minOfDay < toMin(18, 0)) {
    const nextOpen = sameDayET(et, etOffsetMin, 18, 0);
    return { status: "WEEKEND", label: "WEEKEND", badgeVariant: "neutral", countdownLabel: "Globex opens in", nextBoundaryMs: nextOpen };
  }

  // Sunday 18:00+: GLOBEX → next RTH is Monday 9:30
  if (weekday === 0 && minOfDay >= toMin(18, 0)) {
    const nextRTH = nextWeekdayET(now, et, etOffsetMin, 1, 9, 30);
    return { status: "GLOBEX", label: "GLOBEX OPEN", badgeVariant: "info", countdownLabel: "RTH opens in", nextBoundaryMs: nextRTH };
  }

  // Mon–Fri logic:
  // RTH: 9:30 – 16:00
  if (minOfDay >= toMin(9, 30) && minOfDay < toMin(16, 0)) {
    const nextClose = sameDayET(et, etOffsetMin, 16, 0);
    return { status: "RTH", label: "RTH OPEN", badgeVariant: "bull", countdownLabel: "Closes in", nextBoundaryMs: nextClose };
  }

  // MAINTENANCE: 16:00 – 18:00 (post-RTH gap + official maintenance window)
  if (minOfDay >= toMin(16, 0) && minOfDay < toMin(18, 0)) {
    const nextGlobex = sameDayET(et, etOffsetMin, 18, 0);
    return { status: "MAINTENANCE", label: "MAINTENANCE", badgeVariant: "warn", countdownLabel: "Globex opens in", nextBoundaryMs: nextGlobex };
  }

  // GLOBEX: before 9:30 AM or after 18:00 Mon–Fri
  if (minOfDay < toMin(9, 30)) {
    // Overnight session — RTH opens today
    const nextRTH = sameDayET(et, etOffsetMin, 9, 30);
    return { status: "GLOBEX", label: "GLOBEX OPEN", badgeVariant: "info", countdownLabel: "RTH opens in", nextBoundaryMs: nextRTH };
  }

  // After 18:00 Mon–Fri → RTH opens next trading day
  let nextTradingWeekday: number;
  if (weekday === 5) {
    // Friday night → Monday
    nextTradingWeekday = 1;
  } else {
    nextTradingWeekday = weekday + 1;
  }
  const nextRTH = nextWeekdayET(now, et, etOffsetMin, nextTradingWeekday, 9, 30);
  return { status: "GLOBEX", label: "GLOBEX OPEN", badgeVariant: "info", countdownLabel: "RTH opens in", nextBoundaryMs: nextRTH };
}

// ── Countdown formatter ────────────────────────────────────────────────────

function formatCountdown(targetMs: number, nowMs: number): string {
  const diff = Math.max(0, Math.floor((targetMs - nowMs) / 1000));
  const h = Math.floor(diff / 3600);
  const m = Math.floor((diff % 3600) / 60);
  const s = diff % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${h}:${pad(m)}:${pad(s)}`;
}

// ── Upcoming sessions ─────────────────────────────────────────────────────

interface UpcomingEvent {
  label: string;
  desc: string;
}

function etFmt(ms: number): string {
  return (
    new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York",
      weekday: "short",
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    }).format(new Date(ms)) + " ET"
  );
}

function buildUpcoming(now: Date): UpcomingEvent[] {
  const et = getETTime(now);
  const etOffsetMin = getETOffsetMinutes(now);
  const nowMs = now.getTime();
  const { weekday, hour, minute } = et;
  const minOfDay = toMin(hour, minute);

  const candidates: { label: string; ms: number }[] = [];

  // RTH Open: 9:30 AM ET Mon–Fri
  if (weekday >= 1 && weekday <= 5 && minOfDay < toMin(9, 30)) {
    candidates.push({ label: "RTH Opens", ms: sameDayET(et, etOffsetMin, 9, 30) });
  } else {
    // Next trading day
    const nextTD = weekday === 0 || weekday === 6 ? 1 : weekday === 5 ? 1 : weekday + 1;
    candidates.push({ label: "RTH Opens", ms: nextWeekdayET(now, et, etOffsetMin, nextTD, 9, 30) });
  }

  // RTH Close: 4:00 PM ET Mon–Fri
  if (weekday >= 1 && weekday <= 5 && minOfDay < toMin(16, 0)) {
    candidates.push({ label: "RTH Closes", ms: sameDayET(et, etOffsetMin, 16, 0) });
  } else {
    const nextTD = weekday === 0 || weekday === 6 ? 1 : weekday >= 1 && weekday <= 4 ? weekday + 1 : 1;
    candidates.push({ label: "RTH Closes", ms: nextWeekdayET(now, et, etOffsetMin, nextTD, 16, 0) });
  }

  // Globex Open: 6:00 PM ET (Mon–Fri and Sun)
  const canOpenToday =
    (weekday === 0 || (weekday >= 1 && weekday <= 4)) && minOfDay < toMin(18, 0);
  if (canOpenToday) {
    candidates.push({ label: "Globex Opens", ms: sameDayET(et, etOffsetMin, 18, 0) });
  } else if (weekday === 5 && minOfDay < toMin(18, 0)) {
    candidates.push({ label: "Globex Opens", ms: sameDayET(et, etOffsetMin, 18, 0) });
  } else if (weekday === 5 && minOfDay >= toMin(18, 0)) {
    // Fri evening → Sunday 18:00
    candidates.push({ label: "Globex Opens", ms: nextWeekdayET(now, et, etOffsetMin, 0, 18, 0) });
  } else if (weekday === 6) {
    candidates.push({ label: "Globex Opens", ms: nextWeekdayET(now, et, etOffsetMin, 0, 18, 0) });
  } else {
    // Mon–Thu after 18:00 → tomorrow 18:00
    candidates.push({ label: "Globex Opens", ms: nextWeekdayET(now, et, etOffsetMin, weekday + 1, 18, 0) });
  }

  return candidates
    .filter((c) => c.ms > nowMs)
    .sort((a, b) => a.ms - b.ms)
    .slice(0, 3)
    .map((ev) => ({ label: ev.label, desc: etFmt(ev.ms) }));
}

// ── Timeline bar ──────────────────────────────────────────────────────────

function TimelineBar({ et }: { et: ETTime }) {
  const totalMin = 1440;
  const pct = (min: number) => `${((min / totalMin) * 100).toFixed(3)}%`;

  // Blocks (minutes from midnight ET in a 24-hour view):
  // Globex part 1:  0:00 – 9:30  (570 min)
  // RTH:            9:30 – 16:00 (390 min)
  // Maintenance:   16:00 – 18:00 (120 min)
  // Globex part 2: 18:00 – 24:00 (360 min)
  const rthStart = toMin(9, 30);   // 570
  const rthEnd   = toMin(16, 0);   // 960
  const maintEnd = toMin(18, 0);   // 1080

  const currentMin = toMin(et.hour, et.minute) + et.second / 60;
  const markerPct = (currentMin / totalMin) * 100;

  return (
    <div className="relative w-full h-6 rounded overflow-hidden flex" style={{ fontSize: 9 }}>
      {/* Globex: 0:00 – 9:30 */}
      <div
        className="h-full bg-info/20 border-r border-info/30 flex items-center justify-center text-info overflow-hidden whitespace-nowrap"
        style={{ width: pct(rthStart) }}
      >
        <span className="px-0.5 truncate">Globex</span>
      </div>
      {/* RTH: 9:30 – 16:00 */}
      <div
        className="h-full bg-bull/20 border-r border-bull/30 flex items-center justify-center text-bull overflow-hidden whitespace-nowrap"
        style={{ width: pct(rthEnd - rthStart) }}
      >
        <span className="px-0.5 truncate">RTH</span>
      </div>
      {/* Maintenance: 16:00 – 18:00 */}
      <div
        className="h-full bg-warn/20 border-r border-warn/30 flex items-center justify-center text-warn overflow-hidden whitespace-nowrap"
        style={{ width: pct(maintEnd - rthEnd) }}
      >
        <span className="px-0.5 truncate">Maint.</span>
      </div>
      {/* Globex: 18:00 – 24:00 */}
      <div
        className="h-full bg-info/20 flex items-center justify-center text-info overflow-hidden whitespace-nowrap"
        style={{ width: pct(totalMin - maintEnd) }}
      >
        <span className="px-0.5 truncate">Globex</span>
      </div>
      {/* Current time marker */}
      <div
        className="absolute top-0 bottom-0 w-0.5 bg-foreground/70 z-10"
        style={{ left: `${markerPct.toFixed(3)}%` }}
      />
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────

export function MarketSessionWidget() {
  const [now, setNow] = useState<Date>(() => new Date());
  const [engineOnline, setEngineOnline] = useState<boolean | null>(null);

  // Tick every 10 seconds
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 10_000);
    return () => clearInterval(id);
  }, []);

  // Engine health check (optional, failure handled gracefully)
  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        await fetchEngine(`/health`, {
          signal: AbortSignal.timeout(4000),
        });
        if (!cancelled) setEngineOnline(true);
      } catch {
        if (!cancelled) setEngineOnline(false);
      }
    };
    check();
    const id = setInterval(check, 30_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const et = getETTime(now);
  const session = computeSession(now, et);
  const countdown = formatCountdown(session.nextBoundaryMs, now.getTime());
  const upcoming = buildUpcoming(now);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Market Session</CardTitle>
          {engineOnline !== null && (
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <span
                className={`inline-block h-2 w-2 rounded-full ${
                  engineOnline ? "bg-bull animate-pulse" : "bg-bear"
                }`}
              />
              Engine {engineOnline ? "online" : "offline"}
            </span>
          )}
        </div>
      </CardHeader>

      <CardContent>
        {/* Current ET time + session badge */}
        <div className="flex items-baseline gap-3 mb-4">
          <span className="text-2xl font-mono font-semibold tracking-tight text-foreground">
            {et.timeString}
          </span>
          <Badge variant={session.badgeVariant}>{session.label}</Badge>
        </div>

        {/* Countdown to next session change */}
        <div className="flex items-center gap-2 mb-5 text-sm text-muted-foreground">
          <span>{session.countdownLabel}</span>
          <span className="font-mono text-foreground font-medium tabular-nums">
            {countdown}
          </span>
        </div>

        {/* Timeline bar */}
        <div className="mb-1">
          <p className="text-xs text-muted-foreground mb-1.5">
            Today&apos;s schedule (midnight → midnight ET)
          </p>
          <TimelineBar et={et} />
          <div className="flex justify-between text-[10px] text-muted-foreground mt-0.5">
            <span>12 AM</span>
            <span>9:30 AM</span>
            <span>4 PM</span>
            <span>6 PM</span>
            <span>11:59 PM</span>
          </div>
        </div>

        {/* Upcoming sessions */}
        {upcoming.length > 0 && (
          <div className="mt-4 space-y-1.5 border-t border-border pt-3">
            <p className="text-xs text-muted-foreground mb-2">Upcoming</p>
            {upcoming.map((ev, i) => (
              <div key={i} className="flex justify-between items-center text-sm">
                <span className="text-muted-foreground">{ev.label}</span>
                <span className="font-mono text-xs text-foreground">{ev.desc}</span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
