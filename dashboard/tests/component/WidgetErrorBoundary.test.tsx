// WidgetErrorBoundary containment test — Phase 9.2 (Tier 3), P9-4.
//
// WidgetErrorBoundary's stated purpose (components/WidgetErrorBoundary.tsx):
// "Wrapping an individual widget in this boundary contains the failure to
// that one card — the rest of the dashboard keeps updating." That claim was
// previously unproven by any test. This file renders a multi-widget layout
// (mirroring how app/paper/page.tsx etc. mount several widgets, each in its
// own boundary instance), forces ONE child to throw during render, and
// asserts the sibling widget in its own boundary is unaffected.
import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { WidgetErrorBoundary } from "@/components/WidgetErrorBoundary";

/** Deliberately throws during render, to simulate a malformed-payload widget crash. */
function ThrowingWidget(): never {
  throw new Error("simulated malformed payload");
}

function HealthyWidget() {
  return <div data-testid="healthy-widget">Account P&amp;L: +$412.50</div>;
}

function AnotherHealthyWidget() {
  return <div data-testid="another-healthy-widget">Win Rate: 61%</div>;
}

describe("WidgetErrorBoundary (multi-widget containment)", () => {
  // React logs the caught error to console.error (both its own dev warning
  // and this component's own componentDidCatch log) — expected noise for
  // this test, not a real failure. Silence it locally, restore after.
  const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

  afterEach(() => {
    consoleErrorSpy.mockClear();
  });

  it("contains a throwing child to its own boundary and does not blank sibling widgets", () => {
    render(
      <div>
        <WidgetErrorBoundary name="Healthy Widget A">
          <HealthyWidget />
        </WidgetErrorBoundary>
        <WidgetErrorBoundary name="Throwing Widget">
          <ThrowingWidget />
        </WidgetErrorBoundary>
        <WidgetErrorBoundary name="Healthy Widget B">
          <AnotherHealthyWidget />
        </WidgetErrorBoundary>
      </div>,
    );

    // The two healthy siblings rendered normally — the layout is NOT blank.
    expect(screen.getByTestId("healthy-widget")).toBeInTheDocument();
    expect(screen.getByText("Account P&L: +$412.50")).toBeInTheDocument();
    expect(screen.getByTestId("another-healthy-widget")).toBeInTheDocument();
    expect(screen.getByText("Win Rate: 61%")).toBeInTheDocument();

    // The failing widget's own boundary shows the contained fallback, naming it.
    expect(screen.getByText("Throwing Widget failed to render")).toBeInTheDocument();
    expect(screen.getByText("simulated malformed payload")).toBeInTheDocument();
  });

  it("renders the generic 'Widget failed to render' fallback when no name prop is given", () => {
    render(
      <WidgetErrorBoundary>
        <ThrowingWidget />
      </WidgetErrorBoundary>,
    );

    expect(screen.getByText("Widget failed to render")).toBeInTheDocument();
  });

  it("does not affect a sibling boundary even when both widgets share the same parent and re-render", () => {
    const { rerender } = render(
      <div>
        <WidgetErrorBoundary name="A">
          <HealthyWidget />
        </WidgetErrorBoundary>
        <WidgetErrorBoundary name="B">
          <HealthyWidget />
        </WidgetErrorBoundary>
      </div>,
    );

    expect(screen.getAllByTestId("healthy-widget")).toHaveLength(2);

    // Re-render with the second widget now throwing (e.g. its data went bad
    // on a later poll) — the first must remain intact and interactive.
    rerender(
      <div>
        <WidgetErrorBoundary name="A">
          <HealthyWidget />
        </WidgetErrorBoundary>
        <WidgetErrorBoundary name="B">
          <ThrowingWidget />
        </WidgetErrorBoundary>
      </div>,
    );

    expect(screen.getAllByTestId("healthy-widget")).toHaveLength(1);
    expect(screen.getByText("B failed to render")).toBeInTheDocument();
  });
});
