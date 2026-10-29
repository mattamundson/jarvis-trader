import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import useSWR from "swr";
import JournalPage from "@/app/journal/page";

vi.mock("swr", () => ({
  default: vi.fn(),
}));

const mockedSWR = vi.mocked(useSWR);

const proofRecord = {
  available: true,
  source: "proof-record.json",
  generated_ct: "2026-10-29 10:53 CT",
  r_basis: "1R = entry to actual stop",
  goal_setups: 20,
  counted: 2,
  wins: 1,
  losses: 1,
  avg_r: 0.75,
  total_r: 1.5,
  error: null,
  setups: [
    {
      date: "2026-09-23",
      setup: "8am fade",
      side: "short",
      trigger: "lose ONL 7818.75",
      entry_time: null,
      entry: 7818.75,
      stop: 7837,
      target: 7781,
      exit_time: null,
      exit: 7781,
      exit_reason: "target",
      r_multiple: 2.5,
      rule_breaks: 0,
      status: "legacy",
      counted: true,
    },
    {
      date: "2026-10-28",
      setup: "8am bounce",
      side: "long",
      trigger: "reclaim 7755",
      entry_time: "08:40",
      entry: 7755,
      stop: 7745,
      target: 7775,
      exit_time: "08:50",
      exit: 7745,
      exit_reason: "stop",
      r_multiple: -1,
      rule_breaks: 1,
      status: null,
      counted: true,
    },
  ],
};

function setSWR(value: Record<string, unknown>) {
  mockedSWR.mockReturnValue({
    mutate: vi.fn(),
    isValidating: false,
    ...value,
  } as never);
}

describe("JournalPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders loading state", () => {
    setSWR({ data: undefined, error: undefined, isLoading: true });
    render(<JournalPage />);
    expect(screen.getByText(/Loading journal/i)).toBeInTheDocument();
  });

  it("renders page title with 'Trade Journal' heading", () => {
    setSWR({ data: undefined, error: undefined, isLoading: true });
    render(<JournalPage />);
    expect(screen.getByText(/Trade Journal/i)).toBeInTheDocument();
  });

  it("renders the proof record from /trades/scored-setups", () => {
    setSWR({ data: proofRecord, error: undefined, isLoading: false });
    render(<JournalPage />);
    expect(screen.getAllByText(/Scored Setups/i).length).toBeGreaterThan(0);
    expect(screen.getByText("+0.75R")).toBeInTheDocument();
    expect(screen.getByText("+2.50R")).toBeInTheDocument();
    expect(screen.getByText("-1.00R")).toBeInTheDocument();
    expect(screen.getByText(/1 rule break/)).toBeInTheDocument();
    expect(screen.getByText(/as of 2026-10-29 10:53 CT/)).toBeInTheDocument();
    expect(screen.getByText(/Session-level stat/i)).toBeInTheDocument();
  });

  it("shows unavailable note when the proof record can't be read", () => {
    setSWR({
      data: {
        ...proofRecord,
        available: false,
        counted: 0,
        avg_r: null,
        setups: [],
        error: "proof record not found",
      },
      error: undefined,
      isLoading: false,
    });
    render(<JournalPage />);
    expect(
      screen.getByText(/Proof record unavailable: proof record not found/),
    ).toBeInTheDocument();
    expect(screen.getByText(/No scored setups yet/i)).toBeInTheDocument();
  });

  it("renders Trade Journal heading when engine is down", () => {
    setSWR({
      data: null,
      error: new Error("Engine unavailable"),
      isLoading: false,
    });

    render(<JournalPage />);
    expect(screen.getByText(/Trade Journal/i)).toBeInTheDocument();
    expect(screen.getByText(/Error loading journal/i)).toBeInTheDocument();
  });

  it("handles empty data response from engine", () => {
    setSWR({
      data: {
        available: false,
        source: "proof-record.json",
        error: "proof record not found",
        goal_setups: 20,
        counted: 0,
        wins: 0,
        losses: 0,
        avg_r: null,
        total_r: null,
        setups: [],
        file_mtime: null,
        age_seconds: null,
      },
      error: null,
      isLoading: false,
    });

    render(<JournalPage />);
    expect(screen.getByText(/Trade Journal/i)).toBeInTheDocument();
    expect(screen.getByText(/Proof record unavailable/i)).toBeInTheDocument();
  });
});
