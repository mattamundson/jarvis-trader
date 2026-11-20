// Pure header-construction for the server-side engine proxy
// (app/api/engine/[...path]/route.ts). Extracted so the exact auth-injection
// behavior can be exercised in isolation — see tests/engineProxyHeaders.test.ts.
//
// Why these headers (DEPLOY_VERCEL.md): in production the engine sits behind an
// ngrok tunnel that (1) enforces basic-auth and (2) injects an HTML browser-warning
// interstitial for browser-like requests. Without both headers below, every engine
// call through the tunnel is 401'd or served HTML instead of JSON, and the deployed
// dashboard renders "engine offline" everywhere. All are set server-side only, so
// neither the engine key nor the basic-auth credential reaches the browser bundle.

export interface EngineAuthEnv {
  // Engine X-API-Key (engine/.env API_KEY). Absent → header omitted.
  apiKey?: string;
  // ngrok tunnel basic-auth as "user:pass" (ngrok.yml). Absent (local dev, no
  // tunnel) → Authorization header omitted.
  tunnelBasicAuth?: string;
}

export function applyEngineAuthHeaders(
  headers: Headers,
  env: EngineAuthEnv,
): Headers {
  headers.delete("authorization");
  if (env.apiKey) {
    headers.set("X-API-Key", env.apiKey);
  }
  if (env.tunnelBasicAuth) {
    const encoded = Buffer.from(env.tunnelBasicAuth).toString("base64");
    headers.set("Authorization", `Basic ${encoded}`);
  }
  // Always safe to send; only meaningful when traversing the ngrok tunnel.
  headers.set("ngrok-skip-browser-warning", "true");
  return headers;
}
