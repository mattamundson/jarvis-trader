// Smoke test proving the Vitest + RTL + jsdom harness actually RUNS (not just
// installs) — Phase 9.1, D11. Deliberately trivial: renders one real component
// and asserts on its text + honesty-badge styling contract. P9-2/9-3/9-4 build
// real widget coverage on top of this harness in a later wave.
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Badge } from "@/components/ui/badge";

describe("Badge (component-test harness smoke test)", () => {
  it("renders its children", () => {
    render(<Badge variant="bull">LIVE</Badge>);
    expect(screen.getByText("LIVE")).toBeInTheDocument();
  });

  it("applies the bull-variant styling classes", () => {
    render(<Badge variant="bull">LIVE</Badge>);
    const badge = screen.getByText("LIVE");
    expect(badge.className).toContain("text-bull");
  });

  it("applies the static (dashed) honesty-badge styling for placeholder data", () => {
    render(<Badge variant="static">STATIC</Badge>);
    const badge = screen.getByText("STATIC");
    expect(badge.className).toContain("border-dashed");
  });
});
