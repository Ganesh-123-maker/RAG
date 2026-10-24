# Changelog

All notable changes to this project are documented here. Phase PRs
are linked by number once merged; while stacked, their bases are
noted. Version 1.0.0 is the first tagged release, covering Phases
A-G. No live evaluation or live deployment numbers are claimed in
this changelog -- see `docs/EVALUATION.md` and `docs/DEPLOYMENT.md`.

## [Unreleased]

- (Phase G items land here until v1.0.0 is tagged; see below.)

## [1.0.0] -- Phases A-G

### Phase A -- Correctness (PR #1, branch `phase-a-correctness`)
- Embedding failures raise a typed error instead of returning
  SHA-256 fallback vectors; ingestion marks documents `error` with
  a safe message and cleans up files and vectors.
- One RAG path: `/chat` and `/chat/stream` both run the same
  LangGraph service (same planner, prompt, history window,
  citations); streaming emits `status`/`token`/`citations`/`done`/
  `error` and persists the assistant message even on disconnect.
- Planner direct-answer branch for chit-chat/no-retrieval
  questions; planner system prompt + validated JSON schema.
- Fresh-clone Docker boot fixed (frontend `public/`, `.env`
  optional, backend CMD, `.dockerignore`s, `/health` + `/ready`).
- Owner-scoped repositories, chat `document_id` ownership/status
  check, 401 (not 500) for malformed JWT `sub`, `is_active`
  enforcement, safe error responses.
- Startup uses Alembic migrations (`entrypoint.sh`), not
  `create_all()`.

### Phase B -- RAG Quality (PR #2, branch `phase-b-rag-quality`)
- PDF page numbers, MD/DOCX headings, DOCX tables as text,
  scanned-PDF detection with a clear error; magic-byte validation
  and size-streamed uploads; threadpool parsing/tokenizing.
- Sentence/paragraph-aware chunking with char offsets, page,
  section, chunk index, and content hash in the Qdrant payload.
- Content-hash dedupe per owner; chunk-level dedupe.
- Similarity threshold (0.30, unmeasured default), fetch-k 20 +
  MMR (λ 0.7) to top-k 5, shared empty/low-confidence refusal,
  collection-dimension mismatch detection.
- Delimited, data-marked context; chunk-id citations with
  validation; context/history token budgets and `max_tokens`.

### Phase C -- Agentic Architecture (PR #3, branch `phase-c-agentic`)
- Graded LangGraph: planner -> retriever -> grade -> [rewrite +
  retry once] -> reasoning -> verify -> [regenerate once] ->
  response, plus direct-answer branch. State extended with
  errors, retries, scores. Graph diagram in `docs/graph.mmd`.
- LangChain removed from requirements (it was declared but never
  imported); README corrected to match.

### Phase D -- Real Evaluation (PR #4, branch `phase-d-evaluation`)
- Deleted the simulated `scripts/evaluate_rag.py` and the fake
  `eval_metrics_report.*`.
- Built `backend/eval/`: 10 self-written documents, 55 golden
  questions, 16 unanswerable probes, 6 injection probes, and a
  runner measuring hit-rate@k, MRR, judge correctness (live only),
  faithfulness (hand-rolled overlap), citation precision, refusal
  accuracy, latency, and estimated cost.
- Ran two offline smoke runs only (`docs/eval/offline-smoke-1/`,
  `docs/eval/offline-smoke-threshold-off/`), labelled as pipeline
  smoke, not quality. Live run BLOCKED pending a valid
  `OPENAI_API_KEY`. Hybrid search / reranker NOT implemented for
  lack of live data to justify them.

### Phase E -- Production Hardening (PR #5, branch `phase-e-hardening`)
- DB-backed ingestion queue (queued/processing/ready/error),
  progress, retry on embedding failure, worker + orphan
  reconciliation script.
- httpOnly + SameSite cookies, logout denylist, login lockout,
  aligned lifetimes (cookie Max-Age 3600 = JWT 60 min); refresh
  tokens deferred.
- In-memory rate limits and per-user daily quotas; structured
  JSON logging with request IDs; Prometheus-text `/metrics`;
  per-node tracing logs; optional Sentry hook; circuit breaker
  around Qdrant search; timeouts/retries; graceful shutdown.
- Pydantic-settings validation and startup checks (key present,
  dimensions match collection).
- Security review: bandit 11 Low / 0 Medium / 0 High; pip-audit
  71 records documented as accepted risk for Phase G; XSS review
  (no raw HTML execution); security headers.

### Phase F -- Frontend & UX (PR #6, branch `phase-f-frontend`)
- Single typed API client, 401 interceptor redirecting to login,
  fixed register auto-login content type, error toasts, loading
  skeletons.
- Streaming UX: stop/cancel, retry, regenerate, copy, sanitised
  Markdown + code rendering, citation chips opening a source
  panel, conversation rename/delete, document status/progress,
  drag-and-drop upload with validation.
- Responsive/mobile sidebar, keyboard/ARIA basics, dark-only
  theme (slate-500 secondary text at 4.0:1, below WCAG AA --
  documented limitation).
- Vitest + React Testing Library (17 tests) and Playwright E2E
  (signup -> upload -> ask -> cited answer, mock-API mode).

### Phase G -- CI/CD, Deployment, Docs (PR #7, branch `phase-g-cicd-docs`)
- CI rewritten: backend pytest with a measured 80% coverage gate,
  blocking Ruff, non-blocking mypy (14 pre-existing errors) and
  security scans, frontend lint/typecheck/Vitest/`next build`/
  Playwright E2E, Docker builds for both images, compose smoke
  test (`/health` + `/ready`, test key only), Dependabot,
  pre-commit config. Static 97% coverage badge removed.
- Deployment config: Render `render.yaml` (backend + Postgres)
  and documented Vercel settings (frontend); Qdrant Cloud free
  tier. **Live deploy NOT performed** -- no credentials were
  available; `docs/DEPLOYMENT.md` lists exactly what to provide.
- Documentation rewritten honestly: README without the synthetic
  benchmark table, `docs/ARCHITECTURE.md`, `docs/EVALUATION.md`,
  `docs/SECURITY.md`, `docs/DEPLOYMENT.md`, `CONTRIBUTING.md`,
  this changelog, `docs/RESUME.md`, generated `docs/openapi.json`
  (14 paths), Makefile, demo seed script, MIT `LICENSE` file
  (README already claimed MIT; the file itself was missing).
- Cleanup: unused `zustand` dependency removed; backend Ruff
  clean (auto-fixes + config for the FastAPI `Depends` idiom).
- Compose fix found by CI: Qdrant healthcheck removed (image
  ships no wget/curl; it made `docker compose up` report Qdrant
  unhealthy forever) in favour of an entrypoint readiness wait
  plus `/ready`; CI smoke start step dumps logs on failure.
- Measured Phase G results: backend 122 passed / 91% coverage,
  frontend 17 Vitest passed, `tsc`/`lint` clean, `next build`
  7 pages, Playwright E2E 1 passed (mock-API). Docker builds and
  compose smoke were not run in the sandbox (no Docker); CI
  covers them.

## Notes on versioning

Versions before 1.0.0 were untagged development on `main`
(head `d5322f4` at the Phase A starting point). Phase branches
A-G were stacked and merged in order for v1.0.0; see the PRs
above and `docs/phase-g-report.md` for the merge record.
