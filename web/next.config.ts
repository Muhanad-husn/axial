import type { NextConfig } from "next";

/** Where the analyst service lives. Read when the server starts, not when the
 * bundle is built, so the API's address stays a deployment setting instead of
 * something baked into the browser. `/api/*` is proxied onto it so the client
 * is same-origin: the FastAPI app installs no CORS middleware, and this way it
 * does not need any. */
const apiBase = (process.env.AXIAL_API_BASE ?? "http://127.0.0.1:8000").replace(/\/$/, "");

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiBase}/:path*` }];
  },
};

export default nextConfig;
