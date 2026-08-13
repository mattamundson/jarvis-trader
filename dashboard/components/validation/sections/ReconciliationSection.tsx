"use client";

// Validation workspace — "reconciliation" (broker position reconciliation)
// section. Extracted verbatim from the former app/validation/page.tsx
// Section I (PRB dashboard-hardening Task 3) — no calculation, label, or
// error-handling behavior changed, only relocated.

import { ReconciliationWidget } from "@/components/ReconciliationWidget";
import { WidgetErrorBoundary } from "@/components/WidgetErrorBoundary";
import { SectionLabel } from "@/components/validation/shared";

export default function ReconciliationSection() {
  return (
    <section>
      <SectionLabel>I — Position Reconciliation</SectionLabel>
      <WidgetErrorBoundary name="Reconciliation">
        <ReconciliationWidget />
      </WidgetErrorBoundary>
    </section>
  );
}
