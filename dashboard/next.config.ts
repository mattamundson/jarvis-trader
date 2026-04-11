import path from "node:path";
import { fileURLToPath } from "node:url";
import type { NextConfig } from "next";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const nextConfig: NextConfig = {
  // Monorepo: silence Next multi-lockfile root warning (repo root may have other lockfiles)
  outputFileTracingRoot: path.join(__dirname, ".."),
  // `/api/engine/*` is handled by the app route proxy in
  // `app/api/engine/[...path]/route.ts` so protected engine requests can be
  // authenticated server-side without depending on browser header forwarding.
  async rewrites() {
    const engineUrl = (
      process.env.ENGINE_URL ?? process.env.NEXT_PUBLIC_ENGINE_URL ?? "http://localhost:8010"
    ).replace(/\/$/, "");

    return [
      {
        source: "/ws/:path*",
        destination: `${engineUrl}/ws/:path*`,
      },
    ];
  },
};

export default nextConfig;
