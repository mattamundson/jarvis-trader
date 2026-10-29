import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "@/components/AppShell";
import { usePathname } from "next/navigation";

vi.mock("next/navigation", () => ({ usePathname: vi.fn() }));

vi.mock("@/components/EngineAvailabilityHint", () => ({ EngineAvailabilityHint: () => null }));
vi.mock("@/components/IBDataDegradedBanner", () => ({ IBDataDegradedBanner: () => null }));
vi.mock("@/components/LLMProviderBadge", () => ({ LLMProviderBadge: () => null }));
vi.mock("@/components/AnomalySentinelStrip", () => ({ AnomalySentinelStrip: () => null }));
vi.mock("@/components/SystemFreshnessStrip", () => ({ SystemFreshnessStrip: () => null }));
vi.mock("@/components/CommandPalette", () => ({ CommandPalette: () => null }));
vi.mock("@/components/PendingApprovalToastListener", () => ({ PendingApprovalToastListener: () => null }));
vi.mock("@/components/SafetyEventListener", () => ({ SafetyEventListener: () => null }));
vi.mock("@/components/Sidebar", () => ({ Sidebar: () => <nav>PRIMARY SIDEBAR</nav> }));
vi.mock("@/lib/engine-websocket-context", () => ({
  EngineWebSocketProvider: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("@/lib/toast-context", () => ({
  ToastProvider: ({ children }: { children: React.ReactNode }) => children,
}));

const mockedUsePathname = vi.mocked(usePathname);

beforeEach(() => mockedUsePathname.mockReset());

describe("AppShell route layout", () => {
  it("keeps Mission Control full-width by omitting the primary sidebar", () => {
    mockedUsePathname.mockReturnValue("/mission-control");
    render(<AppShell><section>MISSION CONTROL CONTENT</section></AppShell>);

    expect(screen.getByText("MISSION CONTROL CONTENT")).toBeInTheDocument();
    expect(screen.queryByText("PRIMARY SIDEBAR")).not.toBeInTheDocument();
  });

  it("retains the primary sidebar on ordinary authenticated routes", () => {
    mockedUsePathname.mockReturnValue("/stats");
    render(<AppShell><section>STATS CONTENT</section></AppShell>);

    expect(screen.getByText("PRIMARY SIDEBAR")).toBeInTheDocument();
    expect(screen.getByText("STATS CONTENT")).toBeInTheDocument();
  });
});

describe("AppShell authentication status", () => {
  beforeEach(() => mockedUsePathname.mockReturnValue("/stats"));

  it("confirms a verified sign-in without asking the owner to sign in again", () => {
    render(<AppShell authStatus="authenticated"><section>CONTENT</section></AppShell>);
    expect(screen.getByRole("status")).toHaveTextContent("Signed in · Dashboard protected");
    expect(screen.queryByRole("link", { name: "Owner sign in" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Authentication required/)).not.toBeInTheDocument();
  });

  it("does not claim protection when local development permits anonymous access", () => {
    render(<AppShell authStatus="unprotected"><section>CONTENT</section></AppShell>);
    expect(screen.getByRole("status")).toHaveTextContent("Not signed in · Local authentication is not configured");
    expect(screen.queryByText("Signed in · Dashboard protected")).not.toBeInTheDocument();
  });

  it("does not claim sign-in when authentication status is unavailable", () => {
    render(<AppShell><section>CONTENT</section></AppShell>);
    expect(screen.getByRole("status")).toHaveTextContent("Sign-in status unavailable");
    expect(screen.getByRole("link", { name: "Owner sign in" })).toHaveAttribute("href", "/api/owner-sign-in");
  });
});
