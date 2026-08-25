// Tier 3 (P&L) component tests — Phase 9.2, P9-4.
//
// Covers two `honestTrades`-consuming widgets (`WeeklyStatsWidget`,
// `BestWorstTradesWidget`) to prove the honesty contract described in
// lib/honestTrades.ts is upheld at the render layer:
//   1. `dedupCaveat()` is rendered wherever an aggregate P&L figure appears,
//      so the operator can see "N real trades / M re-logged rows collapsed"
//      next to the number it qualifies.
//   2. When the honest record can't be computed (fetch error) or there is
//      genuinely no data for the window, the widget renders an EXPLICIT
//      unavailable message — never a bare "$0.00" that reads as a real
//      computed zero.
//
// Both widgets source data through the shared `useHonestTrades()` hook
// (lib/useHonestTrades.ts), so it is mocked here rather than hitting SWR/
// fetch — this isolates the render-layer honesty contract from network
// behavior, which is already covered by the existing node:test suite
// (tests/honestTradesUnavailable.node.test.ts, tests/scorecardHonestTradesHook.node.test.ts).
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  dedupCaveat,
  type HonestTrade,
  type HonestTradeSet,
} from "@/lib/honestTrades";

vi.mock("@/lib/useHonestTrades", () => ({
  useHonestTrades: vi.fn(),
}));

import { useHonestTrades } from "@/lib/useHonestTrades";
import { WeeklyStatsWidget } from "@/components/WeeklyStatsWidget";
import { BestWorstTradesWidget } from "@/components/BestWorstTradesWidget";

const mockedUseHonestTrades = vi.mocked(useHonestTrades);

// ── Fixtures ────────────────────────────────────────────────────────────────

function makeTrade(overrides: Partial<HonestTrade> = {}): HonestTrade {
  return {
    id: overrides.id ?? `trade-${Math.random()}`,
    symbol: "MES",
    direction: "LONG",
    action: "LONG",
    entry_time: new Date().toISOString(),
    exit_time: new Date().toISOString(),
    pnl: 100,
    pnl_usd: 100,
    grade: null,
    ...overrides,
  };
}

function makeHonestTradeSet(
  trades: HonestTrade[],
  overrides: Partial<HonestTradeSet> = {},
): HonestTradeSet {
  const wins = trades.filter((t) => t.pnl > 0).length;
  const losses = trades.filter((t) => t.pnl < 0).length;
  const relogged = overrides.relogged ?? 0;
  return {
    trades,
    net: trades.reduce((s, t) => s + t.pnl, 0),
    wins,
    losses,
    winRate: trades.length ? wins / trades.length : 0,
    profitFactor: null,
    grossWin: trades.filter((t) => t.pnl > 0).reduce((s, t) => s + t.pnl, 0),
    grossLoss: Math.abs(
      trades.filter((t) => t.pnl < 0).reduce((s, t) => s + t.pnl, 0),
    ),
    headline: "",
    rawRows: trades.length + relogged,
    relogged,
    caveats: [],
    ...overrides,
  };
}

/** No bare fabricated-zero string anywhere in the rendered widget. */
function assertNoBareZeroDollar(container: HTMLElement) {
  expect(container.textContent).not.toMatch(/\$0\.00/);
}

beforeEach(() => {
  mockedUseHonestTrades.mockReset();
});

// ── WeeklyStatsWidget ─────────────────────────────────────────────────────

describe("WeeklyStatsWidget (Tier 3 honesty contract)", () => {
  it("renders dedupCaveat() next to the weekly aggregate when trades are present", () => {
    const trades = [
      makeTrade({ id: "t1", pnl: 150 }),
      makeTrade({ id: "t2", pnl: -50 }),
    ];
    const set = makeHonestTradeSet(trades, { relogged: 3 });
    mockedUseHonestTrades.mockReturnValue({
      honest: set,
      error: undefined,
      isLoading: false,
      mutate: vi.fn(),
    } as ReturnType<typeof useHonestTrades>);

    render(<WeeklyStatsWidget />);

    expect(screen.getByText("Weekly Performance")).toBeInTheDocument();
    // The exact caveat string the lib produces must be visible verbatim.
    expect(screen.getByText(dedupCaveat(set), { exact: false })).toBeInTheDocument();
  });

  it("renders an explicit unavailable message on fetch error, never a bare $0.00", () => {
    mockedUseHonestTrades.mockReturnValue({
      honest: null,
      error: new Error("master-api unreachable"),
      isLoading: false,
      mutate: vi.fn(),
    } as ReturnType<typeof useHonestTrades>);

    const { container } = render(<WeeklyStatsWidget />);

    expect(screen.getByText("Unable to load weekly stats")).toBeInTheDocument();
    assertNoBareZeroDollar(container);
  });

  it("renders an explicit 'no trades' message when the window is empty, never a bare $0.00", () => {
    // Trades exist but all closed outside the trailing-7-day window, so
    // `deriveWeeklyStats` returns null — a real, non-error empty state.
    const staleTrade = makeTrade({
      id: "old",
      exit_time: new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString(),
    });
    const set = makeHonestTradeSet([staleTrade]);
    mockedUseHonestTrades.mockReturnValue({
      honest: set,
      error: undefined,
      isLoading: false,
      mutate: vi.fn(),
    } as ReturnType<typeof useHonestTrades>);

    const { container } = render(<WeeklyStatsWidget />);

    expect(screen.getByText("No trades in the last 7 days")).toBeInTheDocument();
    assertNoBareZeroDollar(container);
  });

  it("renders a loading state without fabricating any figure while the fetch is in flight", () => {
    mockedUseHonestTrades.mockReturnValue({
      honest: null,
      error: undefined,
      isLoading: true,
      mutate: vi.fn(),
    } as ReturnType<typeof useHonestTrades>);

    const { container } = render(<WeeklyStatsWidget />);

    expect(screen.getByText("Weekly Performance")).toBeInTheDocument();
    assertNoBareZeroDollar(container);
  });
});

// ── BestWorstTradesWidget ─────────────────────────────────────────────────

describe("BestWorstTradesWidget (Tier 3 honesty contract)", () => {
  it("renders dedupCaveat() next to the best/worst aggregate when trades are present", () => {
    const trades = [
      makeTrade({ id: "b1", symbol: "MES", pnl: 300 }),
      makeTrade({ id: "b2", symbol: "MNQ", pnl: 200 }),
      makeTrade({ id: "w1", symbol: "MGC", pnl: -120, action: "SHORT", direction: "SHORT" }),
    ];
    const set = makeHonestTradeSet(trades, { relogged: 2 });
    mockedUseHonestTrades.mockReturnValue({
      honest: set,
      error: undefined,
      isLoading: false,
      mutate: vi.fn(),
    } as ReturnType<typeof useHonestTrades>);

    render(<BestWorstTradesWidget />);

    expect(screen.getByRole("heading", { name: "Best & Worst Trades" })).toBeInTheDocument();
    expect(screen.getByText(dedupCaveat(set), { exact: false })).toBeInTheDocument();
  });

  it("renders an explicit error message on fetch failure, never a bare $0.00", () => {
    mockedUseHonestTrades.mockReturnValue({
      honest: null,
      error: new Error("engine unreachable"),
      isLoading: false,
      mutate: vi.fn(),
    } as ReturnType<typeof useHonestTrades>);

    const { container } = render(<BestWorstTradesWidget />);

    expect(screen.getByText(/^Error: engine unreachable$/)).toBeInTheDocument();
    assertNoBareZeroDollar(container);
  });

  it("renders an explicit 'need more history' message with fewer than 2 trades, never a bare $0.00", () => {
    const set = makeHonestTradeSet([makeTrade({ id: "only-one" })]);
    mockedUseHonestTrades.mockReturnValue({
      honest: set,
      error: undefined,
      isLoading: false,
      mutate: vi.fn(),
    } as ReturnType<typeof useHonestTrades>);

    const { container } = render(<BestWorstTradesWidget />);

    expect(screen.getByText("Need more trade history")).toBeInTheDocument();
    assertNoBareZeroDollar(container);
  });
});
