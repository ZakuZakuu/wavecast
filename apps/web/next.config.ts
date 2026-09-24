import type { NextConfig } from "next";

const internalApiUrl = process.env.WAVECAST_INTERNAL_API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return {
      beforeFiles: [],
      afterFiles: [],
      fallback: [{ source: "/api/:path*", destination: `${internalApiUrl}/api/:path*` }],
    };
  },
};

export default nextConfig;
