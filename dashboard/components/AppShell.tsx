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

function isMissionControlPath(pathname: string | null): boolean {
  return pathname === "/mission-control" || pathname?.startsWith("/mission-control/") === true;
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  if (isPublicReadOnlyPath(pathname)) {
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
            <div role="status" className="border-b border-cyan-900/40 bg-slate-950 px-4 py-2 text-sm text-cyan-300">Private dashboard · Authentication required. <a className="ml-2 underline" href="/api/owner-sign-in">Owner sign in</a></div>
            {children}
          </main>
        </div>
      </EngineWebSocketProvider>
    </ToastProvider>
  );
}
