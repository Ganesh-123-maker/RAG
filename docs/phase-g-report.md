# Phase G — CI/CD, Deployment, Docs: Report

Branch: `phase-g-cicd-docs` (from `phase-f-frontend` @ `663dfae`).
No history was rewritten, no force-push was used, and no secrets,
`.env`, `uploads/`, `node_modules/`, or build output were committed.
Staged files were grep-checked for key material before committing
(no secret was found; see Verification).

## What Phase G is, and is not

Phase G finishes the project's honesty and delivery surface: CI that
actually gates, deployment config that is real but not fabricated,
and docs whose every number is measured or explicitly marked
unmeasured. It does **not** claim a live deployment, a live
evaluation, clean scans, or mypy-clean code -- all four are
explicitly recorded as not done, with reasons and next steps.

## G1 -- CI (`.github/workflows/ci.yml`, rewritten)

Jobs (8): `backend-tests`, `backend-lint`, `backend-mypy`,
`backend-security`, `frontend`, `frontend-security`, `docker-build`,
`compose-smoke`. Dependency caching is on for pip (backend) and npm
(frontend). Triggers: pushes to `main`/`master`/`develop`/`phase-*`
and PRs to `main`/`master`.

- **Backend tests (blocking):** Python 3.11, SQLite in-memory,
  in-memory Qdrant, placeholder OpenAI key (all OpenAI calls are
  mocked in tests). Coverage gate: `--cov-fail-under=80`, plus
  `fail_under = 80` in `backend/pyproject.toml`. Measured on this
  branch: **91%** (see Verification), so the 80% gate is not a
  fake threshold -- it is below the measured value and will fail
  on a real regression. Coverage artifact is uploaded; Codecov
  upload is optional/non-blocking (no Codecov token is configured,
  so no Codecov badge is claimed).
- **Backend lint (blocking):** `ruff check` + `ruff format --check`
  on `app tests eval`. To make this honestly blocking, Phase G
  applied ruff's safe auto-fixes (62 fixes: unused imports,
  modernised annotations/imports) plus `ruff format` across the
  backend, then fixed the remaining 27 hits by hand: intentional
  best-effort `except: pass` sites now carry `# noqa` with a
  reason, the main.py nested-if was collapsed, and unused test
  variables were underscore-prefixed. A `[tool.ruff]` config was
  added: `target-version = "py311"` and `ignore = ["B008"]`
  (FastAPI `Depends()` in argument defaults is the documented
  FastAPI idiom, not a bug). No rule was loosened to hide a real
  issue: an earlier attempt to select the full `E` rule set
  surfaced 58 E501/B904/UP042 hits on long Prometheus lines and
  similar pre-existing style; that expansion was reverted, because
  reformatting the whole codebase to an 88-column limit is a
  separate style decision, not a Phase G correctness fix. The
  config documents that the default rule set is used.
- **mypy (NON-BLOCKING, `continue-on-error: true`):** `mypy app
  --ignore-missing-imports` with `mypy==2.4.0` and a minimal
  `[tool.mypy]` config (`python_version = "3.11"`,
  `ignore_missing_imports = true`). Result: **14 errors in 9
  files, NOT clean** (config.py Settings call-arg; database.py
  dict-item types; models name-defined for relationship strings;
  chunking_service assignment; vector_store_service Filter
  variance; agent_service OpenAI message types / async-iterable
  union; main.py `/metrics` return type). Code was NOT weakened
  to pass mypy, and mypy-clean is NOT claimed anywhere. The job
  exists so the count is visible on every PR until fixed.
- **Backend security (NON-BLOCKING):** bandit + pip-audit, both
  with `continue-on-error: true` because their results are not
  clean (see docs/SECURITY.md). Non-blocking here means "visible
  but not gating", not "ignored": findings are documented with
  counts, reasons, and a review note.
- **Frontend (blocking):** Node 20, `npm ci`, `tsc --noEmit`,
  `npm run lint`, Vitest, `next build`, Playwright chromium
  install, then Playwright E2E in mock-API mode. The server and
  the tests share one step on purpose: a background process
  started in one Actions step is not guaranteed to survive into
  the next step. E2E mode is `E2E_RUN=1 E2E_MOCK_API=1` (no OpenAI
  key needed); the docker-stack E2E mode (`E2E_MOCK_API=0`) is
  not run in CI because the stack is not up in that job -- it
  remains a manual step documented in the Phase F report.
- **Frontend security (NON-BLOCKING):** `npm audit
  --audit-level=moderate`, non-blocking because its sandbox result
  was unavailable (registry 403) and its CI result is therefore
  unknown until a run reports it.
- **Docker builds (blocking):** `docker build ./backend` and
  `docker build ./frontend` -- this is what catches the old
  missing-`public/` failure class in CI, since the frontend
  build job alone does not exercise the Dockerfile COPY.
- **Compose smoke (blocking, needs docker-build):** `docker
  compose up -d --build` with a test key (`OPENAI_API_KEY=
  test-smoke-key`, test JWT secret), waits up to 5 minutes for
  `/ready` to report `ready`, then checks `/health` and the
  frontend login page, then `docker compose down -v`. Limit,
  stated in the job and in docs/DEPLOYMENT.md: the placeholder
  key is presence-only (lifespan checks it exists; `/ready`
  checks Postgres + Qdrant only), so this proves boot, migration,
  and readiness -- **not chat**. A real chat smoke needs a valid
  key.
- **Dependabot** (`.github/dependabot.yml`, weekly, pip/npm/
  GitHub Actions, 5 PRs each): PRs must be reviewed, never
  auto-merged, because a FastAPI/LangGraph upgrade needs a full
  retest (see SECURITY.md accepted risk).
- **Pre-commit** (`.pre-commit-config.yaml`, ruff + standard
  hooks + private-key detection): configured only. It was NOT
  run over the whole history, per the brief.
- **Badges:** the static `Coverage-97%` shields badge is removed.
  The README keeps only the real CI workflow badge (which
  reflects the workflow in this file), the MIT license badge
  (now backed by an actual `LICENSE` file, see below), and
  informational Python/Next.js badges. No Codecov badge is used:
  Codecov is not configured, and a badge for an unconfigured
  service would be exactly the kind of fake badge Phase G exists
  to remove.

## G2 -- Deployment: attempted, NOT completed (credentials missing)

- **Chosen stack:** backend on Render (`render.yaml`, Docker web
  service + Render Postgres free tier), frontend on Vercel (no
  `vercel.json` -- Vercel needs no config file for Next.js, so
  inventing one would be decoration), Qdrant on Qdrant Cloud
  free tier. Justification and alternatives are in
  `docs/DEPLOYMENT.md`.
- **Credential check (presence only, nothing printed):**
  `OPENAI_API_KEY`, `VERCEL_TOKEN`, `RENDER_API_KEY`,
  `FLY_API_TOKEN`, `RAILWAY_TOKEN` were all **absent** from the
  sandbox environment. GitHub CLI auth exists (account
  `Ganesh-123-maker`, scopes `repo`/`workflow`), which is enough
  for PR/merge/release operations but not for deploying to
  Render or Vercel.
- **Therefore the live-deploy sub-task was stopped**, exactly as
  the brief instructs, and everything else continued. No live URL
  is claimed, no deployment was invented, and no URL was
  smoke-tested. `docs/DEPLOYMENT.md` lists exactly what the
  maintainer must provide: Render dashboard secrets
  (`OPENAI_API_KEY`, `JWT_SECRET_KEY`, `QDRANT_HOST`,
  `QDRANT_API_KEY`), the required `DATABASE_URL` scheme fix
  (`postgres://` -> `postgresql+asyncpg://`, because Render's
  `fromDatabase` string does not match the app's async driver),
  a Qdrant Cloud cluster, and Vercel project settings (Root
  Directory `frontend`, `BACKEND_URL` = Render backend URL --
  correcting the old guide's dead `NEXT_PUBLIC_API_URL` -- and
  the Vercel domain as a CORS origin). The old README's Render
  build/start commands and Qdrant port 6333 for cloud were also
  wrong and are corrected (Dockerfile CMD already runs Alembic
  then uvicorn; cloud port is 443).
- **Repo metadata via `gh`:** attempted after merging (see Merge
  section); if it fails, the suggested description/topics are
  recorded in the handoff, not fabricated as applied.

## G3 -- Documentation

- **README.md rewritten** (not patched): unified LangGraph with
  grade/retry/verify, threshold/MMR, chunk-id citations, httpOnly
  auth, ingestion queue, and the eval runner are described as
  they actually are. The old synthetic benchmark table (100%
  grounded / 0% hallucination / <1.5s / 97% coverage / 52
  documents indexed) is **removed**, as is the unverified Vercel
  "Production" link. The Evaluation section states the offline
  smoke results with their OFFLINE PIPELINE SMOKE ONLY label,
  states live eval is BLOCKED pending a valid key with the exact
  command, and reports test/coverage numbers from this phase's
  real runs (122 backend / 91%, 17 Vitest, 1 E2E). A Limitations
  section covers single-instance rate limits, in-memory quotas,
  overlap-based verify, dark-only theme, slate-500 contrast
  4.0:1, deferred refresh tokens, Docker smoke not run in the
  sandbox, live deploy pending credentials, mypy not clean, and
  scans not clean. The tech-stack table no longer lists
  `js-cookie` (removed from app code in Phase E) and states
  LangChain was removed in Phase C.
- **New docs:** `docs/ARCHITECTURE.md` (system + LangGraph
  Mermaid diagrams, reusing `docs/graph.mmd`; request flows;
  config reference with thresholds flagged as unmeasured
  defaults), `docs/EVALUATION.md` (corpus, golden set, runner,
  mode labels, reproduction commands, blocked live run, hybrid/
  reranker experiment), `docs/SECURITY.md` (auth, ownership,
  rate limits, CSP, rendering, scan results + accepted risks
  with review/expiry note), `docs/DEPLOYMENT.md` (see G2),
  `CONTRIBUTING.md`, `CHANGELOG.md` (Phases A-G with PR links).
- **Makefile** (cross-platform targets: `test`, `lint`, `build`,
  `up`, `down`, `eval-offline`, `eval-live`, `openapi`, `seed`,
  `clean`): the `.ps1` scripts are kept as optional and were not
  deleted. Note: `make test`'s backend command assumes a Python
  with the backend dependencies installed (a venv, as in the
  local-dev guide); it clears proxy variables including
  `NO_PROXY` for sandbox compatibility.
- **Demo seed script** (`backend/scripts/seed_demo.py`): creates
  a demo user (register then login -- register returns a
  UserResponse, not a token, which the first draft got wrong and
  was fixed against the real schemas) and uploads sample docs
  from the Phase D corpus via the API, printing per-document
  status. No secrets are hardcoded (password via flag, env, or
  prompt). It was **not run** in the sandbox (no running stack);
  its help text and `docs/phase-g-report.md` say so, and the
  command to run it is `make seed` against a running stack.
- **Demo screenshots/GIF: TODO, not faked.** No running stack
  exists in the sandbox to screenshot, so no screenshots or GIF
  are included. Exact steps to produce them (compose up, seed,
  upload, ask, screenshot dashboard + cited answer + source
  panel) are: `docker compose up -d --build`, `make seed`,
  open http://localhost:3000, register/login as the demo user,
  wait for documents to reach `ready`, ask a question from the
  corpus, screenshot the dashboard, the streamed cited answer,
  and the open source panel, and save them under `docs/demo/`.
  No stock images are used.
- **API reference:** `docs/openapi.json` generated for real with
  the new `backend/scripts/export_openapi.py` (FastAPI
  `app.openapi()`, 14 paths, no lifespan, no external calls).
  It is generated, not hand-written, and the script is committed
  so it can be regenerated.
- **LICENSE check:** the README claimed MIT, but **no `LICENSE`
  file existed** in the repo. A standard MIT `LICENSE` file
  (Copyright 2026 Barmavath Ganesh, matching the repo's author
  and commit dates) was added in this phase; the license type
  was not changed, only the missing file supplied. This is
  recorded here so the addition is not mistaken for a
  pre-existing file.

## G4 -- Resume (`docs/RESUME.md`)

5-6 bullets plus talking points, using only verified numbers:
122 backend tests / 91% coverage (gate 80%), 17 Vitest, 1 E2E,
10 corpus documents / 55 golden / 16 unanswerable / 6 injection,
offline smoke labelled as smoke, live numbers explicitly
pending. A "What NOT to claim" section lists the old synthetic
numbers, hybrid/reranker, semantic memory, and verified
deployment as unclaimable in v1.0.0.

## Cleanup in this phase

- Removed the unused `zustand` dependency from
  `frontend/package.json` (+ regenerated `package-lock.json`;
  0 references remain; no app code imported it). `js-cookie`
  was already absent from `package.json` by Phase F.
- Backend Ruff clean + formatted (see G1 for scope and the
  reverted E501 expansion).

## Verification (all runs on this branch, sandbox)

- **Backend pytest** (proxy vars cleared *including* `NO_PROXY`,
  `OPENAI_API_KEY=test-placeholder-key`, SQLite in-memory,
  Qdrant in-memory, test JWT secret, `ENVIRONMENT=test`):
  **122 passed, 0 failed; coverage 91%** (2052 statements, 175
  missed). The coverage gate (`--cov-fail-under=80`) passes.
- **Why `NO_PROXY` matters (sandbox artifact, not a code bug):**
  an earlier run that cleared only `HTTP(S)_PROXY`/`ALL_PROXY`
  failed 31 tests with `httpx.InvalidURL` when constructing the
  OpenAI client. Clearing `NO_PROXY`/`no_proxy` as well makes
  all 122 pass, and a direct client-construction test confirms
  it. The sandbox `NO_PROXY` list contains bracketed IPv6
  entries that httpx's proxy handling chokes on. GitHub Actions
  runners do not carry that list, so CI is unaffected -- but
  anyone reproducing locally in this sandbox must clear
  `NO_PROXY` too, which is why the Makefile `test` target does.
  Phase D's "28 pre-existing failures" were this same artifact
  (its runs did not clear `NO_PROXY`); Phase F's 122-pass run
  is the correct baseline and Phase G reproduces it exactly.
- **Ruff:** `ruff check app tests eval` clean;
  `ruff format --check app tests eval` clean (61 files).
- **mypy:** 14 errors in 9 files (listed in G1) -- NOT clean,
  non-blocking job, documented.
- **Bandit:** 11 Low, 0 Medium, 0 High (same as Phase E).
- **pip-audit:** 71 records across 12 dependencies (same count
  as Phase E; package list in `docs/SECURITY.md`). Not upgraded:
  see the accepted-risk note -- upgrading FastAPI/starlette/
  LangGraph pins needs its own full retest and must precede any
  public deploy.
- **Frontend:** Vitest **17 passed** (6 files); `tsc --noEmit`
  clean; `npm run lint` clean (no warnings); `next build`
  succeeds (7 pages; dashboard 71.3 kB / 183 kB first load).
- **Playwright E2E (mock-API):** **1 passed** against the
  production build (`npm run start`, `E2E_RUN=1
  E2E_MOCK_API=1`), signup -> upload -> ask -> cited answer.
  Docker-stack mode (`E2E_MOCK_API=0`) was not run (no Docker).
- **Docker:** NOT run in this sandbox -- `docker` is not
  installed here, same caveat as Phases A-F. `docker build`
  for both images and the compose smoke test are CI jobs, not
  claimed local passes. The Dockerfiles themselves were already
  fixed in Phase A (non-root users, backend CMD via
  `entrypoint.sh`, frontend `public/` placeholder).
- **Secrets check:** staged diff grep-checked for key material
  (no secret found; the only key-like strings are the
  documented test/placeholder values in CI and the dev-only
  JWT secret, which production refuses).
- **OpenAPI:** generated for real (14 paths, see G3).

## Known limitations (Phase G, do not over-claim)

- Live deployment: not performed (no credentials). CI will
  verify Docker builds and compose smoke; a human must still
  perform the Render/Vercel steps in `docs/DEPLOYMENT.md`.
- Live evaluation: still blocked (no OpenAI key). README and
  resume numbers therefore contain no live quality metric.
- mypy: 14 pre-existing errors, non-blocking.
- Scans: pip-audit 71 records (accepted risk, pre-deploy
  upgrade required), npm audit unknown until a CI run reports
  it, bandit 11 Low only.
- Screenshots/GIF: TODO (steps documented, no fakes).
- Compose smoke in CI uses a placeholder key: it proves boot
  and readiness, not chat.
- `make test` assumes an activated backend venv; `make build`
  and `make up` assume Docker.
- The Phase G ruff config keeps ruff's default rule set (plus
  the B008 ignore); a stricter rule set (e.g. E501 at 88 chars)
  is a separate style decision, not done here.

## Merge status (at time of writing, before merging)

This report was written on `phase-g-cicd-docs` before the merge
chain ran, as instructed. Merge/tag/release outcomes are recorded
in the PR #7 body and in the final handoff, not by a post-merge
commit to `main` (the merge authorisation covers merging the
stack, tagging, and releasing; it does not authorise a new
direct commit to `main` for report updates).
