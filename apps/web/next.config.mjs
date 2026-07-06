/** @type {import('next').NextConfig} */
const API_PROXY_TARGET = process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8088";

// Static-export mode (CDN deploy, e.g. GitHub Pages). When STATIC_EXPORT=1 the
// site is emitted as a fully static bundle in `out/` — no server, no rewrites —
// and the client reads pre-baked JSON snapshots (see lib/api.ts static mode).
// BASE_PATH scopes it under a repo subpath (GitHub project pages: /<repo>).
const STATIC_EXPORT = process.env.STATIC_EXPORT === "1";
const BASE_PATH = process.env.PAGES_BASE_PATH ?? "";

const nextConfig = {
  reactStrictMode: true,
  env: {
    // Empty = same-origin: the browser calls /api/* on the web origin and Next
    // proxies it to the backend (see rewrites). Keeps the API private and avoids
    // CORS — and means a single public URL (e.g. Tailscale Funnel) serves both.
    NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL ?? "",
    NEXT_PUBLIC_STATIC_MODE: STATIC_EXPORT ? "1" : "",
    NEXT_PUBLIC_BASE_PATH: BASE_PATH,
  },
  ...(STATIC_EXPORT
    ? {
        output: "export",
        basePath: BASE_PATH || undefined,
        assetPrefix: BASE_PATH || undefined,
        trailingSlash: true,
        images: { unoptimized: true },
      }
    : {
        async rewrites() {
          return [
            { source: "/api/:path*", destination: `${API_PROXY_TARGET}/api/:path*` },
            { source: "/health", destination: `${API_PROXY_TARGET}/health` },
            { source: "/health/:path*", destination: `${API_PROXY_TARGET}/health/:path*` },
          ];
        },
      }),
};

export default nextConfig;
