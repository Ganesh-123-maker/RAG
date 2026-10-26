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
- **Retrieval** — Dense Qdrant search (cosine) with an `owner_id` payload filter, a configurable similarity threshold (default 0.30, tested against 0.50 on live data and kept -- see Evaluation), fetch-k 20 with MMR selection (λ 0.7) down to top-k 5, and a shared empty/low-confidence refusal path. Hybrid search and a reranker were deliberately **not** added: live retrieval is already 1.0 on this corpus, so there is no measured gap for them to close (see `docs/EVALUATION.md`).
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
| npm audit | CI first run: 15 vulnerabilities (3 moderate, 11 high, 1 critical), incl. Next.js 14.2.5 update; non-blocking CI job, see docs/SECURITY.md |
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

**Live evaluation has now been run — on Gemini free tier, not
OpenAI.** The connected OpenAI account returned
`credit_balance_exhausted`, so the live runs used Gemini's
OpenAI-compatible endpoint (chat `gemini-3.5-flash-lite`, embeddings
`gemini-embedding-001`, 3072 dims) at $0 cost. Every number below
measures that configuration and must never be quoted as an OpenAI /
GPT-4o result. Full discussion, run outputs, and the tuning decision:
`docs/EVALUATION.md`.

- **Corpus:** 10 self-written documents (`backend/eval/corpus/`, TXT /
  MD / PDF / DOCX), 55 golden questions, 16 unanswerable probes,
  6 prompt-injection probes. See `backend/eval/README.md`.
- **Full live run** (`docs/eval/gemini-live-full/`, 55 golden):
  hit@1 = 1.0, hit@3 = 1.0, hit@5 = 1.0, MRR = 1.0; citation
  precision 0.9623; faithfulness 0.9636; refusal accuracy 0.6875
  (11/16); injection pass 0.8333 (5/6); LLM judge 52/54 correct;
  latency p50 10.0s, p95 78.5s (p95 inflated by free-tier 503
  retries, not normal answering speed).
- **Capped live run** (`docs/eval/gemini-live-limit20/`, 20 golden):
  hit@1/3/5 = 1.0, citation precision 1.0, faithfulness 0.9833,
  refusal 0.5625 (9/16), injection 0.8333 (5/6), judge 20/20.
- **Honest limits:** the corpus is small and the golden questions
  were written against it, so perfect retrieval proves the pipeline
  end to end, not general quality on a large corpus. **Refusal is
  the weak metric** (0.50–0.6875 across runs) and it wobbles run to
  run on identical probes. Raising the similarity threshold 0.30 →
  0.50 was tested (`docs/eval/gemini-live-limit20-threshold050/`) and
  did **not** improve refusal (8/16 vs 9/16), so the production
  default stays at 0.30; a grade-based refusal is the identified
  future fix, not a shipped change.
- **Offline smoke results (labelled as such):** `docs/eval/offline-smoke-1/`
  (current config, threshold 0.30) and
  `docs/eval/offline-smoke-threshold-off/` (threshold 0.0). The
  current-config hit@5 of 0.3636 is a **fake-embedding artifact**
  (hashed cosines typically fall below 0.30), not evidence about the
  real threshold. Offline scores must never be quoted as system
  quality.

Hybrid search and a reranker are **not implemented**: with retrieval
already at 1.0 on this corpus there is no measured gap for them to
close; the experiment to run first on a larger corpus is documented
in `docs/EVALUATION.md`.

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
- Demo screenshots (real UI against a local stack, 2026-10-26; see `docs/manual-api-exercise.md` for the run): [login](docs/screenshots/01-login.png), [dashboard with a Ready document](docs/screenshots/02-dashboard.png), [chat answer with citations](docs/screenshots/03-chat-answer.png). No stock or fake screenshots are included.

---

## ⚠️ Limitations

- **Live quality is measured on Gemini free tier only** (see Evaluation), on a 10-document corpus. No OpenAI/GPT-4o number is claimed, and no large-corpus quality is claimed.
- **Thresholds are measured, not tuned optima:** similarity 0.30 was tested against 0.50 on live data and kept (0.50 did not improve refusal); grade 0.50, MMR λ 0.7, and fetch-k 20 remain untested defaults. Do not claim they are tuned.
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
