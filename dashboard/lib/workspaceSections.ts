// Shared contract for "summary-first" workspace pages (/validation, /performance).
// A workspace page shows a lightweight default view (`summary`) plus a small set
// of named, lazily-mounted drill-down sections selected via `?section=<id>`.
// See docs/superpowers/specs/2026-08-13-dashboard-hardening-design.md section 3.

import type { ComponentType } from "react";

export const WORKSPACE_DEFAULT_SECTION_ID = "summary";

export interface WorkspaceSectionDef {
  /** Stable, URL-safe identifier. First entry must be WORKSPACE_DEFAULT_SECTION_ID. */
  id: string;
  /** Short label for nav tabs / links. */
  label: string;
  /** One-line description shown on the summary card that links into this section. */
  summary: string;
  /** Lazy loader passed to next/dynamic() — the section's heavy content never
   * ships or mounts unless this section is selected. */
  loadComponent: () => Promise<{ default: ComponentType }>;
}

/**
 * Resolves a raw `?section=` query value against a workspace's known sections.
 * Absent or unrecognized values fall back to the default summary section --
 * never crash, never silently render nothing.
 */
export function resolveWorkspaceSection(
  sections: readonly Pick<WorkspaceSectionDef, "id">[],
  sectionId: string | null | undefined,
): string {
  if (sectionId && sections.some((section) => section.id === sectionId)) {
    return sectionId;
  }
  return WORKSPACE_DEFAULT_SECTION_ID;
}
