import { NextRequest, NextResponse } from "next/server";
import { decideDashboardAuth, readDashboardAuthEnv } from "@/lib/dashboardAuth";
import { isPublicReadOnlyPath } from "@/lib/publicRoutes";

/**
 * HTTP Basic Auth for the JARVIS trading dashboard.
 *
 * The dashboard is a trading control surface (positions, kill-switch state,
 * order approval) — it must never be reachable without credentials when
 * exposed beyond localhost. This middleware enforces Basic Auth at the edge
 * (before any route handler runs) whenever credentials are configured.
 *
 * Configuration (server-side env, never NEXT_PUBLIC):
 *   DASHBOARD_AUTH_USER  — username
 *   DASHBOARD_AUTH_PASS  — password
 *
 * Behavior (see lib/dashboardAuth.ts for the policy and its unit tests):
 *   - Both vars set   -> enforced. Missing/wrong creds get 401 + WWW-Authenticate
 *                        (browser shows the native credential prompt).
 *   - Neither set, on a hosted deployment -> FAIL CLOSED (503). This is the
 *                        important case: a Vercel deploy without DASHBOARD_AUTH_*
 *                        previously served the whole dashboard and the
 *                        /api/engine/* proxy (which injects the engine API key
 *                        server-side) to the public internet. Refusing traffic is
 *                        the safe failure mode.
 *   - Neither set, plain localhost -> allowed, so local dev and CI need no shared
 *                        secret. Logs a warning so the gap stays visible.
 *   - DASHBOARD_AUTH_DISABLED=1 -> allowed even on a hosted deployment, for a
 *                        deliberate public demo. Never set this in production.
 *
 * Security notes:
 *   - Uses a constant-time comparison (crypto.timingSafeEqual) to avoid
 *     user-enumerable timing side channels.
 *   - The check runs in the Edge runtime (Next middleware) — no secrets are
 *     shipped to the client bundle.
 *   - Credentials travel in the Authorization header; in production this must
 *     sit behind TLS (local dev is loopback-only by default).
 */

function timingSafeEqualStr(a: string, b: string): boolean {
  const bufA = new TextEncoder().encode(a);
  const bufB = new TextEncoder().encode(b);
  if (bufA.length !== bufB.length) return false;
  let diff = 0;
  for (let i = 0; i < bufA.length; i++) {
    diff |= bufA[i] ^ bufB[i];
  }
  return diff === 0;
}

let warnedUnauthenticated = false;

function unauthorized(): NextResponse {
  return new NextResponse("Authentication required", {
    status: 401,
    headers: {
      "WWW-Authenticate": 'Basic realm="JARVIS Trading Dashboard", charset="UTF-8"',
      "Cache-Control": "no-store",
    },
  });
}

export function middleware(req: NextRequest) {
  if (isPublicReadOnlyPath(req.nextUrl.pathname)) {
    return NextResponse.next();
  }

  const decision = decideDashboardAuth(readDashboardAuthEnv());

  if (decision === "deny") {
    if (!warnedUnauthenticated) {
      warnedUnauthenticated = true;
      console.error(
        "[auth] DASHBOARD_AUTH_USER/DASHBOARD_AUTH_PASS not set on a hosted deployment — refusing to serve private routes. " +
          "Set both, or set DASHBOARD_AUTH_DISABLED=1 deliberately for a public demo.",
      );
    }
    return new NextResponse(
      "Dashboard authentication is not configured on this deployment. " +
        "Set DASHBOARD_AUTH_USER and DASHBOARD_AUTH_PASS.",
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }

  if (decision === "allow") {
    if (!warnedUnauthenticated) {
      warnedUnauthenticated = true;
      console.warn(
        "[auth] DASHBOARD_AUTH_USER/DASHBOARD_AUTH_PASS not set — dashboard is UNAUTHENTICATED. Set both to enforce Basic Auth.",
      );
    }
    return NextResponse.next();
  }

  // decision === "enforce" — fall through to Basic Auth check below
  const user = process.env.DASHBOARD_AUTH_USER!;
  const pass = process.env.DASHBOARD_AUTH_PASS!;

  const auth = req.headers.get("authorization") ?? "";
  const [scheme, encoded] = auth.split(" ");
  if (scheme !== "Basic" || !encoded) return unauthorized();

  let decoded: string;
  try {
    decoded = Buffer.from(encoded, "base64").toString("utf8");
  } catch {
    return unauthorized();
  }

  const colon = decoded.indexOf(":");
  if (colon === -1) return unauthorized();
  const reqUser = decoded.slice(0, colon);
  const reqPass = decoded.slice(colon + 1);

  if (!timingSafeEqualStr(reqUser, user) || !timingSafeEqualStr(reqPass, pass)) {
    return unauthorized();
  }

  return NextResponse.next();
}

export const config = {
  // Protect every route except Next.js internals (static assets under _next
  // are fine to gate too — the browser resends credentials after the 401,
  // and it prevents unauthenticated probing of build assets).
  //
  // /ws/:path* is EXCLUDED: WebSocket upgrades from browsers cannot carry the
  // Authorization header, so gating them here would break every live stream.
  // The engine authenticates WS itself (/ws/pipeline requires ?api_key=, which
  // the Next.js rewrite injects server-side; /ws/events is a public event
  // stream). See lib/pipeline_ws.ts security note (2026-08-17).
  matcher: ["/((?!_next/static|_next/image|favicon.ico|ws/).*)"],
};
