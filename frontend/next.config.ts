import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // Disable aggressive caching so deployments take effect immediately
  headers: async () => [
    {
      source: "/:path*",
      headers: [
        {
          key: "Cache-Control",
          value: "no-store, must-revalidate",
        },
      ],
    },
  ],
};

export default nextConfig;
