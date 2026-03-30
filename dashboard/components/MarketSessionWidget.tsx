"use client";

import { useEffect, useState } from "react";
import { Calendar, Clock, Moon, Sun } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

// ── Types ─────────────────────────────────────────────────────────────────────

type SessionState = "regular" | "extended" | "maintenance" | "closed";

interface CTComponents {
  hours: number;
  minutes: number;
  dayOfWeek: number; // 0=Sun, 1=Mon ... 6=Sat
}

interface SessionInfo {
  state: SessionState;
  label: string;
  nextEventLabel: string;
  nextEventMinutes: number;
  ctTimeDisplay: string;
  ctDayName: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function getCTComponents(): CTComponents {
  const now = new Date();
  const ctStr = now.toLocaleString("en-US", { timeZone: "America/Chicago" });
  const ctDate = new Date(ctStr);
  return {
    hours: ctDate.getHours(),
    minutes: ctDate.getMinutes(),
    dayOfWeek: ctDate.getDay(),
  };
}

function getCTTimeDisplay(): string {
  const now = new Date();
  return now.toLocaleTimeString("en-US", {
    timeZone: "America/Chicago",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: true,
  });
}

/** Convert hours + minutes to total minutes from midnight */
function toMinutes(hours: number, minutes: number): number {
  return hours * 60 + minutes;
}

/** Format a minutes duration as "Xh Ym" or "Ym" */
function formatDuration(totalMinutes: number): string {
  const h = Math.floor(totalMinutes / 60);
  const m = totalMinutes % 60;
  if (h === 0) return `${m}m`;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}m`;
}

const DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

/**
 * Determine the current CME Globex session state.
 *
 * Key session windows (all CT):
 *   Regular Trading Hours (RTH): Mon-Fri 08:30–15:15
 *   Settlement:                  Mon-Fri 16:00–16:30
 *   Globex Extended:             Sun 17:00 through Fri 16:00 (nearly 23hr)
 *   Weekend Maintenance:         Fri 16:00 through Sun 17:00
 */
function computeSessionInfo(): SessionInfo {
  const { hours, minutes, dayOfWeek } = getCTComponents();
  const ctNow = toMinutes(hours, minutes);
  const ctTimeDisplay = getCTTimeDisplay();
  const ctDayName = DAY_NAMES[dayOfWeek];

  // Boundary constants (minutes from midnight CT)
  const RTH_OPEN = toMinutes(8, 30);   // 8:30am
  const RTH_CLOSE = toMinutes(15, 15); // 3:15pm
  const GLOBEX_CLOSE_FRI = toMinutes(16, 0); // 4:00pm Friday (Globex closes)
  const GLOBEX_OPEN_SUN = toMinutes(17, 0);  // 5:00pm Sunday (Globex opens)

  // --- SUNDAY ---
  if (dayOfWeek === 0) {
    if (ctNow < GLOBEX_OPEN_SUN) {
      // Still in weekend maintenance (before 5pm Sunday)
      const minutesUntilOpen = GLOBEX_OPEN_SUN - ctNow;
      return {
        state: "maintenance",
        label: "Weekend Maintenance",
        nextEventLabel: `Opens in ${formatDuration(minutesUntilOpen)}`,
        nextEventMinutes: minutesUntilOpen,
        ctTimeDisplay,
        ctDayName,
      };
    } else {
      // Globex is open (after 5pm Sunday) — extended hours
      // Next event: RTH opens Monday 8:30am = minutes until end of Sunday + 8:30 into Monday
      const minutesRemainingSunday = 24 * 60 - ctNow;
      const minutesUntilRTH = minutesRemainingSunday + RTH_OPEN;
      return {
        state: "extended",
        label: "Extended Hours",
        nextEventLabel: `RTH opens in ${formatDuration(minutesUntilRTH)}`,
        nextEventMinutes: minutesUntilRTH,
        ctTimeDisplay,
        ctDayName,
      };
    }
  }

  // --- SATURDAY ---
  if (dayOfWeek === 6) {
    // Weekend maintenance all day Saturday
    // Globex opens Sunday 5pm: minutes to end of Saturday + time into Sunday until 5pm
    const minutesRemainingSaturday = 24 * 60 - ctNow;
    const minutesUntilOpen = minutesRemainingSaturday + GLOBEX_OPEN_SUN;
    return {
      state: "maintenance",
      label: "Weekend Maintenance",
      nextEventLabel: `Opens in ${formatDuration(minutesUntilOpen)}`,
      nextEventMinutes: minutesUntilOpen,
      ctTimeDisplay,
      ctDayName,
    };
  }

  // --- MONDAY–THURSDAY ---
  if (dayOfWeek >= 1 && dayOfWeek <= 4) {
    if (ctNow >= RTH_OPEN && ctNow < RTH_CLOSE) {
      // Regular Trading Hours
      const minutesUntilClose = RTH_CLOSE - ctNow;
      return {
        state: "regular",
        label: "Regular Hours",
        nextEventLabel: `RTH closes in ${formatDuration(minutesUntilClose)}`,
        nextEventMinutes: minutesUntilClose,
        ctTimeDisplay,
        ctDayName,
      };
    } else {
      // Extended hours (Globex is open but outside RTH)
      if (ctNow < RTH_OPEN) {
        // Pre-market: before 8:30am
        const minutesUntilRTH = RTH_OPEN - ctNow;
        return {
          state: "extended",
          label: "Extended Hours",
          nextEventLabel: `RTH opens in ${formatDuration(minutesUntilRTH)}`,
          nextEventMinutes: minutesUntilRTH,
          ctTimeDisplay,
          ctDayName,
        };
      } else {
        // After-hours: after 3:15pm, before midnight (Globex still open until 4pm next day)
        const minutesUntilNextRTH = (24 * 60 - ctNow) + RTH_OPEN;
        return {
          state: "extended",
          label: "Extended Hours",
          nextEventLabel: `RTH opens in ${formatDuration(minutesUntilNextRTH)}`,
          nextEventMinutes: minutesUntilNextRTH,
          ctTimeDisplay,
          ctDayName,
        };
      }
    }
  }

  // --- FRIDAY ---
  if (dayOfWeek === 5) {
    if (ctNow >= RTH_OPEN && ctNow < RTH_CLOSE) {
      // Regular Trading Hours
      const minutesUntilClose = RTH_CLOSE - ctNow;
      return {
        state: "regular",
        label: "Regular Hours",
        nextEventLabel: `RTH closes in ${formatDuration(minutesUntilClose)}`,
        nextEventMinutes: minutesUntilClose,
        ctTimeDisplay,
        ctDayName,
      };
    } else if (ctNow < RTH_OPEN) {
      // Pre-market Friday
      const minutesUntilRTH = RTH_OPEN - ctNow;
      return {
        state: "extended",
        label: "Extended Hours",
        nextEventLabel: `RTH opens in ${formatDuration(minutesUntilRTH)}`,
        nextEventMinutes: minutesUntilRTH,
        ctTimeDisplay,
        ctDayName,
      };
    } else if (ctNow >= RTH_CLOSE && ctNow < GLOBEX_CLOSE_FRI) {
      // After RTH close but before Globex close (3:15pm–4:00pm)
      const minutesUntilGlobexClose = GLOBEX_CLOSE_FRI - ctNow;
      return {
        state: "extended",
        label: "Extended Hours",
        nextEventLabel: `Globex closes in ${formatDuration(minutesUntilGlobexClose)}`,
        nextEventMinutes: minutesUntilGlobexClose,
        ctTimeDisplay,
        ctDayName,
      };
    } else {
      // After 4:00pm Friday — weekend maintenance
      // Next open: Sunday 5:00pm
      const minutesRemainingFriday = 24 * 60 - ctNow;
      const minutesUntilOpen = minutesRemainingFriday + (24 * 60) + GLOBEX_OPEN_SUN;
      return {
        state: "maintenance",
        label: "Weekend Maintenance",
        nextEventLabel: `Opens in ${formatDuration(minutesUntilOpen)}`,
        nextEventMinutes: minutesUntilOpen,
        ctTimeDisplay,
        ctDayName,
      };
    }
  }

  // Fallback (should not be reached)
  return {
    state: "closed",
    label: "Closed",
    nextEventLabel: "—",
    nextEventMinutes: 0,
    ctTimeDisplay,
    ctDayName,
  };
}

function sessionBadgeVariant(state: SessionState): "bull" | "bear" | "warn" | "info" | "neutral" {
  switch (state) {
    case "regular":     return "bull";
    case "extended":    return "info";
    case "maintenance": return "neutral";
    case "closed":      return "bear";
  }
}

function SessionIcon({ state }: { state: SessionState }) {
  switch (state) {
    case "regular":
      return <Sun className="h-4 w-4 text-bull" />;
    case "extended":
      return <Moon className="h-4 w-4 text-info" />;
    case "maintenance":
      return <Moon className="h-4 w-4 text-muted-foreground" />;
    case "closed":
      return <Moon className="h-4 w-4 text-bear" />;
  }
}

// ── Key Times Reference ───────────────────────────────────────────────────────

const KEY_TIMES = [
  { label: "Globex Open",  value: "Sun 5:00pm CT" },
  { label: "RTH Open",     value: "Mon–Fri 8:30am CT" },
  { label: "RTH Close",    value: "Mon–Fri 3:15pm CT" },
  { label: "Globex Close", value: "Fri 4:00pm CT" },
];

// ── Component ─────────────────────────────────────────────────────────────────

export function MarketSessionWidget() {
  const [session, setSession] = useState<SessionInfo>(() => computeSessionInfo());

  useEffect(() => {
    const tick = () => setSession(computeSessionInfo());
    const interval = setInterval(tick, 60_000);
    return () => clearInterval(interval);
  }, []);

  const badgeVariant = sessionBadgeVariant(session.state);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/10">
              <Clock className="h-4 w-4 text-accent" />
            </div>
            <CardTitle>Market Session</CardTitle>
          </div>
          <Badge variant={badgeVariant}>
            <span className="flex items-center gap-1">
              <SessionIcon state={session.state} />
              {session.label}
            </span>
          </Badge>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Session name + CT time */}
        <div className="flex items-end justify-between gap-4">
          <div>
            <p className="text-2xl font-bold text-foreground">{session.label}</p>
            <div className="flex items-center gap-1.5 mt-1">
              <Calendar className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-xs text-muted-foreground">{session.ctDayName}</span>
            </div>
          </div>
          <div className="text-right">
            <p className="text-lg font-mono font-semibold text-foreground tabular-nums">
              {session.ctTimeDisplay}
            </p>
            <p className="text-[11px] text-muted-foreground">Central Time</p>
          </div>
        </div>

        {/* Next event countdown */}
        <div className="rounded-lg border border-border bg-muted/30 px-3 py-2.5 flex items-center gap-2">
          <Clock className="h-4 w-4 text-muted-foreground flex-shrink-0" />
          <span className="text-sm font-medium text-foreground">{session.nextEventLabel}</span>
        </div>

        {/* Key times reference table */}
        <div className="space-y-1">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">
            Session Times
          </p>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1">
            {KEY_TIMES.map((kt) => (
              <div key={kt.label} className="flex items-center justify-between gap-2 py-1 border-b border-border/50 last:border-0">
                <span className="text-xs text-muted-foreground">{kt.label}</span>
                <span className="text-xs font-mono font-medium text-foreground">{kt.value}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Footer note */}
        <p className="text-[11px] text-muted-foreground text-center pt-1">
          CME Globex (MES/MGC) — Central Time — updates every 60s
        </p>
      </CardContent>
    </Card>
  );
}
