"use client";

// Validation workspace — "audit" (export data + pipeline run history)
// section. Extracted verbatim from the former app/validation/page.tsx
// Sections H and F (PRB dashboard-hardening Task 3) — no calculation, label,
// or error-handling behavior changed, only relocated.

import { PipelineRunHistory } from "@/components/PipelineRunHistory";
import { ExportDataWidget } from "@/components/ExportDataWidget";
import { WidgetErrorBoundary } from "@/components/WidgetErrorBoundary";
import { SectionLabel } from "@/components/validation/shared";

export default function AuditSection() {
  return (
    <div className="space-y-6">
      {/* Section F: Pipeline Run History */}
      <section>
        <SectionLabel>F — Pipeline Run History</SectionLabel>
        <PipelineRunHistory />
      </section>

      {/* Section H: Export Data */}
      <section>
        <SectionLabel>H — Export Data</SectionLabel>
        <WidgetErrorBoundary name="Export Data">
          <ExportDataWidget />
        </WidgetErrorBoundary>
      </section>
    </div>
  );
}
