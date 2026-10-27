"use client";

import { usePathname } from "next/navigation";
import { EngineAvailabilityHint } from "@/components/EngineAvailabilityHint";
import { IBDataDegradedBanner } from "@/components/IBDataDegradedBanner";
import { LLMProviderBadge } from "@/components/LLMProviderBadge";
import { AnomalySentinelStrip } from "@/components/AnomalySentinelStrip";
import { SystemFreshnessStrip } from "@/components/SystemFreshnessStrip";
import { CommandPalette } from "@/components/CommandPalette";
import { PendingApprovalToastListener } from "@/components/PendingApprovalToastListener";
import { SafetyEventListener } from "@/components/SafetyEventListener";
import { EngineWebSocketProvider } from "@/lib/engine-websocket-context";
import { ToastProvider } from "@/lib/toast-context";
import { Sidebar } from "@/components/Sidebar";

function isPublicReadOnlyPath(pathname: string | null): boolean {
  return pathname === "/market-brief-public" || pathname?.startsWith("/market-brief-public/") === true;
}

function isTapePath(pathname: string | null): boolean {
  return pathname === "/tape" || pathname?.startsWith("/tape/") === true;
}

function isMissionControlPath(pathname: string | null): boolean {
  return pathname === "/mission-control" || pathname?.startsWith("/mission-control/") === true;
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  // /tape is a standalone read-only terminal view: no engine providers, no sidebar, no account surfaces.
  if (isPublicReadOnlyPath(pathname) || isTapePath(pathname)) {
    return <main className="min-h-screen bg-background">{children}</main>;
  }

  const missionControlFocus = isMissionControlPath(pathname);

  return (
    <ToastProvider>
      <EngineWebSocketProvider>
        <PendingApprovalToastListener />
        <SafetyEventListener />
        <CommandPalette />
        <AnomalySentinelStrip />
        <EngineAvailabilityHint />
        <SystemFreshnessStrip />
        <IBDataDegradedBanner />
        <LLMProviderBadge />
        <div className="flex min-h-screen">
          {!missionControlFocus && <Sidebar />}
          <main className="flex-1 min-w-0 overflow-x-hidden">
            {children}
          </main>
        </div>
      </EngineWebSocketProvider>
    </ToastProvider>
  );
}
