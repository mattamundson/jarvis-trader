import { NextRequest, NextResponse } from "next/server";
import { decideDashboardAuth, readDashboardAuthEnv } from "@/lib/dashboardAuth";
import { isPublicReadOnlyRequest, isWebSocketPath, isWebSocketUpgrade, isFlowIngestPath } from "@/lib/publicRoutes";

/**
 * Pages and explicitly allowlisted data reads are public. Other routes and
 * mutations require DASHBOARD_AUTH_USER/PASS; engine credentials remain server-only.
 * GET is not inherently safe: command streams, LLM actions and unknown proxies
 * are deliberately excluded from public reads. The legacy public-demo disable
 * flag must never disable action authentication on a hosted deployment.
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
  if (isPublicReadOnlyRequest(req.nextUrl.pathname, req.method)) {
    return NextResponse.next();
  }

  // Flow ingest endpoint has its own Bearer token auth (FLOW_INGEST_TOKEN).
  // Exempt POST /api/flow/ingest from Basic auth so pushers can authenticate directly.
  if (isFlowIngestPath(req.nextUrl.pathname, req.method)) {
    return NextResponse.next();
  }

  // WebSocket handshakes cannot carry an Authorization header, so a genuine upgrade must be
  // allowed through. An ordinary GET under /ws/ is NOT an upgrade and falls through to the
  // auth checks below — otherwise the whole /ws/ prefix is an unauthenticated hole.
  if (isWebSocketPath(req.nextUrl.pathname) && isWebSocketUpgrade(req.headers.get("upgrade"))) {
    return NextResponse.next();
  }

  // A public page may poll a protected diagnostic. Do not turn an API denial
  // into a browser-wide Basic Auth dialog; owners can still supply credentials.
  if (req.nextUrl.pathname.startsWith("/api/") && !req.headers.get("authorization")) {
    return NextResponse.json({ error: "read_only", message: "This action requires authentication." },
      { status: 403, headers: { "Cache-Control": "no-store" } });
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
  // Protect every route except Next.js internals (static assets under _next
  // are fine to gate too — the browser resends credentials after the 401,
  // and it prevents unauthenticated probing of build assets).
  //
  // /ws/:path* is NO LONGER excluded from the matcher.
  //
  // Excluding the whole `ws/` prefix meant any ORDINARY GET under /ws/ bypassed Basic Auth
  // and was proxied to the engine tunnel — which disclosed the tunnel hostname to anonymous
  // callers and exposed its unauthenticated surface. WebSocket traffic genuinely cannot
  // carry an Authorization header, so the decision now lives in the request instead of the
  // path: a real `Upgrade: websocket` handshake passes, and everything else under /ws/ must
  // authenticate like any other route. See lib/publicRoutes.ts (isWebSocketPath /
  // isWebSocketUpgrade) and the lib/pipeline_ws.ts security note.
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
