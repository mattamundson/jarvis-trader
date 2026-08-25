// Tier 1 (honesty/provenance) component tests — Phase 9.2, P9-2.
//
// `ExploratoryBanner` (components/ExploratoryBanner.tsx) is the shared
// disclosure mounted on research surfaces (RL Lab, Kairos, Polymarket,
// Hidden Pivots, ...) so an unvalidated signal feed can never be mistaken
// for validated edge. Covers: the testid other pages/tests hook into, the
// default vs. caller-supplied disclosure text, and its accessible role.
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ExploratoryBanner } from "@/components/ExploratoryBanner";

describe("ExploratoryBanner", () => {
  it("renders its testid", () => {
    render(<ExploratoryBanner />);
    expect(screen.getByTestId("exploratory-banner")).toBeInTheDocument();
  });

  it("exposes an accessible 'note' role for assistive tech", () => {
    render(<ExploratoryBanner />);
    expect(screen.getByRole("note")).toBeInTheDocument();
  });

  it("renders the default disclosure text when no `what` prop is given", () => {
    render(<ExploratoryBanner />);
    expect(
      screen.getByText(/This surface shows research under investigation/i),
    ).toBeInTheDocument();
  });

  it("renders the caller-supplied `what` phrase instead of the default", () => {
    render(<ExploratoryBanner what="RL strategy discovery" />);
    expect(screen.getByText(/RL strategy discovery/i)).toBeInTheDocument();
    expect(
      screen.queryByText(/This surface shows research under investigation/i),
    ).not.toBeInTheDocument();
  });

  it("always renders the 'Exploratory — not validated' headline regardless of `what`", () => {
    render(<ExploratoryBanner what="anything" />);
    expect(screen.getByText(/Exploratory/)).toBeInTheDocument();
    expect(screen.getByText(/not validated/)).toBeInTheDocument();
  });
});
