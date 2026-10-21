import type { NextConfig } from "next";

// The browser calls same-origin /api/*; Next.js forwards it to the Django API,
// so no CORS setup is needed and database credentials never reach the browser.
// Read at build time for `next build`/`next start`, and at startup for `next dev`.
const apiUrl = (process.env.ATTENDANCE_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiUrl}/api/:path*` }];
  },
};

export default nextConfig;
