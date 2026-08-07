# Agentic RAG Knowledge Assistant

[![CI](https://github.com/Ganesh-123-maker/RAG/actions/workflows/ci.yml/badge.svg)](https://github.com/Ganesh-123-maker/RAG/actions/workflows/ci.yml)

> Upload PDFs, DOCX, TXT, and Markdown files — ask questions — get cited answers powered by an agentic LangGraph pipeline, GPT-4o, and Qdrant vector search.

---

## Features

- **Multi-format ingestion** — PDF, DOCX, TXT, Markdown
- **Token-aware chunking** — tiktoken (cl100k_base), 512-token windows with 64-token overlap
- **High-quality embeddings** — OpenAI `text-embedding-3-large` (3072 dimensions)
- **Agentic RAG pipeline** — LangGraph state machine with Planner, Retriever, Reasoning, and Response nodes
- **Query rewriting** — Planner rewrites follow-up questions into standalone queries for accurate vector search
- **Source citations** — every answer links back to the exact document chunk
- **SSE streaming** — tokens stream to the browser in real time
- **Conversational memory** — full history passed to the reasoning node
- **JWT authentication** — bcrypt passwords, bearer tokens
- **Ownership-scoped retrieval** — Qdrant payload filtering, no cross-user data leakage
- **Modern UI** — Next.js 14, Tailwind CSS, dark-mode glassmorphism design

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Browser (Next.js 14)                         │
│  Landing → Auth → Dashboard                                     │
│              │ Upload           │ Chat (SSE stream)             │
└──────────────┼──────────────────┼──────────────────────────────┘
               │                  │
               ▼                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                  FastAPI (Python 3.11)                          │
│                                                                 │
│  POST /api/v1/documents/upload                                  │
│    └─► DocumentService                                          │
│         ├─ extract_text  (pdfplumber / python-docx / plain)     │
│         ├─ chunk_text    (tiktoken, 512 tok, 64 overlap)        │
│         ├─ EmbeddingService.embed_batch (text-embedding-3-large)│
│         └─ VectorStoreService.upsert_chunks ──────────► Qdrant  │
│                                                                 │
│  POST /api/v1/chat/stream                                       │
│    └─► AgentService (LangGraph)                                 │
│         ├─ planner_node   — query rewrite + retrieval decision  │
│         ├─ retriever_node — embed query + Qdrant filtered search│
│         ├─ reasoning_node — GPT-4o with context + history       │
│         └─ response_node  — parse citations → SSE stream        │
│                                                                 │
│  JWT auth middleware                                            │
│  Repository pattern (UserRepo / DocumentRepo / ConvRepo)        │
└────────────────────────┬────────────────────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
     PostgreSQL         Qdrant       Local disk
     (metadata,      (vector store,  (uploaded
      auth, history)  owner-filtered)  files)
```

### Key Design Decisions

| Decision | Why |
|----------|-----|
| **Token-based chunking** | Embedding models have token budgets, not character limits |
| **64-token overlap** | Facts at chunk boundaries appear in at least one complete chunk |
| **Qdrant payload filtering** | Ownership enforced inside the vector DB — no post-filtering in Python |
| **LangGraph state machine** | Nodes are inspectable and testable; conditional edges handle fast paths |
| **Planner query rewrite** | Follow-ups like "What does that mean?" become standalone queries |
| **Repository + Service layer** | Routers stay thin; services own business logic; repositories own SQL |
| **Async throughout** | FastAPI + asyncpg + AsyncQdrantClient + AsyncOpenAI — no thread blocking |
| **SSE streaming** | GPT-4o tokens stream to the browser as they arrive |

---

## Prerequisites

- **Docker Desktop** — [download here](https://www.docker.com/products/docker-desktop/)
- **OpenAI API key** with access to `text-embedding-3-large` and `gpt-4o`

---

## Quick Start (Docker — Recommended)

### 1. Clone the repository

```powershell
git clone https://github.com/Ganesh-123-maker/RAG.git
cd RAG
```

### 2. Configure environment

```powershell
cp .env.example .env
```

Open `.env` and fill in the required values:

```env
OPENAI_API_KEY=sk-proj-YOUR_REAL_KEY_HERE
JWT_SECRET_KEY=your-random-secret-32-chars-minimum
```

### 3. Start all services

```powershell
.\start.ps1
```

This script:
- Checks Docker is running
- Warns if the OpenAI key is not set
- Builds and starts all 4 services (PostgreSQL, Qdrant, FastAPI, Next.js)
- Waits for the backend to become healthy
- Opens your browser automatically

**Other modes:**
```powershell
.\start.ps1 -Rebuild   # Force rebuild of Docker images
.\start.ps1 -Logs      # Follow container logs
.\start.ps1 -Stop      # Stop all services
```

### 4. Open the app

Visit **http://localhost:3000** → Register → Upload a PDF → Ask questions

---

## Local Development (Without Docker)

Requires Python 3.11+, Node 18+, and running Qdrant + PostgreSQL instances.

### Backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Set env vars or use .env file
# DATABASE_URL=sqlite+aiosqlite:///./ragdb.sqlite  (SQLite works for local dev)
# QDRANT_HOST=localhost

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

---

## Service URLs

| Service | URL |
|---------|-----|
| **Frontend** | http://localhost:3000 |
| **API Docs (Swagger)** | http://localhost:8000/docs |
| **API Health** | http://localhost:8000/health |
| **Qdrant Dashboard** | http://localhost:6333/dashboard |

---

## Environment Variables

All variables are loaded from the `.env` file. Copy `.env.example` to `.env` to get started.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | **Yes** | — | OpenAI API key (`sk-proj-...`) |
| `JWT_SECRET_KEY` | **Yes** | — | Secret for signing JWT tokens (min 32 chars) |
| `DATABASE_URL` | No | `sqlite+aiosqlite:///./ragdb.sqlite` | SQLAlchemy async DB URL |
| `QDRANT_HOST` | No | `localhost` | Qdrant host (Docker: `qdrant`) |
| `QDRANT_PORT` | No | `6333` | Qdrant port |
| `QDRANT_COLLECTION` | No | `rag_chunks` | Qdrant collection name |
| `POSTGRES_USER` | No | `raguser` | PostgreSQL user (Docker only) |
| `POSTGRES_PASSWORD` | No | `ragpassword` | PostgreSQL password (Docker only) |
| `POSTGRES_DB` | No | `ragdb` | PostgreSQL database name (Docker only) |
| `OPENAI_EMBEDDING_MODEL` | No | `text-embedding-3-large` | Embedding model |
| `OPENAI_EMBEDDING_DIMENSIONS` | No | `3072` | Embedding dimensions |
| `OPENAI_CHAT_MODEL` | No | `gpt-4o` | Chat completion model |
| `UPLOAD_DIR` | No | `./uploads` | Directory for uploaded files |
| `MAX_UPLOAD_SIZE_MB` | No | `50` | Max file size in MB |
| `CHUNK_SIZE_TOKENS` | No | `512` | Chunk size in tokens |
| `CHUNK_OVERLAP_TOKENS` | No | `64` | Overlap between chunks |
| `RETRIEVAL_TOP_K` | No | `5` | Number of chunks to retrieve |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | No | `60` | Token expiry in minutes |
| `ENVIRONMENT` | No | `development` | `development` or `production` |
| `BACKEND_CORS_ORIGINS` | No | `["http://localhost:3000"]` | Allowed CORS origins (JSON array) |

---

## API Reference

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/v1/auth/register` | — | Register new user |
| POST | `/api/v1/auth/login` | — | Login, returns JWT |
| GET | `/api/v1/auth/me` | ✓ | Current user info |
| POST | `/api/v1/documents/upload` | ✓ | Upload & ingest document |
| GET | `/api/v1/documents/` | ✓ | List user's documents |
| GET | `/api/v1/documents/{id}` | ✓ | Get document by ID |
| DELETE | `/api/v1/documents/{id}` | ✓ | Delete document + vectors |
| POST | `/api/v1/chat/` | ✓ | Ask question (JSON response) |
| POST | `/api/v1/chat/stream` | ✓ | Ask question (SSE stream) |
| GET | `/api/v1/chat/conversations` | ✓ | List conversations |
| GET | `/api/v1/chat/conversations/{id}` | ✓ | Get conversation with messages |
| DELETE | `/api/v1/chat/conversations/{id}` | ✓ | Delete conversation |

Full interactive docs at **http://localhost:8000/docs**

---

## Running Tests

```bash
cd backend
pip install -r requirements.txt

pytest --cov=app --cov-report=term-missing
```

Or inside Docker:
```bash
docker compose exec backend pytest --cov=app --cov-report=term-missing
```

---

## Project Structure

```
.
├── .env                     # Your secrets (git-ignored)
├── .env.example             # Template — copy to .env
├── .gitignore
├── docker-compose.yml       # Orchestrates all 4 services
├── start.ps1                # One-command launcher (Windows)
├── setup.ps1                # First-time setup
├── README.md
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── pyproject.toml       # pytest config
│   ├── alembic/             # Database migrations
│   ├── app/
│   │   ├── main.py          # FastAPI app + lifespan
│   │   ├── core/
│   │   │   ├── config.py    # Settings (pydantic-settings)
│   │   │   ├── database.py  # Async SQLAlchemy engine
│   │   │   ├── security.py  # JWT + bcrypt
│   │   │   └── dependencies.py  # FastAPI dependency injection
│   │   ├── models/          # SQLAlchemy ORM models
│   │   ├── repositories/    # Data access layer
│   │   ├── schemas/         # Pydantic request/response schemas
│   │   ├── services/
│   │   │   ├── agent_service.py     # LangGraph agentic pipeline
│   │   │   ├── rag_service.py       # Direct RAG (non-agentic)
│   │   │   ├── document_service.py  # Ingestion orchestration
│   │   │   ├── chunking_service.py  # Text extraction + chunking
│   │   │   ├── embedding_service.py # OpenAI embeddings
│   │   │   ├── vector_store_service.py  # Qdrant operations
│   │   │   └── auth_service.py      # Registration + login
│   │   └── routers/
│   │       ├── auth.py      # /api/v1/auth/*
│   │       ├── documents.py # /api/v1/documents/*
│   │       └── chat.py      # /api/v1/chat/*
│   └── tests/
│       ├── conftest.py      # Shared fixtures (in-memory SQLite)
│       ├── test_auth.py
│       ├── test_chunking.py
│       ├── test_documents.py
│       └── test_rag.py
└── frontend/
    ├── Dockerfile
    ├── next.config.js       # API proxy rewrites
    ├── tailwind.config.js
    ├── app/
    │   ├── layout.tsx       # Root layout + toasts
    │   ├── globals.css      # Design system tokens
    │   ├── page.tsx         # Landing page
    │   ├── login/           # Login page
    │   ├── register/        # Register page
    │   └── dashboard/       # Main app (documents + chat)
    ├── components/
    │   └── ChatPanel.tsx    # SSE streaming chat UI
    └── lib/
        └── api.ts           # Typed Axios client + interfaces
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 14, TypeScript, Tailwind CSS |
| Backend | FastAPI, Python 3.11, SQLAlchemy 2.0 async |
| Database | PostgreSQL 16 (prod) / SQLite (dev/test) |
| Vector DB | Qdrant v1.9 |
| Embeddings | OpenAI text-embedding-3-large (3072 dim) |
| LLM | OpenAI GPT-4o |
| Agent | LangGraph 0.2 (Planner → Retriever → Reasoning → Response) |
| Auth | JWT (python-jose), bcrypt (passlib) |
| Testing | pytest, pytest-asyncio, httpx, aiosqlite |
| Dev | Docker Compose, health checks |

---

## Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| `Settings validation error` on startup | Missing required env vars | Copy `.env.example` to `.env` and fill in `OPENAI_API_KEY` and `JWT_SECRET_KEY` |
| `JWT_SECRET_KEY` error | Key is too short | Must be ≥ 32 characters. Run: `python -c "import secrets; print(secrets.token_hex(32))"`  |
| Qdrant connection refused | Qdrant not running | Start with Docker: `docker run -p 6333:6333 qdrant/qdrant` or use `QDRANT_HOST=:memory:` for local dev |
| `asyncpg` import error on Windows | asyncpg not installed | Install full requirements: `pip install -r requirements.txt` |
| Document upload returns 500 | Qdrant unreachable | Ensure Qdrant is running and `QDRANT_HOST`/`QDRANT_PORT` are correct |
| Tests fail with `ModuleNotFoundError` | PYTHONPATH not set | Run from `backend/` directory: `cd backend && pytest` |

---

## Future Improvements

- [x] **Streaming citation save** — citations from SSE stream are now persisted in the DB
- [ ] **Re-ranking** — add Cohere/cross-encoder re-ranking after initial retrieval
- [ ] **Multi-file chat scope** — let users ask questions across a selected subset of documents
- [ ] **Document preview** — display the original chunk in context with highlight
- [ ] **Async ingestion** — background task queue (Celery/ARQ) for large file processing
- [ ] **Metadata filtering** — filter by document date, type, or custom tags
- [ ] **Admin dashboard** — usage metrics, user management
- [ ] **OpenAI alternatives** — pluggable LLM/embedding backends (Ollama, Groq, etc.)

---

## License

MIT
