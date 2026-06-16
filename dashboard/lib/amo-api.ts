// Read-only client for the amo-arbitrage system, proxied server-side through
// /api/amo (see app/api/amo/[...path]/route.ts) to avoid CORS. The two trading
// systems stay independent — this is observability-only for the Trust Pane.
const AMO = "/api/amo";
const FETCH_TIMEOUT_MS = 15000;

export async function fetchAmo<T = unknown>(path: string): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const res = await fetch(`${AMO}${path}`, {
      cache: "no-store",
      signal: controller.signal,
    });
    if (!res.ok) {
      throw new Error(`amo error ${res.status}: ${path}`);
    }
    return res.json();
  } finally {
    clearTimeout(timeoutId);
  }
}

/** GET /api/health on amo-arbitrage. */
export interface AmoScheduledJob {
  id: string;
  next_run: string;
}

export interface AmoHealthResponse {
  status: string;
  version?: string;
  time?: string;
  scheduler_running?: boolean;
  scheduled_jobs?: number;
  jobs?: AmoScheduledJob[];
}

export async function fetchAmoHealth(): Promise<AmoHealthResponse> {
  return fetchAmo<AmoHealthResponse>("/api/health");
}
