// Tier-2 safety-action component test — Phase 9.2, P9-3.
//
// KillSwitchPanel controls the single most consequential control on this
// dashboard: halting/resuming live trading. Its rendered state is fully derived
// from the server-backed `data` prop, and the parent refresh (`mutate`) only
// fires after the engine POST resolves successfully. A failed request must never
// make the UI look halted or resumed.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { KillSwitchPanel } from "@/components/safety/SafetyPanels";
import {
  activateKillSwitch,
  deactivateKillSwitch,
  type KillSwitchStatus,
} from "@/lib/settings-api";

vi.mock("@/lib/settings-api", () => ({
  activateKillSwitch: vi.fn(),
  deactivateKillSwitch: vi.fn(),
}));

const mockedActivateKillSwitch = vi.mocked(activateKillSwitch);
const mockedDeactivateKillSwitch = vi.mocked(deactivateKillSwitch);

function killSwitchStatus(
  active: boolean,
  reason: string | null = null
): KillSwitchStatus {
  return {
    kill_switch_active: active,
    kill_switch_reason: reason,
    live_trading_enabled: false,
    require_human_approval: true,
    daily_pnl: 0,
    equity_peak: 10000,
    current_equity: 10000,
    drawdown_pct: 0,
    orders_last_minute: 0,
  };
}

describe("KillSwitchPanel - safety-critical state derivation", () => {
  beforeEach(() => {
    mockedActivateKillSwitch.mockReset();
    mockedDeactivateKillSwitch.mockReset();
  });

  it("does NOT mutate when the activate POST fails", async () => {
    mockedActivateKillSwitch.mockRejectedValueOnce(new Error("engine returned 500"));
    const mutate = vi.fn();
    render(<KillSwitchPanel data={killSwitchStatus(false)} mutate={mutate} />);

    fireEvent.click(screen.getByRole("button", { name: /activate kill switch/i }));
    fireEvent.change(screen.getByPlaceholderText(/market volatility/i), {
      target: { value: "manual_dashboard" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Activate" }));

    await waitFor(() =>
      expect(mockedActivateKillSwitch).toHaveBeenCalledWith("manual_dashboard")
    );
    await waitFor(() =>
      expect(screen.getByText("Failed to activate kill switch.")).toBeInTheDocument()
    );

    expect(mutate).not.toHaveBeenCalled();
    expect(screen.getByText("Trading Active")).toBeInTheDocument();
  });

  it("mutates exactly once when the activate POST succeeds", async () => {
    mockedActivateKillSwitch.mockResolvedValueOnce({
      status: "activated",
      reason: "manual_dashboard",
    });
    const mutate = vi.fn();
    render(<KillSwitchPanel data={killSwitchStatus(false)} mutate={mutate} />);

    fireEvent.click(screen.getByRole("button", { name: /activate kill switch/i }));
    fireEvent.change(screen.getByPlaceholderText(/market volatility/i), {
      target: { value: "manual_dashboard" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Activate" }));

    await waitFor(() => expect(mutate).toHaveBeenCalledTimes(1));
  });

  it("does NOT mutate when the deactivate POST fails", async () => {
    mockedDeactivateKillSwitch.mockRejectedValueOnce(new Error("engine returned 500"));
    const mutate = vi.fn();
    render(
      <KillSwitchPanel
        data={killSwitchStatus(true, "manual_dashboard")}
        mutate={mutate}
      />
    );

    const deactivateBtn = screen.getByRole("button", {
      name: /deactivate kill switch and resume trading/i,
    });
    // First click only arms the confirmation state (no request sent yet).
    fireEvent.click(deactivateBtn);
    expect(mockedDeactivateKillSwitch).not.toHaveBeenCalled();
    // Second click actually sends the resume request.
    fireEvent.click(deactivateBtn);

    await waitFor(() =>
      expect(mockedDeactivateKillSwitch).toHaveBeenCalledTimes(1)
    );
    await waitFor(() =>
      expect(screen.getByText("Failed to deactivate kill switch.")).toBeInTheDocument()
    );

    expect(mutate).not.toHaveBeenCalled();
    expect(screen.getByText("KILL SWITCH ACTIVE")).toBeInTheDocument();
  });
});
