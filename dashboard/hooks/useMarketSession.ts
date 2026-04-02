"use client";

import { useState, useEffect } from "react";

export interface SessionInfo {
  label: string;
  color: string;
  badge: string;
  isActive: boolean;
}

function getMarketSession(): SessionInfo {
  const now = new Date();
  // Rough DST detection: DST is active Mar–Nov in the US
  const month = now.getMonth(); // 0-indexed
  const isDST = month > 2 && month < 10;
  const ctOffsetHours = isDST ? -5 : -6;
  const ctTime = new Date(
    now.getTime() + (now.getTimezoneOffset() + ctOffsetHours * 60) * 60000
  );
  const totalMinutes = ctTime.getHours() * 60 + ctTime.getMinutes();
  const day = ctTime.getDay(); // 0=Sun, 6=Sat

  if (day === 0 || day === 6) {
    return {
      label: "WEEKEND — CLOSED",
      color: "text-gray-500",
      badge: "bg-gray-800 text-gray-400 border-gray-700",
      isActive: false,
    };
  }
  if (totalMinutes < 8 * 60) {
    return {
      label: "PRE-MARKET PREP",
      color: "text-yellow-400",
      badge: "bg-yellow-950 text-yellow-400 border-yellow-800",
      isActive: false,
    };
  }
  if (totalMinutes < 9 * 60 + 35) {
    return {
      label: "PRE-RTH — AVOID",
      color: "text-orange-400",
      badge: "bg-orange-950 text-orange-400 border-orange-800",
      isActive: false,
    };
  }
  if (totalMinutes < 11 * 60 + 30) {
    return {
      label: "RTH MORNING — PRIMARY ★",
      color: "text-green-400",
      badge: "bg-green-950 text-green-400 border-green-800",
      isActive: true,
    };
  }
  if (totalMinutes < 13 * 60) {
    return {
      label: "MIDDAY LULL",
      color: "text-yellow-400",
      badge: "bg-yellow-950 text-yellow-400 border-yellow-800",
      isActive: false,
    };
  }
  if (totalMinutes < 15 * 60 + 30) {
    return {
      label: "RTH AFTERNOON — SECONDARY",
      color: "text-cyan-400",
      badge: "bg-cyan-950 text-cyan-400 border-cyan-800",
      isActive: true,
    };
  }
  if (totalMinutes < 17 * 60) {
    return {
      label: "AFTER-HOURS",
      color: "text-slate-400",
      badge: "bg-slate-800 text-slate-400 border-slate-700",
      isActive: false,
    };
  }
  return {
    label: "CLOSED",
    color: "text-gray-500",
    badge: "bg-gray-800 text-gray-400 border-gray-700",
    isActive: false,
  };
}

export function useMarketSession(): SessionInfo {
  const [session, setSession] = useState<SessionInfo>(() => getMarketSession());

  useEffect(() => {
    // Update every minute
    const interval = setInterval(() => {
      setSession(getMarketSession());
    }, 60_000);
    return () => clearInterval(interval);
  }, []);

  return session;
}
