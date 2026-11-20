// Tier-2 safety-action component test — Phase 9.2, P9-3.
//
// KillSwitch controls the single most consequential control on this dashboard:
// halting/resuming live trading. Its rendered state is fully derived from the
// `isActive` prop, which the PARENT only flips after `onToggle()` is invoked —
// and `onToggle()` is only called after the engine POST resolves successfully
// (see components/KillSwitch.tsx handleActivate/handleDeactivate). This suite
// proves that contract holds: a failed/rejected POST must never trigger
// `onToggle`, because on a live trading dashboard a halt request that silently
// "looks like it worked" is a lethal lie.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { KillSwitch } from "@/components/KillSwitch";
import { postEngine } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  postEngine: vi.fn(),
}));

const mockedPostEngine = vi.mocked(postEngine);

describe("KillSwitch — safety-critical state derivation", () => {
  beforeEach(() => {
    mockedPostEngine.mockReset();
  });

  it("does NOT call onToggle when the activate (halt) POST fails — state must never optimistically flip to halted", async () => {
    mockedPostEngine.mockRejectedValueOnce(new Error("engine returned 500"));
    const onToggle = vi.fn();
    render(<KillSwitch isActive={false} onToggle={onToggle} />);

    fireEvent.click(screen.getByRole("button", { name: /emergency stop/i }));
    fireEvent.change(screen.getByPlaceholderText("Type here..."), {
      target: { value: "CONFIRM KILL" },
    });
    fireEvent.click(screen.getByRole("button", { name: "HALT SYSTEM" }));

    await waitFor(() =>
      expect(mockedPostEngine).toHaveBeenCalledWith("/safety/kill-switch/activate", {
        reason: "manual_dashboard",
      })
    );
    await waitFor(() =>
      expect(screen.getByText("Failed to activate kill switch")).toBeInTheDocument()
    );

    // The load-bearing assertion: a failed request never told the parent to
    // treat trading as halted.
    expect(onToggle).not.toHaveBeenCalled();
    // And the component itself never renders a halted UI on its own — the
    // "Trading Active" header (driven purely by the still-unchanged isActive
    // prop) is still present.
    expect(screen.getByText("Trading Active")).toBeInTheDocument();
  });

  it("DOES call onToggle exactly once when the activate POST succeeds (contrast case)", async () => {
    mockedPostEngine.mockResolvedValueOnce({});
    const onToggle = vi.fn();
    render(<KillSwitch isActive={false} onToggle={onToggle} />);

    fireEvent.click(screen.getByRole("button", { name: /emergency stop/i }));
    fireEvent.change(screen.getByPlaceholderText("Type here..."), {
      target: { value: "CONFIRM KILL" },
    });
    fireEvent.click(screen.getByRole("button", { name: "HALT SYSTEM" }));

    await waitFor(() => expect(onToggle).toHaveBeenCalledTimes(1));
  });

  it("does NOT call onToggle when the deactivate (resume trading) POST fails — must never silently resume", async () => {
    mockedPostEngine.mockRejectedValueOnce(new Error("engine returned 500"));
    const onToggle = vi.fn();
    render(<KillSwitch isActive={true} reason="manual_dashboard" onToggle={onToggle} />);

    const deactivateBtn = screen.getByRole("button", {
      name: /deactivate kill switch and resume trading/i,
    });
    // First click only arms the confirmation state (no request sent yet).
    fireEvent.click(deactivateBtn);
    expect(mockedPostEngine).not.toHaveBeenCalled();
    // Second click actually sends the resume request.
    fireEvent.click(deactivateBtn);

    await waitFor(() =>
      expect(mockedPostEngine).toHaveBeenCalledWith("/safety/kill-switch/deactivate")
    );
    await waitFor(() =>
      expect(screen.getByText("Failed to deactivate kill switch")).toBeInTheDocument()
    );

    expect(onToggle).not.toHaveBeenCalled();
    // Still shows the halted UI — trading was never actually resumed.
    expect(screen.getByText("KILL SWITCH ACTIVE")).toBeInTheDocument();
  });
});
