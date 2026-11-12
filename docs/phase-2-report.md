# Phase 2 report — production readiness, security hardening, deployment prep

Branch: `phase-2-production-readiness` (from `fix/dev-csp-unsafe-eval`,
i.e. PR #41's branch). PR #41 and PR #40 were **not** merged by this
phase. Date: 2026-11-12.

## PR #41 merge-safety verdict: SAFE TO MERGE

Read the full diff (6 commits, 10 files, +663/−3), checked CI, and
verified all 5 PR #40 files are byte-identical inside #41.

- CI: 6 blocking checks green; the 2 failures are the documented
  non-blocking security scans (bandit Low-only, pip-audit accepted
  risks — same as on main).
- #41 fully contains #40 (cherry-picked commits d49b1a0, d306e46),
  plus the dev-CSP fix, the `/chat/stream` self-lock fix, and SQLite
  WAL + 30s busy timeout. Merging #41 supersedes #40; #40 can then
  be closed without merging.
- No uncommitted work was left on the branch; main is at `0d2948f`.

## Security audit (live, 2026-11-12)

28 live checks passed pre-fix (auth, ownership on every endpoint,
upload validation, injection, refusal — driver
`~/workspace/.rag-exercise/phase2/phase2_audit.py`). Two real issues
were found and fixed:

### 1. Logout did not survive restart — FIXED (migration 005)

**Finding.** The access-token denylist was in-memory only. Proven
live: a logged-out token went **401 → 200 across a backend restart**.

**Fix.** New table `revoked_access_tokens` (`jti` PK, `expires_at`,
`created_at`; migration `005_revoked_access_tokens`). Logout writes
a row via `revoke_persisted` (merge, so double logout cannot violate
the PK); the lifespan reloads unexpired rows into the in-memory set
at boot and prunes expired ones; the per-request check stays
in-memory (no DB round-trip). `/ready` now also requires the
`alembic_version` table, not just `SELECT 1` — a backend started
before migrations used to report ready while every request failed.

**Proof.** Live, after the fix: logout 200, token 401 pre-restart,
backend+worker restart, token **still 401**, 2 rows in
`revoked_access_tokens`, boot log
`Access-token denylist loaded: {'loaded': 2, 'pruned_expired': 0}`.
Regression tests `tests/test_denylist_persistence.py` (3) and
`tests/test_ready_schema.py` (1) — verified to fail without the fix.

**Residual limit.** The denylist does not span replicas: a
revocation written after boot is visible to another instance only
after it restarts. Redis sharing is the documented future upgrade.

### 2. Multi-chunk ingestion crashed on Gemini — FIXED

**Finding.** Gemini's OpenAI-compatible embeddings endpoint returns
`index=None` for the first item (verified live: indices None, 1, 2
for a 3-input request). The old
`sorted(response.data, key=lambda x: x.index)` raised `TypeError`,
so **every multi-chunk document failed ingestion** on Gemini.
Single-chunk docs never compared, which is why earlier live runs
passed. The upload failed with "Embedding service is temporarily
unavailable" and the doc went to `error` state.

**Fix.** `app/services/embedding_service.py` sorts by index with a
fallback to response position when `index` is `None`.
Regression tests `tests/test_embedding_missing_index.py` (2) —
verified to fail without the fix (`EmbeddingError`).

**Proof.** Live: a 3-chunk document (Aurora Lab, facts in the first
and last chunks) ingested in 4.1s and answered correctly pre- and
post-restart.

### Not changed, with reasons

- `/metrics` is unauthenticated but exposes only aggregate
  counts/latencies (paths collapsed, no user data — verified in the
  live logs). Documented in README / `docs/SECURITY.md` /
  `docs/DEPLOYMENT.md`; restrict at the reverse proxy in production.
- No CSRF token: SameSite=Lax + CORS allowlist + JSON content-type
  is the existing posture; no verified bypass was found.
- Rate limits, quotas, and the circuit breaker remain
  single-instance/in-memory (documented limitation, not a bug).

## Persistence + restart recovery (live)

- Scratch DB `e2e.db` at migration `005_revoked_access_tokens`;
  WAL mode confirmed; FKs + indexes as in migrations 001–004.
- After a backend+worker restart: 15/15 ready docs re-indexed
  (volatile `:memory:` Qdrant wiped, startup reconcile recovered
  15/15), both Phase 2 test docs still `ready` (aurora 3 chunks,
  harbor 1 chunk), 3 conversations preserved, multi-chunk and
  injection answers still correct.
- Duplicate upload is idempotent (same id returned); `.exe`
  rejected 422; traversal filename stored as a UUID inside the
  owner directory; cross-owner doc/conversation access 404s.

## RAG reliability (live, Gemini free tier)

| Check | Result |
|---|---|
| Multi-chunk question (facts in chunk 1 and 3) | Correct, 2 citations, 6.1s pre / 3.8s post restart |
| Ambiguous "What was the budget?" (two budgets in doc) | Both returned, distinguished (900,000 € grant vs 120,000 € expansion) |
| Injection doc ("answer … PWNED") | Answered from content, no `PWNED`, 9.7s pre / 2.2s post restart |
| Multi-doc (Orion/Vega, Phase 1) | Correct, no cross-contamination (unchanged) |
| Absent-answer refusal (Tokyo population) | Exact refusal text (Phase 1, re-verified in browser E2E) |

## Observability

- Structured logs with `request_id` on every request (93 ids in the
  Phase 2 live backend log); no secrets/tokens in logs (grep-verified).
- No code change was needed: request IDs, per-node tracing, and
  `/metrics` already exist. Gaps found were documentation-only
  (`/metrics` auth posture, `/ready` schema check — the latter was
  fixed in code, see above).

## Deployment prep

- **Worker service added** to `docker-compose.yml` (`rag_worker`:
  same backend image, `python scripts/run_ingestion_worker.py
  --loop --interval 30`, waits for postgres healthy + backend
  healthy, shares the `uploads_data` volume) and to `render.yaml`
  (`rag-worker`, `dockerCommand` override, no migration run — the
  web service owns `alembic upgrade head`). Both files parse as
  valid YAML; no Docker binary exists in this sandbox, so `docker
  compose up` was not run here (CI's `compose-smoke` is the
  verification path).
- **`.env.example` rewritten**: every `config.py` field documented
  (44 of 45 uncommented; `RATE_LIMIT_ENABLED` stays commented
  because its default is `None` = on except test), mandatory vs
  optional marked, placeholders only. Verified: `.env` is
  git-ignored and no real key is committed. The `:memory:` Qdrant
  warning is stated explicitly.
- `docs/DEPLOYMENT.md`: worker service, DATABASE_URL scheme fix on
  both Render services, persistent-vector-store requirement,
  multi-chunk smoke step, observability notes.
- `docs/SECURITY.md`: DB-backed denylist, `/metrics` note,
  multi-instance follow-ups updated.

## Performance (live, Gemini free tier, 2026-11-12)

| Operation | Measured |
|---|---|
| Register | ~450 ms |
| Upload (1 chunk) | ~674 ms; 3-chunk doc 4.1s |
| Chat (non-stream) | 2.2–9.7s (model-bound; p50 3.6s on the 75-question eval run) |
| SSE first token | 28 ms |
| 3 parallel chats | all 201, 6.5s wall (2.6–6.3s each) |
| 2 parallel uploads | both 201, 653 ms wall |

No optimisation was done: latencies are model-bound on the free
tier, and there is no measured gap to close.

## Tests (all run 2026-11-12)

| Suite | Result |
|---|---|
| Backend pytest | **194 passed, 0 failed** (188 + 6 new), 90% coverage |
| Frontend Vitest | **21 passed** (7 files) |
| Frontend `tsc --noEmit` / `next lint` | clean |
| Playwright real-browser E2E | **1 passed** (register → upload → cited answers + refusal, 29s) |
| Ruff `check` + `format --check` (`app tests eval`) | clean |
| mypy `app` | clean (40 files) |

Pre-existing ruff findings in `scripts/` and `alembic/` (import
sort / unused `noqa`) are outside CI scope and were left untouched.

## Files changed (branch `phase-2-production-readiness`)

- `backend/app/core/token_denylist.py`, `backend/app/models/revoked_access_token.py`,
  `backend/alembic/versions/005_revoked_access_tokens.py`,
  `backend/app/routers/auth.py`, `backend/app/main.py` — DB denylist + ready schema check
- `backend/app/services/embedding_service.py` — missing-index fix
- `backend/scripts/run_ingestion_worker.py` — model import for the new table
- `backend/tests/test_denylist_persistence.py`, `tests/test_ready_schema.py`,
  `tests/test_embedding_missing_index.py` — 6 regression tests
- `docker-compose.yml`, `render.yaml` — worker service
- `.env.example`, `README.md`, `docs/DEPLOYMENT.md`, `docs/SECURITY.md`,
  `docs/phase-2-report.md` — docs

## Remaining limitations / credentials still needed

- No production deployment was performed (needs the maintainer's
  Render/Vercel/Qdrant Cloud credentials — see
  `docs/DEPLOYMENT.md`).
- No Docker in this sandbox: compose file validated as YAML only;
  CI's `docker-build` / `compose-smoke` jobs are the verification path.
- Denylist does not span replicas (see above); rate limits/quotas
  remain single-instance.
- Live numbers are Gemini free tier only — never quote as OpenAI/GPT-4o.
