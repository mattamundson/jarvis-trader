// Tier 1 (honesty/provenance) component tests — Phase 9.2, P9-2.
//
// `StalenessIndicator` (components/ui/staleness-indicator.tsx) is the
// general-purpose freshness badge every widget reuses instead of rolling its
// own "Last checked HH:MM:SS" text. These tests pin the boundary behavior
// between its three age buckets (Live / Delayed / Stale) at the exact
// `freshMs`/`staleMs` thresholds, plus the no-data fallback.
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { StalenessIndicator } from "@/components/ui/staleness-indicator";

const FRESH_MS = 60_000;
const STALE_MS = 300_000;
// Comfortably inside/outside each boundary so real test-execution latency
// (a few ms) can never flip which side of the threshold we land on.
const MARGIN_MS = 2_000;

describe("StalenessIndicator", () => {
  it("renders 'No data' when lastUpdated is null", () => {
    render(<StalenessIndicator lastUpdated={null} />);
    expect(screen.getByText(/No data/i)).toBeInTheDocument();
  });

  it("renders 'No data' when lastUpdated is undefined", () => {
    render(<StalenessIndicator lastUpdated={undefined} />);
    expect(screen.getByText(/No data/i)).toBeInTheDocument();
  });

  it("renders 'No data' when lastUpdated is an unparseable value", () => {
    render(<StalenessIndicator lastUpdated="not-a-date" />);
    expect(screen.getByText(/No data/i)).toBeInTheDocument();
  });

  it("renders Live just under the fresh threshold", () => {
    const lastUpdated = new Date(Date.now() - (FRESH_MS - MARGIN_MS));
    render(
      <StalenessIndicator
        lastUpdated={lastUpdated}
        freshMs={FRESH_MS}
        staleMs={STALE_MS}
      />,
    );
    expect(screen.getByText(/^Live/)).toBeInTheDocument();
  });

  it("renders Delayed just over the fresh threshold", () => {
    const lastUpdated = new Date(Date.now() - (FRESH_MS + MARGIN_MS));
    render(
      <StalenessIndicator
        lastUpdated={lastUpdated}
        freshMs={FRESH_MS}
        staleMs={STALE_MS}
      />,
    );
    expect(screen.getByText(/Delayed/)).toBeInTheDocument();
  });

  it("renders Delayed just under the stale threshold", () => {
    const lastUpdated = new Date(Date.now() - (STALE_MS - MARGIN_MS));
    render(
      <StalenessIndicator
        lastUpdated={lastUpdated}
        freshMs={FRESH_MS}
        staleMs={STALE_MS}
      />,
    );
    expect(screen.getByText(/Delayed/)).toBeInTheDocument();
  });

  it("renders Stale at/over the stale threshold", () => {
    const lastUpdated = new Date(Date.now() - (STALE_MS + MARGIN_MS));
    render(
      <StalenessIndicator
        lastUpdated={lastUpdated}
        freshMs={FRESH_MS}
        staleMs={STALE_MS}
      />,
    );
    expect(screen.getByText(/Stale/)).toBeInTheDocument();
  });
});
