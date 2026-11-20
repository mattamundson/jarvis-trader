import type { Metadata } from "next";
import localFont from "next/font/local";
import { headers } from "next/headers";
import { decideDashboardAuth, readDashboardAuthEnv } from "@/lib/dashboardAuth";
import { AppShell } from "@/components/AppShell";
import { SpeedInsights } from "@vercel/speed-insights/next";
import "./globals.css";

const inter = localFont({
  src: "./fonts/Inter-latin.woff2",
  variable: "--font-sans",
  display: "swap",
  weight: "100 900",
  style: "normal",
});

const jetbrainsMono = localFont({
  src: "./fonts/JetBrainsMono-latin.woff2",
  variable: "--font-mono",
  display: "swap",
  weight: "100 800",
  style: "normal",
});

export const metadata: Metadata = {
  title: "JARVIS TRADER",
  description: "LLM-powered autonomous trading system — IBKR Futures + Schwab Options",
};

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // Reading request headers keeps this status request-specific, not build-time.
  // Middleware has already validated Basic Auth before allowing a page render.
  // Only the status crosses the client boundary, never credentials or headers.
  const requestHeaders = await headers();
  const decision = decideDashboardAuth({ ...readDashboardAuthEnv(), disabled: undefined });
  const authStatus = decision === "enforce" && requestHeaders.get("authorization")?.startsWith("Basic ")
    ? "authenticated"
    : decision === "allow" ? "unprotected" : "unknown";

  return (
    <html lang="en" className={`${inter.variable} ${jetbrainsMono.variable}`}>
      <body className="min-h-screen bg-background font-sans antialiased">
        <AppShell authStatus={authStatus}>{children}</AppShell>
        <SpeedInsights />
      </body>
    </html>
  );
}
