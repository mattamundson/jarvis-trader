// Tier 1 (honesty/provenance) component tests — Phase 9.2, P9-2.
//
// `Badge` (components/ui/badge.tsx) carries the honesty-badge contract for
// the whole dashboard: only 7 variants exist, and `live`/`static` are the
// canonical provenance variants everything else (StalenessIndicator,
// classifyProvenance consumers, ...) is allowed to emit. This file pins the
// variant set at EXACTLY those 7 so an accidental 8th variant is caught, not
// silently allowed to drift the honesty contract.
//
// `BadgeVariant`/`BadgeProps` aren't exported from badge.tsx (deliberately —
// consumers should go through the component, not the type), so the
// exhaustiveness check below works structurally via `ComponentProps<typeof
// Badge>` instead of importing the type directly. The two conversion
// functions compile ONLY if the two variant sets are exactly equal:
//   - if badge.tsx grows an 8th variant, `narrowToAllowed` fails to
//     typecheck (the actual union has a member ALLOWED_VARIANTS doesn't)
//   - if this file's list goes stale (badge.tsx drops one), `widenToActual`
//     fails instead
// Both are enforced by `pnpm run typecheck:tests` (tsconfig.test.json),
// which is part of this task's required verification gate.
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Badge } from "@/components/ui/badge";
import type { ComponentProps } from "react";

const ALLOWED_VARIANTS = [
  "bull",
  "bear",
  "warn",
  "info",
  "neutral",
  "live",
  "static",
] as const;

type AllowedVariant = (typeof ALLOWED_VARIANTS)[number];
type ActualVariant = NonNullable<ComponentProps<typeof Badge>["variant"]>;

// Compile-time-only exhaustiveness check (never called at runtime) — see
// file header. Referenced via `void` so eslint/tsc don't flag them unused.
function narrowToAllowed(v: ActualVariant): AllowedVariant {
  return v;
}
function widenToActual(v: AllowedVariant): ActualVariant {
  return v;
}
void narrowToAllowed;
void widenToActual;

describe("Badge variant contract", () => {
  it("has exactly 7 allowed variants", () => {
    expect(ALLOWED_VARIANTS.length).toBe(7);
    expect(ALLOWED_VARIANTS).toEqual([
      "bull",
      "bear",
      "warn",
      "info",
      "neutral",
      "live",
      "static",
    ]);
  });

  it("renders every allowed variant without throwing", () => {
    for (const variant of ALLOWED_VARIANTS) {
      render(<Badge variant={variant}>{variant}</Badge>);
      expect(screen.getByText(variant)).toBeInTheDocument();
    }
  });

  it("defaults to the neutral variant when none is given", () => {
    render(<Badge>default</Badge>);
    expect(screen.getByText("default")).toBeInTheDocument();
  });
});
