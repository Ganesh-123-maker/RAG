# Agentic RAG Knowledge Assistant

[![CI](https://github.com/Ganesh-123-maker/RAG/actions/workflows/ci.yml/badge.svg)](https://github.com/Ganesh-123-maker/RAG/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11](https://img.shields.io/badge/Python-3.11-blue.svg)](https://www.python.org/downloads/release/python-3110/)
[![Next.js 14](https://img.shields.io/badge/Next.js-14.2-black.svg)](https://nextjs.org/)

> A Retrieval-Augmented Generation (RAG) system built by **Barmavath Ganesh (B.Tech CSE, IIIT Guwahati)**. Upload documents (PDF/DOCX/Markdown/TXT), ask questions, and get answers grounded in your own documents with citations by chunk id, streamed over SSE. One LangGraph pipeline serves both the chat and streaming endpoints.

> **Honesty note (read before quoting numbers):** this README contains no
> synthetic benchmark table. The old table claiming 100% groundedness,
> 0% hallucination, <1.5s latency, 97% coverage, and "52 documents
> indexed" was produced by a simulated script that never called an LLM
> or a vector store; it was deleted in Phase D and is removed here in
> Phase G. What follows is measured, labelled, and reproducible -- or
> explicitly marked as not yet measured. See [Evaluation](#-evaluation)
> and [Limitations](#-limitations).

---

## 🌐 Deployment status

> **Live deployment: NOT YET DEPLOYED.** No live URL is claimed. The
> deployment configuration exists (`render.yaml` for the backend,
> Vercel project settings documented in `docs/DEPLOYMENT.md`), but no
> deploy credentials were available in the Phase G sandbox, so the
> live-deploy step was stopped deliberately and is documented in
> `docs/phase-g-report.md` with exactly what the maintainer must
> provide. The previously linked Vercel URL is removed: it was never
> verified from this repository.
>
> Locally, clone and run with `docker compose up -d --build`, then
> visit [http://localhost:3000](http://localhost:3000). See
> [Quick Start](#-quick-start-docker).

| Endpoint (local) | URL | Purpose |
|---|---|---|
| Web Application | http://localhost:3000 | Next.js dashboard |
| Backend API (Swagger Docs) | http://localhost:8000/docs | Interactive OpenAPI UI |
| API Health Endpoint | http://localhost:8000/health | Liveness only (process up) |
| Readiness Endpoint | http://localhost:8000/ready | Postgres + Qdrant must answer |
| Qdrant Dashboard | http://localhost:6333/dashboard | Vector store console |
| Metrics | http://localhost:8000/metrics | In-process Prometheus text |

---

## 🚀 Key Features

- **Multi-format ingestion** — PDF (`pdfplumber`, with page numbers and scanned-PDF detection), DOCX (paragraphs, headings, and tables as text), Markdown (headings), and raw text. Uploads are validated by content (magic bytes), size-streamed (50 MB cap without loading the whole file), and parsed in a threadpool so the async event loop is not blocked.
- **Sentence/paragraph-aware chunking** — Tiktoken (`cl100k_base`), 512-token chunks, 64-token overlap, with char offsets, page, section, chunk index, and content hash stored in the Qdrant payload.
- **Dedupe** — Content hash per owner: re-uploading the same file is detected, and duplicate chunks within a document are not re-indexed.
- **Embeddings** — OpenAI `text-embedding-3-large` (3072 dimensions by default, configurable and validated; a collection-dimension mismatch is detected at startup). Embedding failures raise a typed error and mark the document `error` -- there is deliberately **no fallback vector**: a silently substituted vector would corrupt retrieval.
- **One LangGraph pipeline for chat and streaming** — `planner → retriever → grade → [rewrite + retry once] → reasoning → verify → [regenerate once] → response`, with a direct-answer branch for chit-chat. Both `POST /api/v1/chat` and `POST /api/v1/chat/stream` run this same graph with the same prompt, history window, and citation semantics. Streaming yields structured SSE events: `status`, `token`, `citations`, `done`, `error`; the assistant message is persisted even if the client disconnects.
- **Retrieval** — Dense Qdrant search (cosine) with an `owner_id` payload filter, a configurable similarity threshold (default 0.30, an unmeasured starting default -- see Limitations), fetch-k 20 with MMR selection (λ 0.7) down to top-k 5, and a shared empty/low-confidence refusal path. Hybrid search and a reranker were deliberately **not** added: Phase D found no live data to justify them (see `docs/EVALUATION.md`).
- **Grounded prompting and chunk-id citations** — Context blocks are delimited and marked as data, not instructions. Citations reference chunk ids (not positions) and are validated: only chunks actually retrieved and cited by the model are shown, with page/section and snippet, in a clickable source panel in the UI.
- **Conversation memory** — PostgreSQL message history, bounded by a token budget (context 6000 tokens, history 2000 tokens, chat output capped at 1000 tokens). This is history, not semantic long-term memory.
- **Background ingestion** — Uploads queue (queued → processing → ready/error) with progress, retry on embedding failure (max 2 attempts), and a worker (`backend/scripts/run_ingestion_worker.py`) plus an orphan-reconciliation script.
- **Auth and isolation** — JWT with bcrypt, httpOnly cookies (JavaScript never sees the token), logout revocation via a token denylist, owner-scoped repositories, and an `owner_id` Qdrant filter on every search. Refresh tokens are deferred (see Limitations).
- **Rate limits and quotas** — Per-minute limits (auth 10, upload 10, chat 30), login lockout after 5 failures (15 minutes), and a per-user daily quota (200 chats, 200k estimated tokens -- an estimate, not metered usage). All single-instance/in-memory unless noted.
- **Observability** — Structured JSON logs with request IDs, a Prometheus-text `/metrics` endpoint, per-node tracing logs, and an optional Sentry hook (no DSN = no-op). Circuit breaker around Qdrant search (3 failures, 60s cooldown).
- **Frontend** — Next.js 14 App Router, Tailwind, dark theme, responsive/mobile sidebar, streaming controls (stop, retry, regenerate, copy), citation chips opening a source panel, conversation rename/delete, document status/progress, drag-and-drop upload with validation. Markdown answers render sanitised (no raw HTML execution).

---

## 🏗️ Architecture

```text
Next.js 14 (frontend)
  │  same-origin rewrite proxy (BACKEND_URL) → backend
  ▼
FastAPI (backend/app/main.py)
  ├─ routers: auth / documents / chat
  ├─ services: DocumentService → ChunkingService → EmbeddingService
  │            → VectorStoreService (Qdrant) ; AgentService (LangGraph)
  └─ repositories (owner-scoped) → PostgreSQL
       LangGraph: planner → retriever → grade → [rewrite once]
                  → reasoning → verify → [regenerate once] → response
                  └─ direct answer (no retrieval, no citations)
```

Full diagrams (system + LangGraph, Mermaid) are in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/graph.mmd`](docs/graph.mmd).
The API reference is generated from the live app, never hand-written:
[`docs/openapi.json`](docs/openapi.json) (14 paths), via
`backend/scripts/export_openapi.py`.

---

## 🛠️ Technology Stack

| Category | Technologies |
|---|---|
| **Frontend** | Next.js 14 (App Router), React 18, TypeScript, Tailwind CSS, Lucide Icons, react-hot-toast |
| **Backend API** | Python 3.11, FastAPI, Uvicorn, Pydantic v2, Pydantic-Settings |
| **Agentic Framework** | LangGraph (direct OpenAI SDK; LangChain was declared but never imported and was removed in Phase C) |
| **LLM & Embeddings** | OpenAI GPT-4o, `text-embedding-3-large` (3072 dimensions) |
| **Vector Database** | Qdrant v1.9 (payload filtered, cosine distance) |
| **Relational Database** | PostgreSQL 16 (production, asyncpg) / SQLite (development, aiosqlite) |
| **ORM & Migrations** | SQLAlchemy 2.0 Async, Alembic (schema is owned by migrations, not `create_all()`) |
| **Authentication** | JWT (`python-jose`), bcrypt, httpOnly cookies |
| **Text Ingestion** | `pdfplumber`, `python-docx`, `tiktoken` (cl100k_base) |
| **Testing & Quality** | `pytest`, `pytest-asyncio`, `pytest-cov`, Vitest, Playwright, Ruff |
| **Containerization** | Docker, Docker Compose (multi-stage builds, non-root users) |

---

## ⚡ Quick Start (Docker)

### 1. Clone the repository

```bash
git clone https://github.com/Ganesh-123-maker/RAG.git
cd RAG
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Set at minimum in `.env`:

```env
OPENAI_API_KEY=sk-...
JWT_SECRET_KEY=your-random-secret-key-at-least-32-chars-long
```

`docker compose up` works with only `OPENAI_API_KEY` set for local
development (a dev-only JWT secret is used and production refuses it),
but set a real secret for anything beyond local use. Never commit
`.env`, `uploads/`, `node_modules/`, or build output.

### 3. Launch the full stack

```bash
docker compose up -d --build
```

Or on Windows: `.\start.ps1` (see also `setup.ps1`; the `.ps1` scripts
are optional -- the Makefile targets are the cross-platform path).

Access the app at **[http://localhost:3000](http://localhost:3000)**.
Check readiness with `curl http://localhost:8000/ready` (must report
`ready`; `/health` alone only proves the process is up).

---

## 💻 Local Development

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Run migrations & start FastAPI
alembic upgrade head
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Makefile shortcuts

```bash
make test        # backend pytest (coverage gate 80%) + frontend Vitest
make lint        # ruff + frontend lint/typecheck
make build       # next build + both Docker images
make up / down   # compose stack up / down (down removes volumes)
make eval-offline # offline pipeline smoke ONLY (not quality)
make openapi     # regenerate docs/openapi.json
make seed        # seed a RUNNING stack (see backend/scripts/seed_demo.py)
```

---

## 🧪 Testing

Measured on the Phase G branch in this sandbox (proxy variables
cleared, including `NO_PROXY` -- see `docs/phase-g-report.md` for why
that matters here):

| Suite | Result |
|---|---|
| Backend pytest | **122 passed, 0 failed** |
| Backend coverage | **91%** (gate in CI: `--cov-fail-under=80`) |
| Frontend Vitest | **17 passed** (6 files) |
| Frontend `tsc --noEmit` / `next lint` | clean |
| Frontend `next build` | succeeds (7 pages) |
| Playwright E2E (mock-API mode) | **1 passed** (signup → upload → ask → cited answer) |
| Ruff `check` + `format --check` | clean |
| mypy | **NOT clean: 14 pre-existing errors** (non-blocking CI job, documented in `docs/phase-g-report.md`) |
| Bandit | 11 Low, 0 Medium, 0 High |
| pip-audit | 71 records (documented accepted risk, see `docs/SECURITY.md`) |
| npm audit | not run cleanly in this sandbox (registry 403); runs in CI as a non-blocking job |
| Docker builds / compose smoke | **not run in this sandbox (no Docker)**; covered by CI jobs (`docker-build`, `compose-smoke`) |

Run the backend suite:

```bash
cd backend
python -m pytest tests/ -v --cov=app --cov-report=term-missing --cov-fail-under=80
```

Run the frontend suites:

```bash
cd frontend
npm test            # Vitest
E2E_RUN=1 E2E_MOCK_API=1 npx playwright test   # needs the prod server up (see frontend/e2e)
```

---

## 📊 Evaluation

**Live evaluation is BLOCKED pending a valid `OPENAI_API_KEY`.** It has
never been run, and no live quality number (accuracy, groundedness,
latency, cost) is claimed anywhere in this README.

What exists, and what it does and does not prove:

- **Corpus:** 10 self-written documents (`backend/eval/corpus/`, TXT /
  MD / PDF / DOCX), 55 golden questions, 16 unanswerable probes,
  6 prompt-injection probes. See `backend/eval/README.md`.
- **Runner:** `backend/eval/run_eval.py`. `--mode offline` uses fake
  hashed bag-of-words embeddings and a fake LLM that copies the best
  overlapping chunk. It proves the pipeline runs end to end
  (ingest → retrieve → graph → metrics → output). **It is NOT a
  quality measurement and its scores must never be quoted as system
  quality.**
- **Offline smoke results (labelled as such):** `docs/eval/offline-smoke-1/`
  (current config, threshold 0.30) and
  `docs/eval/offline-smoke-threshold-off/` (threshold 0.0). The
  current-config hit@5 of 0.3636 is a **fake-embedding artifact**
  (hashed cosines typically fall below 0.30), not evidence about the
  real threshold; the threshold-off run's refusal accuracy of 0.5625
  (vs 1.0 with the threshold) shows the threshold's real function in
  this pipeline. Full discussion: `docs/EVALUATION.md`,
  `docs/phase-d-report.md`.
- **To run the real evaluation** (once a key with quota is available):

```bash
cd backend
OPENAI_API_KEY=sk-... python eval/run_eval.py --mode live --limit 20
```

Full run without `--limit` once the capped run looks sane. Outputs go
to a new `docs/eval/<run-id>/` directory and must be committed with
their run id; only then may README numbers be updated from them.

Hybrid search and a reranker are **not implemented**, because Phase D
had no live data to show a gain; the experiment to run first is
documented in `docs/EVALUATION.md`.

---

## 🔒 Security

Summary only; the full review, scan results, and accepted risks are in
[`docs/SECURITY.md`](docs/SECURITY.md):

- httpOnly cookies, logout denylist, owner-scoped repositories,
  `owner_id` Qdrant filter, login lockout, rate limits, tightened CORS
  (production rejects `*`), security headers, sanitised Markdown
  rendering (no raw HTML execution, no `dangerouslySetInnerHTML`).
- Scans are **not claimed clean**: bandit 11 Low / 0 Medium / 0 High;
  pip-audit 71 records across pinned/transitive dependencies
  (notably `python-jose`, `python-multipart`, `starlette` via FastAPI
  0.111, and LangGraph transitive deps). They are a documented
  accepted risk **only while the app has no public deployment**,
  with a review note in `docs/SECURITY.md`; upgrading FastAPI /
  LangGraph pins is a separate, fully-retested task and must happen
  before any public deploy.
- Secrets come only from the environment. The dev-only JWT secret in
  code is refused in production; it is flagged by bandit as Low and
  documented there.

---

## 📦 Deployment

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for the full guide,
including the exact credentials a maintainer must provide (Render
dashboard secrets + Vercel project settings) and the smoke test to run
after deploying. In short: backend on Render (`render.yaml`, Docker),
frontend on Vercel (Root Directory `frontend`, `BACKEND_URL` pointing
at the Render backend -- note the old guide's `NEXT_PUBLIC_API_URL`
was dead config and is corrected here), Postgres on Render, Qdrant on
Qdrant Cloud free tier.

---

## 📚 Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) -- system + LangGraph diagrams, request flows, config reference
- [`docs/EVALUATION.md`](docs/EVALUATION.md) -- corpus, golden set, runner, mode labels, how to reproduce, blocked live run
- [`docs/SECURITY.md`](docs/SECURITY.md) -- auth, ownership, rate limits, CSP, scan results + accepted risks
- [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) -- Render + Vercel + Qdrant Cloud, credentials needed, smoke test
- [`docs/RESUME.md`](docs/RESUME.md) -- honest resume bullets + interview talking points (verified numbers only)
- [`docs/openapi.json`](docs/openapi.json) -- API reference, generated from the app
- [`docs/phase-a-report.md`](docs/phase-a-report.md) … [`docs/phase-g-report.md`](docs/phase-g-report.md) -- per-phase reports
- [`CHANGELOG.md`](CHANGELOG.md), [`CONTRIBUTING.md`](CONTRIBUTING.md)
- Demo seed: `backend/scripts/seed_demo.py` (needs a running stack; see its help text)
- Demo screenshots/GIF: **TODO** -- not produced in the sandbox (no running stack to screenshot); exact steps are in `docs/phase-g-report.md`. No stock or fake screenshots are included.

---

## ⚠️ Limitations

- **Live quality is unmeasured.** No accuracy, groundedness, hallucination, latency, or cost number is known until the live eval runs.
- **Thresholds are starting defaults, not tuned optima:** similarity 0.30, grade 0.50, MMR λ 0.7, fetch-k 20. Do not claim they are tuned.
- **Verify is overlap-based, not LLM faithfulness:** `verify_node` checks cited chunk ids were retrieved and share substantive tokens with the answer. It catches unsupported citations, not subtle hallucinations.
- **Single-instance limits:** rate limits, quotas, token denylist, metrics, and the ingestion worker are in-memory/single-instance and do not survive restart (except the DB queue) or span replicas.
- **Refresh tokens deferred:** logout revokes only the current token, in this process. Daily token budget is an estimate (chars/4), not metered usage.
- **Dark-only theme;** secondary text in slate-500 is 4.0:1, below WCAG AA for normal text.
- **Docker smoke not run in the sandbox** (no Docker here); CI's `docker-build` and `compose-smoke` jobs are the verification path, and the compose smoke uses a placeholder key so it proves boot/readiness, not chat.
- **Live deployment pending credentials** (see Deployment status above).
- **mypy not clean** (14 pre-existing errors) and **dependency scans not clean** (see Testing / Security).
- **Screenshots/GIF pending** (see Documentation above).

---

## 👨‍💻 Developer Profile

**Barmavath Ganesh**
- **Education:** B.Tech in Computer Science and Engineering, **Indian Institute of Information Technology Guwahati (IIIT Guwahati)**
- **Expertise:** AI/ML Engineering, LLM Agentic Pipelines, Retrieval-Augmented Generation (RAG), Full-Stack Distributed Systems.
- **GitHub:** [https://github.com/Ganesh-123-maker](https://github.com/Ganesh-123-maker)
- **LinkedIn:** [https://www.linkedin.com/in/barmavathganesh](https://www.linkedin.com/in/barmavathganesh)
- **Email:** [ganeshbarmavath14@gmail.com](mailto:ganeshbarmavath14@gmail.com)

---

## 📄 License

This project is licensed under the **MIT License** -- see [`LICENSE`](LICENSE).
