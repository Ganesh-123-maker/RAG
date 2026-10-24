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

  // Phase E security headers, corrected in Phase F (see below).
  // Phase F fix: the Phase E CSP ("default-src 'self'" with no
  // script-src) blocked Next.js's own inline scripts, so hydration
  // never completed in dev OR production and every form submitted
  // natively instead of through React (proven by Playwright: the
  // register form landed on "/register?" with no API call). Next.js
  // requires inline scripts for hydration unless a nonce is plumbed
  // through middleware, so script-src now allows 'unsafe-inline'
  // (but NOT 'unsafe-eval'). A nonce-based CSP is the Phase G
  // follow-up; do not silently widen this further. Google Fonts
  // are also allowed explicitly: globals.css already @imports
  // them, and the old CSP silently fell back to system fonts.
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
              "default-src 'self'; script-src 'self' 'unsafe-inline'; img-src 'self' data:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' data: https://fonts.gstatic.com; connect-src 'self'",
          },
        ],
      },
    ];
  },
};

module.exports = nextConfig;
