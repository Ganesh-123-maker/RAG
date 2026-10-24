# Phase E — Production Hardening: Report

Branch: `phase-e-hardening` (from `phase-d-evaluation`, stacks on PR #4).
No changes were made to `main`, `phase-a-correctness`,
`phase-b-rag-quality`, `phase-c-agentic`, or `phase-d-evaluation`;
no history was rewritten, no force-push was used, and no secrets,
`.env`, `uploads/`, `node_modules/`, or build output were committed.
Phase A–D behaviour is preserved: one LangGraph path, threshold +
MMR, chunk-id citations, graded graph, and the real eval runner
are untouched except for the additive changes below.

## Decisions and their limits (read before judging the phase)

### E1 — DB-backed ingestion queue, NOT FastAPI BackgroundTasks
BackgroundTasks were rejected on purpose: a task is lost on
restart and has no durable status, so it cannot honestly provide
`queued -> processing -> ready/error`. Instead the document row
itself is the queue: `ingest()` creates the row as `queued`
(progress 0) and commits it, then processes it
(`queued -> processing -> ready/error`, progress 10/30/50/80/100).
`DocumentService.process_queued_documents()` plus
`backend/scripts/run_ingestion_worker.py --once/--loop` is the
recovery path for rows left `queued` by a crash (a queued row
whose file is gone is marked `error`, not crashed on).
**Limit:** the common path still processes synchronously inside
the upload request (the worker is recovery, not the primary
path); a true async worker pool is a later scaling step, and
the worker is single-instance (no distributed lock).
**Retry, corrected during development:** the first implementation
retried *every* failure, which double-ran cleanup on a
post-upsert failure and broke a Phase A test. The shipped
policy retries ONLY embedding failures (bounded, default 2
attempts total); every other failure cleans up once and fails.
That failure is what the retry requirement actually covers
(transient provider outage), and the test now passes unchanged.

### E2 — httpOnly cookies + denylist logout; refresh DEFERRED
The backend now sets the auth cookie itself on login
(`httpOnly` always, `Secure` only in production — Secure
cookies are not sent over plain localhost http and would break
local dev, `SameSite=Lax`, `max_age` exactly the 60-minute JWT
lifetime, fixing the old 1-day-cookie vs 60-minute-token drift).
The frontend no longer reads or writes any token in JS
(`js-cookie` usage removed from all pages/components; the
browser sends the cookie automatically on same-origin requests,
and Bearer auth is kept server-side for API clients). The
landing page no longer presence-checks a token (impossible
with httpOnly cookies); the dashboard proves auth via
`GET /me`. Register auto-login now posts JSON, fixing the old
FormData-through-a-JSON-hardcoded-axios 422 risk.
**Refresh tokens were deliberately NOT shipped:** rotation +
reuse detection is easy to get wrong, and a half-built refresh
flow is worse than a documented deferral. Instead, logout
revokes the current token via an in-memory denylist keyed by
`jti` (tokens now carry a `jti`) and clears the cookie.
**Limit of the denylist:** in-memory and single-instance,
cleared on restart; the window is bounded because access
tokens live only 60 minutes. A persistent denylist (DB/Redis)
is the multi-instance upgrade.
**Lockout:** 5 failed logins in a row locks the account for
15 minutes (configurable), returning 429 with `Retry-After`;
the counter commit is explicit because `get_db` rolls back on
HTTPException, which would otherwise silently discard it.
**Password policy:** kept at >= 8 characters. Existing tests
assume 8, and silently strengthening it here would break the
documented policy without a migration story; any stronger
policy belongs in Phase F/G with the tests updated openly.
**CORS:** origins come from config only; `*` with credentials
fails startup in production and warns loudly elsewhere
(validator in `config.py`, tested).

### E3 — In-memory rate limiting and quotas (single-instance)
`app/core/rate_limit.py` (fixed-window, per-minute: auth 10,
upload 10, chat 30) and `app/core/quotas.py` (per-user daily:
200 chat requests, 200k *estimated* tokens) both return 429
with `Retry-After`. **Limits, stated plainly:** counts are
in-process and lost on restart; a multi-replica deployment
would enforce per replica, not globally. Redis is the upgrade
if horizontal scaling is ever needed, and it was NOT added
here because it would also have to not break the no-Redis
local path. The limiter defaults off in `ENVIRONMENT=test`
(the suite makes many calls as one user in one process);
rate-limit tests enable it explicitly. The token budget is an
*estimate* (chars/4) because the agent service does not return
metered usage — it is a cost guard, never a billing number.

### E4 — Observability: logs, minimal metrics, log tracing
- Request IDs: pure ASGI middleware generates/propagates
  `X-Request-ID`, echoes it on the response, and logs one JSON
  line per request (method, path with UUIDs collapsed,
  status, duration). It does not buffer bodies, so SSE passes
  through unchanged.
- `/metrics` renders Prometheus *text format* from in-process
  counters/histograms. This is deliberately NOT claimed to be
  a prometheus_client integration: no new dependency was
  added, and the endpoint is documented as minimal.
- Tracing: `app/core/tracing.py` `trace_span` logs one line per
  graph node (nodes are wrapped in `_build_graph`, node logic
  untouched). No LangSmith/Langfuse key is required to boot;
  the span boundaries are the documented extension point for
  a real tracer.
- Sentry: optional and env-gated (`SENTRY_DSN`); absent means
  no-op, and an SDK import failure never breaks boot.

### E5 — Reliability
- Circuit breaker (`app/core/circuit_breaker.py`): Qdrant
  search fails fast after N consecutive failures (default 3,
  60s cooldown, half-open trial). The agent's retriever already
  maps any retrieval exception to `AgentError` -> 502, so the
  breaker changes timing, not error semantics. Embeddings keep
  Phase A's tenacity retries; the breaker was not layered on
  top of them (double retry budgets would be worse).
- Graceful shutdown: lifespan shutdown best-effort closes the
  OpenAI/Qdrant clients and disposes the engine.
- Orphan reconciliation: `backend/scripts/reconcile_orphans.py`
  is dry-run by default; `--apply` deletes orphan *files*
  only; `--apply-vectors` is a separate explicit flag for
  orphan Qdrant points. The Qdrant scan is sampled (`--limit`,
  default 1000) — a full scan of a large collection is not
  attempted, and the report says so.

### E6 — Config validation and startup checks
`config.py` now validates: all rate/lockout/budget values
positive, `RETRIEVAL_TOP_K <= RETRIEVAL_FETCH_K`,
`CHUNK_OVERLAP < CHUNK_SIZE`, CORS wildcard rules above, and
the existing dimension/threshold validators. Startup
(`main.py` lifespan) raises if `OPENAI_API_KEY` is missing
outside `ENVIRONMENT=test`; the collection-dimension check
already lived in `ensure_collection()` (Phase B) and is
unchanged. Production still fails loudly without a real
`JWT_SECRET_KEY`; the dev-only secret remains local-dev-only.
A grep for hardcoded secrets found only the documented
dev-only secret (bandit flags it as Low; see E7).

### E7 — Security review
- **pip-audit** (installed in the sandbox venv, not committed):
  71 vulnerability records across direct and transitive
  pinned dependencies (notably `python-jose`, `python-multipart`,
  `starlette` via FastAPI 0.111, and `langchain-core` /
  `langsmith` transitively via `langgraph`). These were NOT
  upgraded in this phase: changing FastAPI/LangGraph pins is a
  dependency-upgrade task that needs its own full retest, and
  the app has no public deployment yet. This is a documented
  accepted risk for Phase G (dependency upgrade + retest),
  not a silent ignore — the counts and the reason are recorded
  here.
- **bandit** (`bandit -r app`): 11 Low, 0 Medium, 0 High. All
  Low findings are documented false positives / intentional:
  the dev-only secret string (production refuses it), four
  `try/except/pass` best-effort shutdown/cleanup blocks,
  the literal `token_type="bearer"`, and two pre-existing
  `assert` uses in MMR code. No bandit finding was fixed by
  code change because none is a real vulnerability; adding
  `#nosec` comments to hide them would be worse than this
  record.
- **npm audit**: UNAVAILABLE in this sandbox — the registry
  audit endpoint returns 403 (sandbox registry policy), not a
  clean result. Recorded as unavailable, not as clean. Note:
  `npm ci` did succeed and printed deprecation/security
  warnings for `next@14.2.5` (upstream security update
  available) — the Next.js upgrade belongs with the Phase G
  dependency pass.
- **XSS review:** no `dangerouslySetInnerHTML`, no `innerHTML`,
  no `rehype-raw` anywhere in the frontend. Document names
  render as React text (escaped by React); answers render via
  `ReactMarkdown` + GFM with no raw-HTML plugin, so embedded
  HTML in an answer is not executed. `rehype-sanitize` was NOT
  added: it is belt-and-braces on top of an already
  non-executing path, and adding it without frontend tests
  (Phase F) risks breaking markdown rendering silently. The
  residual risk and the Phase F follow-up are recorded here.
- **Frontend security headers** (`next.config.js`): 
  `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: strict-origin-when-cross-origin`, and a
  minimal CSP (`default-src 'self'`, style `unsafe-inline`
  only — required by Tailwind-injected styles, no script
  `unsafe-inline`/`unsafe-eval`). Verified by a successful
  `next build` (see Tests), not just by reading the config.

## What changed (files)

Backend (new): `app/core/rate_limit.py`,
`app/core/circuit_breaker.py`, `app/core/token_denylist.py`,
`app/core/tracing.py`, `app/core/observability.py`,
`app/core/quotas.py`, `scripts/run_ingestion_worker.py`,
`scripts/reconcile_orphans.py`, `alembic/versions/003_phase_e.py`.
Backend (changed): `core/config.py` (E6 fields + validators),
`core/security.py` (jti, cookie helpers), `core/dependencies.py`
(Bearer-or-cookie auth, denylist check), `main.py` (middleware,
`/metrics`, startup key check, graceful shutdown, optional
Sentry), `routers/auth.py` (cookie login, logout, rate limits),
`routers/documents.py` (upload rate limit),
`routers/chat.py` (chat rate limit + daily quota),
`services/auth_service.py` (lockout), `services/document_service.py`
(queued/progress/retry-on-embedding-failure/worker),
`services/vector_store_service.py` (circuit breaker on search),
`services/agent_service.py` (traced node wrappers only),
`models/document.py` + `models/user.py` (new columns),
`repositories/document_repository.py` (queued/status/progress),
`repositories/user_repository.py` (lockout counters),
`schemas/document.py` (progress/attempts in responses),
`.env.example` (documented Phase E settings).
Frontend (changed, minimal): `lib/api.ts` (cookie-based auth,
no JS token), `app/login/page.tsx`, `app/register/page.tsx`
(JSON login, no cookie writes), `app/dashboard/page.tsx`
(no cookie guard, server logout), `app/page.tsx` (no token
check), `components/ChatPanel.tsx` (no token header),
`next.config.js` (security headers). `js-cookie` usage is
gone from all app code (the package remains in
`package.json`; removing the dependency is Phase F cleanup).

## Tests

New `backend/tests/test_phase_e.py` (15 tests): rate-limit
429 + `Retry-After` (unit and upload endpoint), lockout after
5 failures (429 + `Retry-After`), httpOnly cookie flags
(`HttpOnly`, `SameSite=lax`, `Max-Age=3600`, no `Secure` in
test env) + logout revocation (cookie auth then 401 after
logout), request-ID header + `/metrics` Prometheus text,
CORS wildcard rejected in production, production JWT secret
required, top-k/fetch-k ordering, circuit breaker
open/half-open/recovery (unit + Qdrant search fail-fast with
no third call), daily quota enforcement, reconcile pure
functions, worker queued->ready with progress 100, upload
response carrying progress/attempts, tracing span log.
Full suite (proxy vars cleared, per the branch note):
**117 passed, 0 failed** (102 baseline + 15 new). Two
regressions found and fixed during development (retry policy
narrowed to embedding failures; register rate limit keyed by
email to avoid changing the direct-call signature) — no
existing test was weakened; the Phase A cleanup test passes
unchanged.
Ruff: `ruff check` + `ruff format --check` clean on all new
Phase E modules and the test file. (Pre-existing ruff hits
elsewhere in the repo are Phase G's config job, as before.)
Alembic: fresh SQLite `alembic upgrade head` applies
001 -> 002 -> 003 and the new columns exist.
Smoke test (uvicorn, SQLite file DB, in-memory Qdrant):
`/health` 200, `/ready` 200, `/metrics` returns counters,
`X-Request-ID` present on responses.
Frontend: `npx tsc --noEmit` clean, `npm run lint` clean,
`npm run build` succeeds (7 static pages). `node_modules/`
and `.next/` were removed after the build and are not
committed. Docker was not available in this sandbox, so
`docker compose build` was NOT run here — same caveat as
Phases A–D, to verify on a Docker machine before merging.

## Known limitations (do not over-claim)

- Rate limiting, quotas, denylist, metrics, and the worker are
  single-instance and in-memory where noted; they do not
  survive restart (except the DB queue itself) and do not
  span replicas.
- Refresh tokens are deferred (see E2); logout revokes only
  the current token, in this process.
- The daily token budget is an estimate, not metered usage.
- pip-audit findings (71 records) and the Next.js security
  update are deferred to Phase G's dependency pass with a
  full retest — the app must not be publicly deployed on the
  current pins without that pass.
- npm audit could not run in this sandbox (registry 403).
- Frontend cookie behaviour (Set-Cookie through the Next.js
  rewrite proxy) is code-reviewed and unit-tested at the
  backend, not browser-verified here; Phase F's Playwright
  E2E is the place that proves it end to end.
