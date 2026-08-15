"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Clock, TrendingUp, Moon, Sun, Sunset } from "lucide-react";
import { fetchEngine } from "@/lib/api";

interface MarketSession {
  session: string;
  label: string;
  color: string;
  is_trading_hours: boolean;
  is_futures_active: boolean;
  timestamp_ct: string;
  next_session: string;
  minutes_until_next: number | null;
  day_of_week: string;
}

const SESSION_ICONS: Record<string, React.ReactNode> = {
  RTH: <TrendingUp className="h-4 w-4" />,
  PRE_MARKET: <Sun className="h-4 w-4" />,
  AFTER_HOURS: <Sunset className="h-4 w-4" />,
  OVERNIGHT: <Moon className="h-4 w-4" />,
  FUTURES_OPEN: <TrendingUp className="h-4 w-4" />,
  WEEKEND: <Moon className="h-4 w-4" />,
};

const SESSION_BADGE: Record<string, "bull" | "bear" | "warn" | "info" | "neutral"> = {
  RTH: "bull",
  PRE_MARKET: "warn",
  AFTER_HOURS: "warn",
  FUTURES_OPEN: "info",
  OVERNIGHT: "neutral",
  WEEKEND: "neutral",
};

export function MarketSessionIndicator() {
  const [session, setSession] = useState<MarketSession | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    const fetch_session = async () => {
      try {
        const data = await fetchEngine("/market/session");
        setSession(data);
        setError(false);
      } catch {
        setError(true);
      }
    };

    fetch_session();
    const interval = setInterval(fetch_session, 60_000); // refresh every minute
    return () => clearInterval(interval);
  }, []);

  if (error || !session) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Clock className="h-4 w-4" />
        <span>Market session unavailable</span>
      </div>
    );
  }

  const icon = SESSION_ICONS[session.session] ?? <Clock className="h-4 w-4" />;
  const variant = SESSION_BADGE[session.session] ?? "neutral";

  return (
    <div className="flex items-center gap-3 p-3 rounded-lg border bg-card">
      <div className="flex items-center gap-2">
        {icon}
        <div>
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium">{session.label}</span>
            <Badge variant={variant}>{session.day_of_week}</Badge>
          </div>
          {session.minutes_until_next !== null && (
            <p className="text-xs text-muted-foreground">
              {session.next_session} in {session.minutes_until_next}m
            </p>
          )}
        </div>
      </div>
      {session.is_futures_active && (
        <div className="ml-auto flex items-center gap-1">
          <div className="h-2 w-2 rounded-full bg-green-500 animate-pulse" />
          <span className="text-xs text-muted-foreground">Futures Active</span>
        </div>
      )}
    </div>
  );
}
