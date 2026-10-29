import { NextRequest, NextResponse } from "next/server";
import { decideDashboardAuth, readDashboardAuthEnv } from "@/lib/dashboardAuth";
import { isFlowIngestPath } from "@/lib/publicRoutes";

/** Require dashboard credentials on every page, API and WebSocket handshake.
 * Feed ingestion retains its separate Bearer-token authentication.
 * Hosted deployments without credentials fail closed; demo flags cannot bypass it.
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
  // Flow ingest endpoint has its own Bearer token auth (FLOW_INGEST_TOKEN).
  // Exempt POST /api/flow/ingest from Basic auth so pushers can authenticate directly.
  if (isFlowIngestPath(req.nextUrl.pathname, req.method)) {
    return NextResponse.next();
  }

  const user = process.env.DASHBOARD_AUTH_USER;
  const pass = process.env.DASHBOARD_AUTH_PASS;

  const decision = decideDashboardAuth({ ...readDashboardAuthEnv(), disabled: undefined });

  if (decision === "deny") {
    if (!warnedUnauthenticated) {
      warnedUnauthenticated = true;
      console.error(
        "[auth] DASHBOARD_AUTH_USER/DASHBOARD_AUTH_PASS not set on a hosted deployment — refusing to serve private routes. " +
          "Set both to authenticate protected actions.",
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

  // decision === "enforce" implies both are configured; this narrows the types and
  // fails closed if that invariant is ever broken.
  if (!user || !pass) return unauthorized();

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
  // All pages, APIs, and WebSocket handshakes are protected. Only framework
  // assets bypass Basic Auth; ingestion verifies its own Bearer token.
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
