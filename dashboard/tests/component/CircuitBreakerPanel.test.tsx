// Tier-2 safety-action component test — Phase 9.2, P9-3.
//
// CircuitBreakerSummary is the live Settings safety-rail readout. This suite
// proves it renders correctly for tripped/halted, normal/all-clear, and
// unavailable states so the dashboard does not silently under-represent risk.
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { CircuitBreakerSummary } from "@/components/safety/SafetyPanels";
import type { CircuitBreakerFull } from "@/lib/settings-api";

function circuitBreaker(data: Partial<CircuitBreakerFull>): CircuitBreakerFull {
  return {
    daily_pnl: 0,
    daily_limit: -500,
    daily_pnl_pct: 0,
    daily_limit_pct: -0.05,
    daily_limit_breached: false,
    drawdown_pct: 0,
    drawdown_limit_pct: -0.2,
    drawdown_breached: false,
    kill_switch_active: false,
    kill_switch_reason: null,
    pnl_source: "memory",
    current_balance: 10000,
    starting_balance: 10000,
    orders_last_minute: 0,
    all_clear: true,
    ...data,
  };
}

describe("CircuitBreakerSummary - tripped vs untripped rendering", () => {
  it("renders the untripped/all-clear state", () => {
    render(
      <CircuitBreakerSummary
        data={circuitBreaker({
          daily_pnl: -50,
          drawdown_pct: -0.01,
        })}
      />
    );

    expect(screen.getByText("All Clear")).toBeInTheDocument();
    expect(screen.getByText("-$50.00")).toBeInTheDocument();
    expect(screen.getByText("1.00%")).toBeInTheDocument();
    expect(screen.queryByText("HALTED")).not.toBeInTheDocument();
  });

  it("renders the tripped/halted state with the HALTED banner", () => {
    render(
      <CircuitBreakerSummary
        data={circuitBreaker({
          daily_pnl: -50,
          daily_limit_breached: true,
          drawdown_pct: -0.25,
          drawdown_breached: true,
          kill_switch_active: true,
          kill_switch_reason: "manual_dashboard",
          all_clear: false,
        })}
      />
    );

    expect(screen.getByText("HALTED")).toBeInTheDocument();
    expect(screen.getByText("25.00%")).toBeInTheDocument();
    expect(screen.queryByText("All Clear")).not.toBeInTheDocument();
  });

  it("renders an explicit unavailable state rather than a blank panel when the engine has no data", () => {
    render(<CircuitBreakerSummary data={undefined} />);

    expect(screen.getByText("Circuit breaker data unavailable")).toBeInTheDocument();
  });
});
