"use client";

// Validation workspace — "wfe" (walk-forward efficiency monitor) section.
// Extracted verbatim from the former app/validation/page.tsx Section K
// (PRB dashboard-hardening Task 3) — no calculation, label, or error-handling
// behavior changed, only relocated.

import { WFEMonitorWidget } from "@/components/WFEMonitorWidget";
import { WidgetErrorBoundary } from "@/components/WidgetErrorBoundary";
import { SectionLabel } from "@/components/validation/shared";

export default function WfeSection() {
  return (
    <section>
      <SectionLabel>K — Walk-Forward Efficiency Monitor</SectionLabel>
      <WidgetErrorBoundary name="WFE Monitor">
        <WFEMonitorWidget />
      </WidgetErrorBoundary>
    </section>
  );
}
