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

  // Security headers. CSP itself lives in middleware.ts, which
  // generates a per-request nonce: a static CSP here would be
  // enforced *in addition* to the middleware one, and its lack of
  // the nonce would block Next.js hydration scripts again (the
  // Phase F failure mode). Google Fonts are allowed explicitly:
  // globals.css already @imports them, and a CSP without them
  // silently fell back to system fonts.
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        ],
      },
    ];
  },
};

module.exports = nextConfig;
