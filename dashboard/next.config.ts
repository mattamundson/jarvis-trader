import path from "node:path";
import { fileURLToPath } from "node:url";
import type { NextConfig } from "next";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const nextConfig: NextConfig = {
  // Let a dev server build into its OWN directory so it cannot destroy the
  // production build that pm2's `next start` is serving from `.next`.
  //
  // `next dev` rewrites distDir in place regardless of --port, so a dev server
  // started in this tree silently replaces the prod bundle: BUILD_ID empties,
  // static/css/ disappears, and `next start` then serves 200 HTML with 400 on
  // every stylesheet -- the dashboard renders as raw unstyled markup while
  // every health check still reports "up". This has taken the dashboard down
  // twice (2026-07-17 02:59 and again ~06:00, mid trading-morning), because
  // .claude/launch.json defines `pnpm dev` configs pointed at this directory.
  //
  // Isolating the paths makes the two coexist instead of fight. Set
  // NEXT_DIST_DIR=.next-dev for any dev server (see .claude/launch.json).
  distDir: process.env.NEXT_DIST_DIR || ".next",

  // Pin Watchpack/output-file-tracing root to this dashboard dir.
  // Without this, Next.js walks up looking for a workspace lockfile and can
  // fall back to C:\, which produces EINVAL lstat errors on hiberfil.sys etc.
  // The dashboard owns its own pnpm-lock.yaml, so __dirname is the correct root.
  outputFileTracingRoot: __dirname,
  async rewrites() {
    const engineUrl = (
      process.env.ENGINE_INTERNAL_URL ??
      process.env.ENGINE_URL_INTERNAL ??
      // 127.0.0.1, not localhost: Windows resolves localhost to ::1 first
      // and the engine binds IPv4 only.
      "http://127.0.0.1:8010"
    ).replace(/\/$/, "");

    // /ws/pipeline requires api_key auth (engine/routers/pipeline_ws_router.py).
    // Inject the server-only ENGINE_API_KEY here so a same-origin client never
    // has to carry it — mirrors the header injection in
    // app/api/engine/[...path]/route.ts. Must precede the general /ws/:path*
    // rule below (rewrites are matched in array order).
    const engineApiKey = process.env.ENGINE_API_KEY;
    const pipelineWsRewrite = engineApiKey
      ? [
          {
            source: "/ws/pipeline",
            destination: `${engineUrl}/ws/pipeline?api_key=${encodeURIComponent(engineApiKey)}`,
          },
        ]
      : [];

    return [
      ...pipelineWsRewrite,
      {
        source: "/ws/:path*",
        destination: `${engineUrl}/ws/:path*`,
      },
    ];
  },
};

export default nextConfig;
