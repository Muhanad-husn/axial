import type { NextConfig } from "next";

/** Where the analyst service lives. Read when the server starts, not when the
 * bundle is built, so the API's address stays a deployment setting instead of
 * something baked into the browser. `/api/*` is proxied onto it so the client
 * is same-origin: the FastAPI app installs no CORS middleware, and this way it
 * does not need any. */
const apiBase = (process.env.AXIAL_API_BASE ?? "http://127.0.0.1:8000").replace(/\/$/, "");

const nextConfig: NextConfig = {
  /** Do not turn this back on (#748). Next's server gzips every response,
   * including the `text/event-stream` proxied by the rewrite below, and gzip
   * buffers: the walk of a fourteen-minute ask reaches the browser when the
   * stream closes, fourteen minutes late, which is indistinguishable from a
   * hung service.
   * Measured on the production build, 25s into a live ask: 10 bytes and 0
   * events with a browser's `Accept-Encoding`, 9,103 bytes and 31 events
   * without it. There is no per-route escape -- compression is applied ahead
   * of routing, and the one header that would exempt this response
   * (`Cache-Control: no-transform`) is overwritten by the proxied response's
   * own. Compressing the bundle belongs to the CDN or edge in front of this
   * server, which is where every deployment of it puts compression anyway. */
  compress: false,
  /** `next dev` otherwise writes its own `AGENTS.md` and `CLAUDE.md` into the
   * repo, where `CLAUDE.md` is a convention with a meaning of its own. */
  agentRules: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiBase}/:path*` }];
  },
};

export default nextConfig;
