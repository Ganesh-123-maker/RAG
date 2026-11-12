import { NextRequest, NextResponse } from "next/server";

// Per-request CSP nonce (Phase G follow-up to the Phase F fix).
//
// Background: Phase E shipped a strict CSP with no script-src, which
// blocked Next.js's own inline hydration scripts entirely (proven by
// Playwright: forms submitted natively, no API calls). Phase F
// restored hydration with script-src 'unsafe-inline'. This middleware
// removes that: each request gets a fresh random nonce, Next.js reads
// it from the x-nonce request header and stamps its inline scripts
// with it, and the response CSP allows exactly that nonce.
//
// style-src keeps 'unsafe-inline' deliberately: Tailwind/Next inject
// inline styles at runtime and there is no equivalent style-nonce
// plumbing for them. The script vector — the one that executes code —
// is nonce-only.
//
// script-src also needs 'unsafe-eval' in development: Next.js dev
// mode evaluates code via eval() (webpack eval devtool), and without
// it the CSP throws on hydration and React never attaches — every
// form submits natively and every button is dead (proven by
// Playwright, 2026-11-12: `__reactFiber$` keys absent, pageerror
// "Evaluating a string as JavaScript violates ... script-src").
// Production builds do not use eval, so production stays nonce-only.
export function middleware(request: NextRequest) {
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");

  const scriptSrc =
    process.env.NODE_ENV === "development"
      ? `script-src 'self' 'nonce-${nonce}' 'unsafe-eval'`
      : `script-src 'self' 'nonce-${nonce}'`;

  const csp = [
    "default-src 'self'",
    scriptSrc,
    "img-src 'self' data:",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' data: https://fonts.gstatic.com",
    "connect-src 'self'",
  ].join("; ");

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);

  const response = NextResponse.next({
    request: { headers: requestHeaders },
  });
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

// Skip static assets and the API proxy (JSON responses need no CSP);
// everything else (pages) gets a nonce.
export const config = {
  matcher: [
    {
      source: "/((?!api|_next/static|_next/image|favicon.ico).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
