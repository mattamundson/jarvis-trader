// Tier-2 safety-action component test — Phase 9.2, P9-3.
//
// The pending-approvals screen is where a human signs off on a real trade.
// The risk math shown there (position size %, margin impact %) is computed
// against an account-value base that is EITHER the live engine equity OR,
// when the engine can't report it, a hardcoded ACCOUNT_VALUE_FALLBACK
// ($10,000, see app/trades/pending-approvals/page.tsx). This suite proves the
// fallback path always renders a visible non-live marker next to that figure
// — never silently as if it were the real account value — and that the
// confirm-action dialog itself carries through the correct row data end to
// end (approve -> postApprovePending with the right id).
//
// next/link is stubbed to a plain anchor (App Router link internals expect a
// router context this harness doesn't provide, and it is irrelevant to what
// this suite tests). ActionableBoardWidget is stubbed out for the same
// reason — it's a separate, unrelated live-status board on this page with
// its own SWR fetch.
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import PendingApprovalsPage from "@/app/trades/pending-approvals/page";
import { ToastProvider } from "@/lib/toast-context";
import {
  getPendingApprovals,
  postApprovePending,
  postRejectPending,
  fetchEngine,
  type PendingApproval,
} from "@/lib/api";

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={typeof href === "string" ? href : "#"}>{children}</a>
  ),
}));

vi.mock("@/components/ActionableBoardWidget", () => ({
  ActionableBoardWidget: () => null,
}));

vi.mock("@/lib/api", () => ({
  getPendingApprovals: vi.fn(),
  postApprovePending: vi.fn(),
  postRejectPending: vi.fn(),
  fetchEngine: vi.fn(),
}));

const mockedGetPendingApprovals = vi.mocked(getPendingApprovals);
const mockedPostApprovePending = vi.mocked(postApprovePending);
const mockedPostRejectPending = vi.mocked(postRejectPending);
const mockedFetchEngine = vi.mocked(fetchEngine);
void mockedPostRejectPending;

const ROW: PendingApproval = {
  id: 1,
  approval_id: "approval-123",
  symbol: "MES",
  action: "BUY",
  quantity: 2,
  entry_price: 5000,
  created_at: "2026-08-02T00:00:00Z",
  pipeline_snapshot: null,
  status: "pending",
  resolved_at: null,
  resolved_by: null,
  rejection_reason: null,
  paper_trade_id: null,
  ib_order_id: null,
};

function renderPage() {
  return render(
    <ToastProvider>
      <PendingApprovalsPage />
    </ToastProvider>
  );
}

describe("Pending-approvals — account-value honesty labeling", () => {
  beforeEach(() => {
    mockedGetPendingApprovals.mockReset().mockResolvedValue({ pending: [ROW], count: 1 });
    mockedPostApprovePending.mockReset();
    mockedFetchEngine.mockReset();
  });

  it("renders the ACCOUNT_VALUE_FALLBACK figure with a visible non-live marker when the engine can't report live equity", async () => {
    mockedFetchEngine.mockRejectedValue(new Error("safety status unavailable"));

    renderPage();

    // The risk-summary base line: "base $10,000 (default — engine offline)".
    // Restricted to the actual <p> leaf so ancestor elements (which share the
    // same substring in their full textContent) don't produce ambiguous
    // matches.
    const baseLine = await screen.findByText((_, el) => {
      if (!el || el.tagName !== "P") return false;
      const t = el.textContent ?? "";
      return t.includes("base $10,000") && t.includes("(default — engine offline)");
    });
    expect(baseLine).toBeInTheDocument();
    expect(baseLine.textContent).not.toContain("(live)");
  });

  it("renders the live equity figure, unmarked as fallback, once the engine reports real portfolio equity", async () => {
    mockedFetchEngine.mockResolvedValue({
      kill_switch_active: false,
      kill_switch_reason: null,
      live_trading_enabled: true,
      require_human_approval: true,
      daily_pnl: 0,
      max_daily_loss: -500,
      portfolio_equity: 25000,
      peak_equity: 25000,
      current_drawdown: 0,
      orders_today: 0,
    });

    renderPage();

    const baseLine = await screen.findByText((_, el) => {
      if (!el || el.tagName !== "P") return false;
      const t = el.textContent ?? "";
      return t.includes("base $25,000") && t.includes("(live)");
    });
    expect(baseLine).toBeInTheDocument();
    expect(baseLine.textContent).not.toContain("engine offline");
  });

  it("the margin-impact figure carries its own Static/approximation badge regardless of live vs fallback account value", async () => {
    mockedFetchEngine.mockRejectedValue(new Error("safety status unavailable"));

    renderPage();

    expect(await screen.findByText("Static")).toBeInTheDocument();
  });

  it("confirming an approval passes the correct approval id through to postApprovePending", async () => {
    mockedFetchEngine.mockRejectedValue(new Error("safety status unavailable"));
    mockedPostApprovePending.mockResolvedValue({
      status: "approved",
      approval_id: ROW.approval_id,
      symbol: ROW.symbol,
      action: ROW.action,
      quantity: ROW.quantity,
      entry_price: ROW.entry_price ?? undefined,
      paper_trade_id: "trade-abc",
    });

    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /^approve$/i }));

    // The confirm dialog renders the row's real data, not placeholder text.
    // "MES" appears both in the row header and inside the dialog, so scope
    // the lookup to the dialog card itself.
    const dialogHeading = await screen.findByText("Approve Trade?");
    const dialogCard = dialogHeading.closest(".max-w-sm");
    expect(dialogCard).not.toBeNull();
    expect(within(dialogCard as HTMLElement).getByText("MES")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /confirm approval/i }));

    await waitFor(() =>
      expect(mockedPostApprovePending).toHaveBeenCalledWith(ROW.approval_id, undefined)
    );
  });
});
