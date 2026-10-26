import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

vi.mock("@/lib/api", () => ({
  fetchEngine: vi.fn(),
}));

import { fetchEngine } from "@/lib/api";
import { OptionsChainCard } from "@/components/OptionsChainCard";

const mockedFetch = vi.mocked(fetchEngine);

describe("OptionsChainCard", () => {
  beforeEach(() => {
    mockedFetch.mockReset();
  });

  it("shows No contracts after a successful empty chain", async () => {
    mockedFetch.mockResolvedValue({
      symbol: "SPY",
      underlying_price: 765.32,
      calls: [],
      puts: [],
    });

    render(<OptionsChainCard />);

    expect(screen.getByText("Loading chain…")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText("No contracts")).toBeInTheDocument();
    });
    expect(screen.queryByText("Loading chain…")).not.toBeInTheDocument();
  });
});
