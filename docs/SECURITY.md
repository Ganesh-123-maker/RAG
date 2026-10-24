# Security

## Authentication and sessions

- Passwords: bcrypt via passlib; minimum length 8 (see
  `schemas/auth.py`). No password is logged or returned.
- Tokens: JWT, HS256, 60-minute expiry, with a `jti` claim. The
  backend accepts a Bearer token or the httpOnly cookie set at login;
  JavaScript never sees the token (Phase E removed all `js-cookie`
  token handling from app code; the `js-cookie` package itself was
  already gone from `package.json` by Phase F).
- Logout revokes only the current token, via an in-memory denylist
  (`core/token_denylist.py`). **Refresh tokens are deferred** (Phase
  E decision): there is no refresh flow, and logout revocation does
  not survive a process restart or span replicas.
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
  strict-origin-when-cross-origin`, and a CSP (`default-src 'self'`,
  style `unsafe-inline` only -- required by Tailwind-injected
  styles; no script `unsafe-inline`/`unsafe-eval` for app code, but
  see the Phase F note: CSP allows `'unsafe-inline'` scripts for
  Next.js hydration; a nonce-based CSP is a follow-up, not done).
- Errors to clients are typed and safe: ingestion failures return
  422/502/500 with a safe message, never raw exception text (a
  sentinel-string test proves this); full errors are logged
  server-side with `exc_info`.

## Scan results -- NOT clean, read this before deploying

### Bandit (Phase G run, same result as Phase E)

`bandit -r app`: **11 Low, 0 Medium, 0 High.** All Low findings are
documented false positives / intentional: the dev-only secret string
(production refuses it), best-effort `try/except/pass` shutdown and
cleanup blocks (now annotated with `# noqa` reasons where they are
intentional), the literal `token_type="bearer"`, and pre-existing
`assert` uses in MMR code. No bandit finding was hidden with a
blanket ignore.

### pip-audit (Phase G run)

`pip-audit -r requirements.txt`: **71 vulnerability records across
12 dependencies** -- the same count Phase E recorded. Affected
packages include `python-jose`, `python-multipart`, `starlette`
(via FastAPI 0.111), `markdown`, `pdfminer-six`, `python-dotenv`,
and LangGraph transitive deps (`langchain-core`, `langgraph`,
`langgraph-checkpoint`, `langsmith`, `ecdsa`); `pytest` records are
dev-only.

**Accepted risk, with conditions (review note):** these are NOT
upgraded in Phase G, because changing FastAPI/starlette/LangGraph
pins is a dependency-upgrade task that needs its own full retest
(pytest + compose smoke + a manual chat pass), and the app has no
public deployment yet. This acceptance is valid **only while the app
is not publicly deployed**. Before any public deploy, the upgrade
must happen and this section must be rewritten with the new counts.
Review/expiry: revisit at the next Dependabot cycle and in any case
before v1.1.0 or before a public URL is announced, whichever comes
first. Dependabot is configured (`.github/dependabot.yml`, weekly)
and its PRs must be reviewed, never auto-merged, for exactly this
reason.

### npm audit

Not run cleanly in the Phase G sandbox (registry audit endpoint
returned 403 -- a sandbox policy, not a clean result). It runs in CI
as a non-blocking job (`frontend-security`, `--audit-level=moderate`).
The first CI run reported **15 vulnerabilities (3 moderate, 11
high, 1 critical)**, including the known `next@14.2.5` security
update (upstream patch available, noted since Phase E). The job is
non-blocking by design, so this result is visible on every PR, not
hidden -- and the Next.js upgrade belongs with the dependency pass
above, before any public deploy.

## What is still open (security follow-ups)

- Nonce-based CSP (replacing the hydration `'unsafe-inline'`).
- Refresh-token flow (replacing single-token logout revocation).
- Redis-backed rate limits / denylist / quotas for multi-instance
  deployments (current ones are single-instance).
- Dependency upgrade + retest (see pip-audit accepted risk above).
- A public-deploy security review pass after that upgrade.
