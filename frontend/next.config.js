/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,

  async rewrites() {
    const backendUrl = process.env.BACKEND_URL || "http://localhost:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },

  env: {
    NEXT_PUBLIC_API_URL: "",
  },

  // Phase E security headers. CSP is intentionally minimal:
  // 'unsafe-inline' for styles is required by Tailwind-injected
  // styles; no 'unsafe-inline'/'unsafe-eval' for scripts. If a
  // future feature needs inline scripts, the CSP must be revisited
  // first — do not silently widen it.
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          {
            key: "Content-Security-Policy",
            value:
              "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; connect-src 'self'",
          },
        ],
      },
    ];
  },
};

module.exports = nextConfig;
