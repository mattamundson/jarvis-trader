import path from "node:path";
import { fileURLToPath } from "node:url";
import type { NextConfig } from "next";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const nextConfig: NextConfig = {
  // Monorepo: silence Next multi-lockfile root warning (repo root may have other lockfiles)
  outputFileTracingRoot: path.join(__dirname, ".."),
  // Allow API calls to the Python engine — destination reads NEXT_PUBLIC_ENGINE_URL
  // so local dev, staging, and production can all point to different hosts.
  async rewrites() {
    const engineUrl = process.env.NEXT_PUBLIC_ENGINE_URL ?? "http://localhost:8010";
    return [
      {
        source: "/api/engine/:path*",
        destination: `${engineUrl}/:path*`,
      },
    ];
  },
};

export default nextConfig;
