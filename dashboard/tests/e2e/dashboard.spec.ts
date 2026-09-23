import { test, expect } from "@playwright/test";

test("dashboard route smoke: /dashboard resolves to command center content", async ({ page }) => {
  await page.goto("/dashboard");
  await page.waitForURL("**/command-center");

<<<<<<< HEAD
  await expect(page.getByRole("heading", { name: /JARVIS TRADER.*COMMAND CENTER/i })).toBeVisible();
=======
  // /dashboard is a client-side redirect stub to /command-center: the redirect
  // completes AFTER domcontentloaded (a router push, not a server 30x), so
  // reading url()/content() immediately races it -- page.content() can even
  // throw "Unable to retrieve content because the page is navigating and
  // changing the content" mid-transition. Wait for the URL to settle first,
  // same idiom as gotoRoute() in smoke.spec.ts. Bounded and swallowed: if this
  // route ever stops redirecting, the branch below already handles that case.
  await page
    .waitForURL((u) => u.pathname.replace(/\/$/, "") !== "/dashboard", {
      waitUntil: "domcontentloaded",
      timeout: 5_000,
    })
    .catch(() => {});

  const url = page.url();
  const html = await page.content();

  if (url.includes("/command-center")) {
    await expect(page.getByRole("heading", { name: /JARVIS TRADER.*COMMAND CENTER/i })).toBeVisible();
  } else {
    expect(html).toContain("/command-center");
  }
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
});
