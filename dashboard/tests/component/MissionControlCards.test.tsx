// Component tests for the two Mission Control cards added alongside the
// TOS RTD market-data work: TOSLiveQuotesCard (GET /prices/snapshot?symbols=...)
// and TradeRecommendationsCard (GET /pipeline/status).
//
// These pin the two things a reviewer cannot see from `tsc --noEmit`:
//   1. an absent/404 route degrades to an explicit offline state (never a
//      fabricated price or a blank card),
//   2. a happy-path payload renders the real numbers it was given.
//
// `@/lib/api` is mocked so no test ever touches a live engine or a socket.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { TOSLiveQuotesCard } from "@/components/TOSLiveQuotesCard";
import { TradeRecommendationsCard } from "@/components/TradeRecommendationsCard";
import { fetchEngine } from "@/lib/api";

vi.mock("@/lib/api", () => ({ fetchEngine: vi.fn() }));

const mockedFetchEngine = vi.mocked(fetchEngine);

function engineError(status: number, path: string): Error {
  // Shape thrown by lib/api.ts's EngineHttpError.
  return new Error(`Engine error ${status}: ${path}`);
}

function mockRoute(handler: (path: string) => unknown): void {
  mockedFetchEngine.mockImplementation((async (path: string) =>
    handler(path)) as unknown as typeof fetchEngine);
}

function mockRouteFailure(handler: (path: string) => Error): void {
  mockedFetchEngine.mockImplementation((async (path: string) => {
    throw handler(path);
  }) as unknown as typeof fetchEngine);
}

beforeEach(() => {
  mockedFetchEngine.mockReset();
});

describe("TOSLiveQuotesCard", () => {
  it("renders the offline state when the price route 404s on the engine", async () => {
    mockRouteFailure((path) => engineError(404, path));

    render(<TOSLiveQuotesCard />);

    expect(await screen.findByText(/Quotes offline/i)).toBeInTheDocument();
    expect(screen.getByText("OFFLINE")).toBeInTheDocument();
    // No price may be invented when the route is missing.
    expect(screen.queryByText("SPY")).not.toBeInTheDocument();
  });

  it("renders last/bid/ask and the source badge from a real payload", async () => {
    // /prices/snapshot returns one dict keyed by symbol.
    mockRoute(() => ({
      SPY: { symbol: "SPY", last: 512.34, bid: 512.3, ask: 512.4, source: "ib_gateway" },
      QQQ: { symbol: "QQQ", last: 441.02, bid: 441.0, ask: 441.05, source: "ib_gateway" },
      VIX: { symbol: "VIX", last: 14.88, bid: 14.87, ask: 14.89, source: "ib_gateway" },
    }));

    render(<TOSLiveQuotesCard />);

    // Symbol rows appear once every quote resolves.
    expect(await screen.findByText("SPY")).toBeInTheDocument();
    expect(screen.getByText("QQQ")).toBeInTheDocument();
    expect(screen.getByText("VIX")).toBeInTheDocument();
    expect(screen.getByText("512.34")).toBeInTheDocument();
    expect(screen.getByText("512.30")).toBeInTheDocument();
    expect(screen.getByText("512.40")).toBeInTheDocument();
    expect(screen.getAllByText("IBKR").length).toBe(3);
  });

  it("marks a stale quote with a warn source badge instead of dropping it", async () => {
    mockRoute(() => ({
      SPY: { symbol: "SPY", last: 1, bid: 1, ask: 1, source: "csv_cache" },
      QQQ: { symbol: "QQQ", last: 1, bid: 1, ask: 1, source: "csv_cache" },
      VIX: { symbol: "VIX", last: 15.5, bid: 15.49, ask: 15.51, source: "csv_cache", stale: true },
    }));

    render(<TOSLiveQuotesCard />);

    expect(await screen.findByText("15.50")).toBeInTheDocument();
    expect(screen.getAllByText("CACHE").length).toBe(3);
  });
});

describe("TradeRecommendationsCard", () => {
  it("renders 'Recommendations offline' when /pipeline/status 404s", async () => {
    mockRouteFailure((path) => engineError(404, path));

    render(<TradeRecommendationsCard />);

    expect(await screen.findByText(/Recommendations offline/i)).toBeInTheDocument();
    expect(screen.getByText("OFFLINE")).toBeInTheDocument();
  });

  it("renders symbol, direction, confidence and levels from last_run", async () => {
    mockRoute(() => ({
      available: true,
      sdk_available: true,
      decision_count: 7,
      last_run: {
        id: 7,
        timestamp: "2026-09-25T13:31:00-05:00",
        symbol: "MES",
        action: "BUY",
        confidence: 0.72,
        entry_price: 5300.25,
        stop_level: 5290.5,
        target_1: 5324.75,
      },
    }));

    render(<TradeRecommendationsCard />);

    expect(await screen.findByText("MES")).toBeInTheDocument();
    expect(screen.getByText("LONG")).toBeInTheDocument();
    expect(screen.getByText("72%")).toBeInTheDocument();
    expect(screen.getByText("5300.25")).toBeInTheDocument();
    expect(screen.getByText("5290.50")).toBeInTheDocument();
    expect(screen.getByText("5324.75")).toBeInTheDocument();
    // Planned R:R is derived only because all three levels are present.
    expect(screen.getByText("R:R 2.51R")).toBeInTheDocument();
  });

  it("shows levels as em-dashes (never inferred) when the payload omits them", async () => {
    mockRoute(() => ({
      available: true,
      decision_count: 1,
      last_run: { id: 1, symbol: "MES", action: "HOLD", confidence: 0.5 },
    }));

    render(<TradeRecommendationsCard />);

    expect(await screen.findByText("MES")).toBeInTheDocument();
    expect(screen.getByText("HOLD")).toBeInTheDocument();
    // Exactly the three level cells (entry/stop/target) are em-dashes — and
    // nothing is inferred to fill them in.
    expect(screen.getAllByText("—").length).toBe(3);
    expect(screen.getByText("R:R —")).toBeInTheDocument();
  });

  it("shows the empty state (not offline) when the pipeline has not run yet", async () => {
    mockRoute(() => ({ available: true, sdk_available: false, last_run: null, decision_count: 0 }));

    render(<TradeRecommendationsCard />);

    expect(await screen.findByText(/No recommendation yet/i)).toBeInTheDocument();
    expect(screen.queryByText(/Recommendations offline/i)).not.toBeInTheDocument();
  });
});
