import { beforeEach, describe, expect, it, vi } from "vitest";
import RootLayout from "@/app/layout";
import { headers } from "next/headers";
import { AppShell } from "@/components/AppShell";
import { decideDashboardAuth, readDashboardAuthEnv } from "@/lib/dashboardAuth";

vi.mock("next/headers", () => ({ headers: vi.fn() }));
vi.mock("next/font/local", () => ({ default: () => ({ variable: "font-variable" }) }));
vi.mock("@/components/AppShell", () => ({ AppShell: vi.fn() }));
vi.mock("@vercel/speed-insights/next", () => ({ SpeedInsights: () => null }));
vi.mock("@/lib/dashboardAuth", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/dashboardAuth")>(),
  readDashboardAuthEnv: vi.fn(),
}));

async function shellProps() {
  const tree = await RootLayout({ children: "CONTENT" });
  const body = tree.props.children;
  const shell = body.props.children[0];
  expect(shell.type).toBe(AppShell);
  return shell.props;
}

beforeEach(() => {
  vi.mocked(readDashboardAuthEnv).mockReturnValue({ user: "test-owner", pass: "test-only" });
  vi.mocked(headers).mockResolvedValue(new Headers({ authorization: "Basic test-only" }) as Awaited<ReturnType<typeof headers>>);
});

describe("request-specific authentication status", () => {
  it("passes only signed-in status after middleware-admitted Basic authentication", async () => {
    expect(await shellProps()).toEqual({ authStatus: "authenticated", children: "CONTENT" });
    expect(headers).toHaveBeenCalled();
  });

  it("does not claim authentication without a Basic header", async () => {
    vi.mocked(headers).mockResolvedValue(new Headers() as Awaited<ReturnType<typeof headers>>);
    expect((await shellProps()).authStatus).toBe("unknown");
  });

  it("labels unauthenticated local development honestly", async () => {
    vi.mocked(readDashboardAuthEnv).mockReturnValue({});
    expect((await shellProps()).authStatus).toBe("unprotected");
  });

  it("never treats a hosted deployment with missing credentials as signed in", async () => {
    vi.mocked(readDashboardAuthEnv).mockReturnValue({ vercel: "1", disabled: "1" });
    expect((await shellProps()).authStatus).toBe("unknown");
    expect(decideDashboardAuth({ vercel: "1", disabled: undefined })).toBe("deny");
  });
});
