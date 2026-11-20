import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import JournalPage from "@/app/journal/page";

vi.mock("swr", () => ({
  default: vi.fn(() => ({
    data: null,
    error: null,
    isLoading: true,
    mutate: vi.fn(),
  })),
}));

describe("JournalPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders loading state", () => {
    render(<JournalPage />);
    expect(screen.getByText(/Loading journal/i)).toBeInTheDocument();
  });

  it("renders page title", () => {
    render(<JournalPage />);
    expect(screen.getByText(/Paper Trading Journal/i)).toBeInTheDocument();
  });

  it("shows progress cards with correct states", () => {
    render(<JournalPage />);
    expect(screen.getByText(/Scored Setups/i)).toBeInTheDocument();
    expect(screen.getByText(/Average R/i)).toBeInTheDocument();
    expect(screen.getByText(/Clean Sessions/i)).toBeInTheDocument();
    expect(screen.getByText(/Data Source/i)).toBeInTheDocument();
  });

  it("shows n/a for clean sessions", () => {
    render(<JournalPage />);
    expect(screen.getByText(/n\/a/i)).toBeInTheDocument();
    expect(screen.getByText(/Session-level stat/i)).toBeInTheDocument();
  });
  
  it("shows data source note", () => {
    render(<JournalPage />);
    expect(screen.getByText(/R-multiples require stop loss data/i)).toBeInTheDocument();
  });
});
