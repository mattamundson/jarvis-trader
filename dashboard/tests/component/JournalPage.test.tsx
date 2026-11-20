// JournalPage (app/journal/page.tsx) sources the trade journal through SWR →
// fetchTradeJournal. Both are mocked deterministically here: SWR returns a
// controllable state object (no real network, no timers) and the API module is
// stubbed so no fetch can ever escape the test. Assertions target the page's
// current rendered contract (loading, error, loaded summary cards, closed
// setup rows, empty state) using the actual current output — the old suite
// asserted labels from the pre-rewrite page while pinning isLoading: true,
// so it only ever saw the spinner.
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import type { TradeJournalEntry } from "@/lib/api";
import JournalPage from "@/app/journal/page";

const h = vi.hoisted(() => ({
  swr: {
    data: undefined as unknown,
    error: undefined as unknown,
    isLoading: true,
  },
}));

vi.mock("swr", () => ({
  default: vi.fn(() => h.swr),
}));

vi.mock("@/lib/api", () => ({
  fetchTradeJournal: vi.fn(),
}));

function entry(partial: Partial<TradeJournalEntry>): TradeJournalEntry {
  return {
    id: 1,
    trade_id: "t-1",
    symbol: "ES",
    side: "long",
    quantity: 1,
    entry_price: 5000,
    exit_price: 5010,
    entry_time: "2026-01-02T14:30:00Z",
    exit_time: "2026-01-02T15:00:00Z",
    pnl: 250,
    status: "closed",
    strategy_params: null,
    notes: null,
    regime: null,
    structure_position: null,
    bias: "long",
    composite_score: null,
    stc_contrib: null,
    orb_contrib: null,
    vwap_contrib: null,
    regime_tier: null,
    deciding_stage: null,
    bull_score: null,
    bear_score: null,
    debate_confidence: null,
    ...partial,
  };
}

function mockSwr(opts: { data?: TradeJournalEntry[]; error?: unknown; isLoading?: boolean }) {
  h.swr = {
    data: opts.data,
    error: opts.error,
    isLoading: opts.isLoading ?? false,
  };
}

describe("JournalPage", () => {
  it("renders the loading state while the journal API is in flight", () => {
    mockSwr({ isLoading: true });
    render(<JournalPage />);
    expect(screen.getByText(/Loading journal/i)).toBeInTheDocument();
  });

  it("renders an explicit error state when the journal API fails", () => {
    mockSwr({ error: "engine down" });
    render(<JournalPage />);
    expect(screen.getByText(/Error loading journal/i)).toBeInTheDocument();
    expect(screen.getByText(/engine down/)).toBeInTheDocument();
  });

  it("renders the progress summary cards with honest zero-state values", () => {
    mockSwr({ data: [] });
    render(<JournalPage />);
    expect(screen.getByText(/Paper Trading Journal/i)).toBeInTheDocument();
    expect(screen.getByText("Scored Setups")).toBeInTheDocument();
    expect(screen.getByText(/Average R/i)).toBeInTheDocument();
    expect(screen.getByText(/Clean Sessions/i)).toBeInTheDocument();
    expect(screen.getByText(/Data Source/i)).toBeInTheDocument();
    // Average R (no valid R yet) and Clean Sessions both render "n/a".
    expect(screen.getAllByText("n/a")).toHaveLength(2);
  });

  it("renders the session-level and data-source honesty notes", () => {
    mockSwr({ data: [] });
    render(<JournalPage />);
    expect(screen.getByText(/Session-level stat \(not available\)/i)).toBeInTheDocument();
    expect(screen.getByText(/R-multiples require stop loss data/i)).toBeInTheDocument();
  });

  it("renders closed setups from the mocked journal API", () => {
    mockSwr({
      data: [
        entry({ symbol: "ES", strategy_params: JSON.stringify({ setup: "ORB breakout" }) }),
        entry({ symbol: "NQ", side: "short", pnl: -120, id: 2, trade_id: "t-2" }),
      ],
    });
    render(<JournalPage />);
    // Header card title + table title both present when rows exist.
    expect(screen.getAllByText("Scored Setups")).toHaveLength(2);
    expect(screen.getByText("ES")).toBeInTheDocument();
    expect(screen.getByText("NQ")).toBeInTheDocument();
    expect(screen.getByText("ORB breakout")).toBeInTheDocument();
    // R-multiples are not derivable from current records — honest "R n/a".
    expect(screen.getAllByText("R n/a")).toHaveLength(2);
  });

  it("renders the empty state when the journal has no closed setups", () => {
    mockSwr({ data: [] });
    render(<JournalPage />);
    expect(screen.getByText(/No scored setups yet/i)).toBeInTheDocument();
    expect(screen.getByText(/Closed trades with completed exits will appear here/i)).toBeInTheDocument();
  });
});
