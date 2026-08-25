import { test, expect } from "@playwright/test";
import { ROUTES, type RouteSpec } from "./_routes";
import {
  installEngineMock,
  collectConsoleErrors,
  ERROR_BOUNDARY_TEXT,
} from "./_engineMock";

// Table-driven smoke across every route in the manifest.
//
// This is a FLOOR, not a replacement for the hand-written golden-path specs.
// Those assert domain behaviour (and one of them asserts the engine API key
// never reaches the browser, which nothing here would catch). This file asserts
// that no route in the manifest is silently broken -- which, before it existed,
// nothing checked at all.
//
// TITLE CONTRACT -- do not reformat casually.
// The drain ledger maps results back to routes by parsing test titles:
//   "<path> [<mode>] <what is being asserted>"
// The path must be a whitespace-delimited token starting with "/", and the mode
// must be the bracketed token. A title that breaks this still runs, but its
// result lands in the ledger as UNMAPPED rather than against its route.
//
// WHY retries STAY 0
// A flaky assertion on a trading dashboard is a real defect, not noise to be
// retried away. If something here is intermittent, that is the finding.

/** Concrete URL to visit: dynamic routes carry a sample path. */
function visitPath(r: RouteSpec): string {
  return r.samplePath ?? r.path;
}

/**
 * Navigate, and for redirect routes wait until the declared target is actually
 * reached before anything is asserted.
 *
 * Redirect routes resolve as CLIENT-side navigations that complete after
 * domcontentloaded. Asserting immediately races them, and the symptom is
 * misleading: the assertion reports against the pre-redirect page, so a
 * perfectly healthy destination looks broken. Every mode needs this, not just
 * the one that checks the URL.
 */
async function gotoRoute(page: import("@playwright/test").Page, r: RouteSpec): Promise<void> {
  await page.goto(visitPath(r), { waitUntil: "domcontentloaded" });
  if (r.kind === "redirect" && r.target) {
    await page.waitForURL((u) => u.pathname.replace(/\/$/, "") === r.target!.replace(/\/$/, ""), {
      waitUntil: "domcontentloaded",
    });
  }
}

/**
 * Assertions every route must satisfy in every mode.
 *
 * Deliberately expressed as "the page did not fail" rather than "the page
 * contains X": for 25 of the 50 routes the manifest has no distinctive landmark
 * yet, so a content assertion would either be vacuous or invented. An invented
 * landmark that passes everywhere is worse than none, because it reads as
 * coverage. The landmark check below runs only where a real one is declared.
 */
async function assertRouteHealthy(
  page: import("@playwright/test").Page,
  r: RouteSpec,
  consoleErrors: string[]
): Promise<void> {
  // 1. Did not collapse to the route-level error boundary (white-screen).
  await expect(
    page.locator("body"),
    `${r.path} white-screened to the route error fallback`
  ).not.toHaveText(ERROR_BOUNDARY_TEXT);

  // 2. Something actually rendered. A blank body is a failure that produces no
  //    error text and would otherwise sail through every other assertion here.
  const bodyText = (await page.textContent("body")) ?? "";
  expect(
    bodyText.trim().length,
    `${r.path} rendered an empty body (nothing at all painted)`
  ).toBeGreaterThan(0);

  // 3. The landmark proving THIS page rendered, where one is declared.
  if (r.landmark) {
    await expect(
      page.locator("body"),
      `${r.path} did not render its landmark ${r.landmark}`
    ).toHaveText(r.landmark);
  }

  // 4. No fatal console errors. Checked last so a more specific failure above
  //    reports first -- console noise is usually a symptom, not the cause.
  expect(
    consoleErrors,
    `${r.path} produced fatal console errors:\n${consoleErrors.join("\n")}`
  ).toEqual([]);
}

for (const r of ROUTES) {
  // ---- every route, degraded engine (up, but no data yet) ------------------
  test(`${r.path} [degraded] renders without crashing on empty engine data`, async ({ page }) => {
    const consoleErrors = collectConsoleErrors(page);
    await installEngineMock(page, "degraded");

    // gotoRoute enforces the redirect target: a redirect that never lands, or
    // lands somewhere else, fails here. A wrong-target redirect otherwise
    // renders a perfectly healthy page and passes every other check in this file.
    await gotoRoute(page, r);

    await assertRouteHealthy(page, r, consoleErrors);
  });

  // ---- critical routes: prove a VISIBLE degraded indicator -----------------
  if (r.criticality === "critical") {
    test(`${r.path} [offline] shows a visible degraded indicator, not just "didn't crash"`, async ({
      page,
    }) => {
      const consoleErrors = collectConsoleErrors(page);
      await installEngineMock(page, "offline");

      await gotoRoute(page, r);

      // The bar is that an operator can SEE the system is degraded. A page that
      // renders serenely with stale or absent data during an engine outage is
      // the most dangerous failure mode this suite can catch: it invites a
      // trading decision on data that is not there.
      //
      // SystemFreshnessStrip (role="status", mounted globally in app/layout.tsx)
      // is the indicator that actually ships. NOTE: EngineOfflineBanner -- the
      // loud bottom banner, and the thing the strip's own docstring calls "the
      // loud failure mode" -- is mounted nowhere. That is filed as a finding,
      // not worked around here.
      await expect(
        page.getByRole("status").filter({ hasText: /Engine\s+offline/i }),
        `${r.path} showed no visible engine-offline indicator during a full engine outage`
      ).toBeVisible();

      await assertRouteHealthy(page, r, consoleErrors);
    });

    test(`${r.path} [slow] resolves its loading state instead of spinning forever`, async ({
      page,
    }) => {
      const consoleErrors = collectConsoleErrors(page);
      await installEngineMock(page, "slow");

      await gotoRoute(page, r);

      // A spinner that never resolves is invisible to a fast mock and looks
      // identical to "loading" forever to an operator.
      await assertRouteHealthy(page, r, consoleErrors);
    });
  }

  // ---- research routes: provenance banner is mandatory ---------------------
  if (r.criticality === "research") {
    test(`${r.path} [exploratory-banner] carries its exploratory provenance banner`, async ({
      page,
    }) => {
      await installEngineMock(page, "degraded");
      await gotoRoute(page, r);

      // A research surface without this banner reads as a production signal.
      // Known to fail on several routes at the time this landed -- that is the
      // finding, and the fix is to add the banner (or correct the route's
      // criticality in the manifest), never to drop this assertion.
      await expect(
        page.getByTestId("exploratory-banner"),
        `${r.path} is classified research but renders no exploratory-banner`
      ).toBeVisible();
    });
  }
}
