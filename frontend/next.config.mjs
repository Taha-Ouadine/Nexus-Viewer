/** @type {import('next').NextConfig} */
const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000"

const nextConfig = {
  // The browser only talks to this Next.js server; /api/* is forwarded to FastAPI.
  // No proxy route handlers to maintain and no CORS issues.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` }]
  },
  async headers() {
    return [
      // Only the embed route may be shown inside other sites' iframes.
      { source: "/embed", headers: [{ key: "Content-Security-Policy", value: "frame-ancestors *" }] },
      {
        source: "/((?!embed).*)",
        headers: [{ key: "Content-Security-Policy", value: "frame-ancestors 'self'" }],
      },
    ]
  },
  experimental: {
    // frame jobs can take a while on a cold cache; give the rewrite proxy room
    proxyTimeout: 120_000,
  },
  images: { unoptimized: true },
}

export default nextConfig
