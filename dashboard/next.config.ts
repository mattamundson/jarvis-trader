import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Allow API calls to the Python engine on port 8010
  async rewrites() {
    return [
      {
        source: "/api/engine/:path*",
        destination: "http://localhost:8010/:path*",
      },
    ];
  },
};

export default nextConfig;
