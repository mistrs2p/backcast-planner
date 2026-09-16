import type { NextConfig } from "next";

// The browser talks to one origin — this app — and Next rewrites
// /api/* to the backend (ADR-008: the generated OpenAPI contract is
// the shared shape; the proxy keeps the contract reachable without
// CORS). API_ORIGIN points at the FastAPI service and is a
// server-side deployment knob, never a browser concern.
const apiOrigin = process.env.API_ORIGIN ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiOrigin}/:path*`,
      },
    ];
  },
};

export default nextConfig;
