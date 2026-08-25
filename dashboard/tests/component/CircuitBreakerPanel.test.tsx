// Tier-2 safety-action component test — Phase 9.2, P9-3.
//
// CircuitBreakerPanel is the at-a-glance safety-rail readout (daily-loss and
// drawdown gauges + kill-switch pill). This suite proves it renders correctly
// for both a tripped/halted engine state and a normal/all-clear one, so a
// stale or miscoded status banner can't silently under-represent real risk.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { CircuitBreakerPanel } from "@/components/CircuitBreakerPanel";
import useSWR from "swr";
import type { CircuitBreakerState } from "@/lib/api";

vi.mock("swr", () => ({
  default: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  // CircuitBreakerPanel's fetcher wraps fetchEngine, but useSWR itself is
  // mocked below so this real call site is never invoked — stub kept only so
  // the module import resolves.
  fetchEngine: vi.fn(),
}));

const mockedUseSWR = vi.mocked(useSWR);

function mockSwrState(data?: CircuitBreakerState, extra?: { error?: unknown; isLoading?: boolean }) {
  mockedUseSWR.mockReturnValue({
    data,
    error: extra?.error,
    isLoading: extra?.isLoading ?? false,
    mutate: vi.fn(),
    isValidating: false,
  } as unknown as ReturnType<typeof useSWR>);
}

describe("CircuitBreakerPanel — tripped vs untripped rendering", () => {
  beforeEach(() => {
    mockedUseSWR.mockReset();
  });

  it("renders the untripped/all-clear state with NORMAL gauges", () => {
    mockSwrState({
      daily_pnl: -50,
      daily_limit: -500,
      drawdown_pct: -0.01,
      drawdown_limit_pct: -0.2,
      kill_switch_active: false,
      all_clear: true,
    });

    render(<CircuitBreakerPanel />);

    expect(screen.getByText("All Clear")).toBeInTheDocument();
    expect(screen.getByText("Kill Switch: Inactive")).toBeInTheDocument();
    const normals = screen.getAllByText("NORMAL");
    expect(normals).toHaveLength(2);
    expect(screen.queryByText("TRIPPED")).not.toBeInTheDocument();
  });

  it("renders the tripped/halted state with TRIPPED gauges and the HALTED banner", () => {
    mockSwrState({
      daily_pnl: -520,
      daily_limit: -500,
      drawdown_pct: -0.25,
      drawdown_limit_pct: -0.2,
      kill_switch_active: true,
      all_clear: false,
    });

    render(<CircuitBreakerPanel />);

    expect(screen.getByText("HALTED")).toBeInTheDocument();
    expect(screen.getByText("Kill Switch: Active")).toBeInTheDocument();
    const tripped = screen.getAllByText("TRIPPED");
    // Both the daily-P&L gauge (520/500) and drawdown gauge (0.25/0.20) are
    // over their limit in this fixture.
    expect(tripped).toHaveLength(2);
    expect(screen.queryByText("NORMAL")).not.toBeInTheDocument();
  });

  it("renders an explicit unavailable state rather than a blank/zeroed panel when the engine has no data", () => {
    mockSwrState(undefined, { error: new Error("fetch failed") });

    render(<CircuitBreakerPanel />);

    expect(screen.getByText("Circuit breaker data unavailable")).toBeInTheDocument();
  });
});
