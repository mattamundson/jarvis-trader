import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { AnomalySentinel } from "@/components/AnomalySentinel";
import { EngineAvailabilityHint } from "@/components/EngineAvailabilityHint";
import { JarvisCommandBar } from "@/components/JarvisCommandBar";
import { PendingApprovalToastListener } from "@/components/PendingApprovalToastListener";
import { SafetyEventListener } from "@/components/SafetyEventListener";
import { EngineWebSocketProvider } from "@/lib/engine-websocket-context";
import { ToastProvider } from "@/lib/toast-context";
import { Sidebar } from "@/components/Sidebar";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
  weight: ["400", "500", "700"],
});

export const metadata: Metadata = {
  title: "JARVIS TRADER",
  description: "LLM-powered autonomous trading system — IBKR Futures + Schwab Options",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${inter.variable} ${jetbrainsMono.variable}`}>
      <body className="min-h-screen bg-background font-sans antialiased">
        <ToastProvider>
          <EngineWebSocketProvider>
            <PendingApprovalToastListener />
            <SafetyEventListener />
            <EngineAvailabilityHint />
            <AnomalySentinel />
            <JarvisCommandBar />
            <div className="flex min-h-screen">
              <Sidebar />
              <main className="flex-1 min-w-0 overflow-x-hidden">
                {children}
              </main>
            </div>
          </EngineWebSocketProvider>
        </ToastProvider>
      </body>
    </html>
  );
}
