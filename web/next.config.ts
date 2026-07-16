import type { NextConfig } from "next";

const apiBase = process.env.KJDS_API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/backend/:path*", destination: `${apiBase}/:path*` }];
  },
};

export default nextConfig;
