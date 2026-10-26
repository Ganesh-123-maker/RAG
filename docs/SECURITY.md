# Security

## Authentication and sessions

- Passwords: bcrypt via passlib; minimum length 8 (see
  `schemas/auth.py`). No password is logged or returned.
- Tokens: JWT, HS256, 60-minute expiry, with a `jti` claim. The
  backend accepts a Bearer token or the httpOnly cookie set at login;
  JavaScript never sees the token (Phase E removed all `js-cookie`
  token handling from app code; the `js-cookie` package itself was
  already gone from `package.json` by Phase F).
- Logout revokes the current access token, via an in-memory denylist
  (`core/token_denylist.py`), and revokes the presented refresh
  token in the database. Access-token denylist revocation does not
  survive a process restart or span replicas; refresh-token
  revocation does (it is a DB row, not process memory).
- Refresh tokens: opaque tokens (`secrets.token_urlsafe(32)`)
  stored only as SHA-256 hashes (`models/refresh_token.py`,
  migration `004_refresh_tokens`), 7-day expiry
  (`REFRESH_TOKEN_EXPIRE_DAYS`), httpOnly cookie scoped to
  `/api/v1/auth`, rotated on every use in the same family
  (`services/refresh_token_service.py`). Presenting an
  already-replaced token is reuse (stolen-token replay): the whole
  family is revoked. Expired, revoked, and unknown tokens all
  return the same generic 401, so failures do not leak which reason
  applied. The frontend retries once after a successful refresh
  (`lib/api.ts`, one shared in-flight refresh for concurrent
  401s); if refresh fails it falls back to the login redirect.
- Login lockout: 5 failed attempts per account, then 15 minutes
  locked (429 + `Retry-After`). Register/login are rate-limited per
  email/IP (see below).
- `is_active` is enforced: deactivated users cannot authenticate
  (Phase A fix). A JWT with a non-UUID `sub` returns 401, not 500.
- Secrets come only from the environment (`pydantic-settings`).
  Production startup refuses to run without a real `JWT_SECRET_KEY`;
  the dev-only secret is local-dev only. Never commit `.env`.

## Ownership and isolation (multi-tenancy)

- Every repository lookup that can return user data is owner-scoped
  (`get_by_id_for_owner`, conversation/document methods taking
  `owner_id`) -- Phase A closed the unscoped `get_by_id`/`delete`/
  `get_messages` pattern. Chat's `document_id` parameter is checked
  for ownership and for `ready` status before retrieval.
- Every Qdrant search ANDs an `owner_id` payload filter with any
  `document_id` filter, and Qdrant deletes are owner-scoped too.
  Cross-user access would require both the repository check and
  the vector filter to fail at once; neither is optional.
- Uploads are isolated per owner: UUID filenames under
  `uploads/<owner_id>/`; the original filename is metadata only and
  is never used as a path, so filename path traversal is not an
  attack surface here.

## Rate limits, quotas, CORS

- In-memory, single-instance rate limits (Phase E): auth 10/min,
  upload 10/min, chat 30/min, with 429 + `Retry-After`. They do not
  span replicas and do not survive restart.
- Per-user daily quota: 200 chats, 200k **estimated** tokens
  (question+answer chars / 4). This is a cost guard, not metered
  OpenAI usage -- never present it as billing.
- CORS origins come from config; production startup rejects `*`
  (with or without credentials). Default local origins are
  `http://localhost:3000` and `http://127.0.0.1:3000`.

## Uploads and prompt injection

- Upload validation is by content, not just extension: magic bytes
  are checked, size is streamed against the 50 MB cap (the whole
  file is not loaded first), and CPU-bound parsing/tokenizing runs
  in a threadpool. Scanned/image-only PDFs are detected and rejected
  with a clear user-facing error (OCR is out of scope).
- Document text is treated as data, not instructions: context blocks
  in the reasoning prompt are delimited and explicitly marked as
  untrusted document data, and the verify node checks cited chunk
  ids against retrieved chunks. This mitigates, but does not
  eliminate, prompt injection from uploaded documents: a sufficiently
  adversarial document plus a compliant model can still leak
  phrasing, and the 6 injection probes in the eval corpus only test
  a fixed forbidden-string rule. Do not claim injection-proofing.

## Frontend rendering and headers

- No `dangerouslySetInnerHTML`, no `innerHTML`, no `rehype-raw`.
  Document names render as React text (escaped by React). Answers
  render via `ReactMarkdown` + GFM with `rehype-sanitize` (added in
  Phase F on top of the already non-executing path), so embedded
  HTML in an answer is not executed.
- Security headers (`next.config.js`): `X-Content-Type-Options:
  nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy:
  strict-origin-when-cross-origin`, and a nonce CSP
  (`frontend/middleware.ts`): each request gets a fresh random nonce,
  Next.js stamps its inline scripts with it via the `x-nonce`
  request header, and `script-src` allows only `'self'` plus that
  nonce -- no script `unsafe-inline`/`unsafe-eval` anywhere. Pages
  are `force-dynamic` because statically prerendered pages are baked
  before any request nonce exists, so their inline scripts would
  ship nonce-less and be blocked (verified by header inspection and
  the Playwright journey). Style `unsafe-inline` remains, required
  by Tailwind-injected styles.
- Errors to clients are typed and safe: ingestion failures return
  422/502/500 with a safe message, never raw exception text (a
  sentinel-string test proves this); full errors are logged
  server-side with `exc_info`.

## Scan results -- NOT clean, read this before deploying

### Bandit (re-measured 2026-10-26)

`bandit -r app`: **12 Low, 0 Medium, 0 High** (was 11 in Phase G;
the one new Low is a best-effort `try/except/pass` in the
refresh-token auth path, same intentional pattern as the others).
All Low findings are documented false positives / intentional: the
dev-only secret string (production refuses it), best-effort
`try/except/pass` shutdown and cleanup blocks (annotated with
`# noqa` reasons where they are intentional), the literal
`token_type="bearer"`, and pre-existing `assert` uses in MMR code.
No bandit finding was hidden with a blanket ignore.

### pip-audit (2026-10-26 upgrade, re-measured — not the Phase G count)

Before (re-measured 2026-10-26 on the old pins): **57 records in
11 packages**. After upgrading (see below): **3 records in 2
packages**, both with **no fixed release available** — they are
documented here, not hidden.

Upgrades applied 2026-10-26 (all in `backend/requirements.txt`,
verified by the full suite — 130 pytest passed, Ruff clean, mypy
clean, no application code changes needed):
`fastapi` 0.111.0 → 0.162.0 (pulls `starlette` 0.37.2 → 1.10.0,
clearing every starlette record), `pydantic` 2.7.4 → 2.14.1 and
`pydantic-settings` 2.3.1 → 2.16.1 (required by the FastAPI bump),
`langgraph` 0.2.16 → 1.2.17 (pulls `langchain-core` 1.7.0,
`langgraph-checkpoint` 4.3.0, `langsmith` 0.14.12),
`python-jose` 3.3.0 → 3.5.0, `markdown` 3.6 → 3.11.2,
`pdfplumber` 0.11.0 → 0.11.10 (pulls `pdfminer.six` 20260107),
`python-dotenv` 1.0.1 → 1.2.4, `pytest` 8.2.2 → 9.1.1 and
`pytest-asyncio` 0.23.7 → 1.4.1 (dev-only). Everything else in
requirements.txt is unchanged.

**Remaining 3 records — accepted risk, with conditions:** no fixed
version exists for any of them, so they cannot be upgraded away,
and each is unreachable from this app's code paths:
- `python-jose` 3.5.0, PYSEC-2026-4298 (algorithm-confusion guard
  bypass via DER-encoded public keys): the advisory's precondition
  is "when algorithms are not explicitly restricted". This app
  restricts them: `decode_access_token` passes
  `algorithms=[settings.JWT_ALGORITHM]` with default `HS256`
  (`app/core/security.py`, `app/core/config.py`), and it never
  accepts caller-chosen algorithms.
- `ecdsa` 0.19.2, PYSEC-2026-1325 ×2 (Minerva timing attack on
  P-256 signing): `ecdsa` is only a transitive dependency of
  `python-jose`; the app never imports it and never performs ECDSA
  signing — all tokens are HS256. (The earlier JWE-compression DoS
  record against `python-jose`, PYSEC-2025-185, no longer appears
  in the post-upgrade audit.)
This acceptance is valid **only while the app is not publicly
deployed**. Before any public deploy, re-run pip-audit: if a fixed
release exists for either package by then, upgrade to it and
rewrite this section. Dependabot is configured
(`.github/dependabot.yml`, weekly) and its PRs must be reviewed,
never auto-merged, for exactly this reason.

### npm audit

Not runnable in this sandbox: the registry audit endpoint returns
403 (`policy_denied`) -- a sandbox egress policy, not a clean
result, so **no npm-audit count is claimed here**. It runs in CI
as a non-blocking job (`frontend-security`,
`--audit-level=moderate`); that CI run is the verification path
for frontend vulnerabilities. What was done locally 2026-10-26:
`npm update` within the existing `^` ranges (no `package.json`
range changes, no major upgrades — Next.js stays on 15.x, React
on 19.x as instructed). Almost nothing moved: Next.js was already
at the latest 15.x (15.5.28), React at 19.3.1; only `axios`
1.19.0 → 1.20.0 and `remark-gfm` 4.0.0 → 4.0.1 plus transitive
re-resolves changed in `package-lock.json`. The old "15
vulnerabilities" figure predates the Next.js 15 upgrade and must
not be quoted as current. Frontend vitest (21 passed), `tsc`, and
`next build` all pass after the update.

## What is still open (security follow-ups)

- Redis-backed rate limits / denylist / quotas for multi-instance
  deployments (current ones are single-instance).
- Re-check the 3 remaining pip-audit records (python-jose, ecdsa)
  before any public deploy — see the pip-audit section above.
- A public-deploy security review pass after that upgrade.
