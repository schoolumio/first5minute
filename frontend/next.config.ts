import type { NextConfig } from "next";

// All API calls go through the Next.js origin (/api/v1/*) and are proxied to the
// FastAPI backend, so auth cookies are first-party and no API keys reach the browser.
const backend = process.env.BACKEND_URL ?? "http://localhost:8000";
// On Vercel the repository's vercel.json routes /api/v1/* straight to the `api` service, so no proxy rule is wanted here.
// Everywhere else (local dev, Docker/Caddy, Render + Vercel-frontend-only) the browser's /api/v1 calls are proxied to BACKEND_URL.
const onVercelServices = process.env.VERCEL === "1" && !process.env.BACKEND_URL;

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  output: "standalone",
  async rewrites() {
    return onVercelServices ? [] : [{ source: "/api/v1/:path*", destination: `${backend}/api/v1/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default nextConfig;
