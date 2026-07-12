import { NextRequest } from "next/server";
import { runProxy, type ProxyConfig } from "@/lib/api-proxy";

// Read-only server-side proxy to the master-api service (separate service,
// not in this repo — see AGENTS.md "External service: master-api"). Mirrors
// app/api/amo/[...path]/route.ts so lib/masterApi.ts never puts the
// master-api URL or key in the client bundle. Only GET is exposed — the
// dashboard never mutates master-api state, including the /master/command/stream
// SSE endpoint (EventSource is GET-only by spec).

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
// 60s: covers the /master/command/stream SSE chat responses, which can run
// longer than a plain JSON fetch. Longer than the amo proxy's 15s on purpose.
export const maxDuration = 60;

function getMasterBaseUrl(): string {
  return process.env.MASTER_API_URL ?? "http://127.0.0.1:8030";
}

function getMasterApiKey(): string | undefined {
  // Server-only var — never NEXT_PUBLIC_* — so the key is never inlined into
  // the client bundle.
  return process.env.MASTER_API_KEY;
}

async function proxyGet(request: NextRequest, path: string[]): Promise<Response> {
  const config: ProxyConfig = {
    baseUrl: getMasterBaseUrl(),
    apiKey: getMasterApiKey(),
    timeoutMs: 55_000,
    // GET-only proxy — the client's own headers are never forwarded upstream,
    // so nothing the browser sends (including any header named X-API-Key)
    // can reach master-api.
    forwardClientHeaders: false,
    errorTag: "master_proxy_failed",
  };

  return runProxy(
    config,
    {
      method: "GET",
      headers: request.headers,
      search: request.nextUrl.search,
    },
    path,
  );
}

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

export async function GET(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return proxyGet(request, path);
}
