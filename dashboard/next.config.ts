import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  typescript: {
    ignoreBuildErrors: true,
  },
  eslint: {
    ignoreDuringBuilds: true,
  },
  async rewrites() {
    const engineUrl = (
      process.env.ENGINE_INTERNAL_URL ??
      process.env.ENGINE_URL_INTERNAL ??
      "http://localhost:8010"
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