/**
 * Framework-agnostic core shared by app/api/engine/[...path]/route.ts and
 * app/api/master/[...path]/route.ts. Built on the standard Request/Response/
 * Headers/fetch Web APIs only (no `next/server` import) specifically so it
 * can be unit-tested with Node's native test runner — the bare "next/server"
 * specifier those route files import can only be resolved by Next's own
 * bundler, not by `node --test` (see tests/api-proxy.test.ts).
 *
 * Behavior is byte-identical to the pre-extraction inline implementations;
 * this is a pure extraction for testability, not a functional change.
 */

export interface ProxyConfig {
  baseUrl: string;
  apiKey: string | undefined;
  apiKeyHeader?: string; // default "X-API-Key"
  timeoutMs: number;
  forwardClientHeaders: boolean; // engine proxy forwards client headers; master proxy does not
  redirect?: RequestRedirect;
  errorTag: string; // "engine_proxy_failed" | "master_proxy_failed"
}

export interface ProxyRequest {
  method: string;
  headers: Headers;
  search: string;
  body?: () => Promise<ArrayBuffer>;
}

export function buildTargetUrl(baseUrl: string, path: string[], search: string): URL {
  const target = new URL(`${baseUrl}/${path.join("/")}`);
  target.search = search;
  return target;
}

/**
 * The API key is always read from server-only config (`config.apiKey`,
 * itself sourced from a non-`NEXT_PUBLIC_*` env var) — it never flows in
 * from `clientHeaders`. When `forwardClientHeaders` is false (master proxy)
 * the client's headers are dropped entirely, so nothing the browser sends
 * — including any header named `X-API-Key` — ever reaches the upstream call.
 */
export function buildUpstreamHeaders(
  config: Pick<ProxyConfig, "apiKey" | "apiKeyHeader" | "forwardClientHeaders">,
  clientHeaders: Headers,
): Headers {
  const headerName = config.apiKeyHeader ?? "X-API-Key";
  const headers = config.forwardClientHeaders ? new Headers(clientHeaders) : new Headers();
  if (config.forwardClientHeaders) {
    headers.delete("host");
    headers.delete("connection");
    headers.delete("content-length");
  }
  if (config.apiKey) {
    headers.set(headerName, config.apiKey);
  }
  return headers;
}

export function sanitizeUpstreamResponseHeaders(upstreamHeaders: Headers): Headers {
  const headers = new Headers(upstreamHeaders);
  headers.delete("content-encoding");
  headers.delete("content-length");
  headers.delete("transfer-encoding");
  return headers;
}

export async function runProxy(
  config: ProxyConfig,
  request: ProxyRequest,
  path: string[],
  fetchImpl: typeof fetch = fetch,
): Promise<Response> {
  const target = buildTargetUrl(config.baseUrl, path, request.search);
  const headers = buildUpstreamHeaders(config, request.headers);

  const init: RequestInit = { method: request.method, headers };
  if (config.redirect) {
    init.redirect = config.redirect;
  }
  if (request.method !== "GET" && request.method !== "HEAD" && request.body) {
    init.body = await request.body();
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), config.timeoutMs);

  let upstream: Response;
  try {
    upstream = await fetchImpl(target, {
      ...init,
      cache: "no-store",
      signal: controller.signal,
    });
  } catch (error) {
    return Response.json(
      {
        error: config.errorTag,
        target: target.toString(),
        message: error instanceof Error ? error.message : "Unknown proxy error",
      },
      { status: 502 },
    );
  } finally {
    clearTimeout(timeout);
  }

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: sanitizeUpstreamResponseHeaders(upstream.headers),
  });
}
