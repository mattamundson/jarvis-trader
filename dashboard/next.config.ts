import path from "node:path";
import { fileURLToPath } from "node:url";
import type { NextConfig } from "next";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const nextConfig: NextConfig = {
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

    return [
      {
        source: "/ws/:path*",
        destination: `${engineUrl}/ws/:path*`,
      },
    ];
  },
};

export default nextConfig;
