# Agentic RAG Knowledge Assistant

[![CI](https://github.com/Ganesh-123-maker/RAG/actions/workflows/ci.yml/badge.svg)](https://github.com/Ganesh-123-maker/RAG/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> A Retrieval-Augmented Generation (RAG) application developed by **Barmavath Ganesh** that enables users to ask questions based on uploaded documents. Powered by an agentic LangGraph pipeline, Next.js 14, FastAPI, GPT-4o, and Qdrant vector search with real-time SSE streaming and source citations.

---

## 🚀 Features

- **Multi-format ingestion** — PDF, DOCX, TXT, and Markdown files
- **Token-aware chunking** — tiktoken (`cl100k_base`), 512-token windows with 64-token overlap
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

## 🏗️ Architecture

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

---

## 🛠️ Tech Stack

| Category | Technologies |
|----------|--------------|
| **Frontend** | Next.js 14, React, TypeScript, Tailwind CSS, Lucide Icons |
| **Backend** | Python 3.11, FastAPI, SQLAlchemy 2.0 (Async), Uvicorn |
| **AI Framework** | LangGraph, LangChain, OpenAI API |
| **LLM & Embeddings** | OpenAI GPT-4o, `text-embedding-3-large` (3072 dim) |
| **Vector Database** | Qdrant (v1.9) |
| **Relational Database** | PostgreSQL 16 (production) / SQLite (local dev) |
| **Auth & Security** | JWT (python-jose), Password Hashing (bcrypt, passlib) |
| **Testing & CI** | pytest, pytest-asyncio, GitHub Actions CI |
| **Containerization** | Docker, Docker Compose |

---

## ⚡ Quick Start (Docker — Recommended)

### 1. Clone the repository

```bash
git clone https://github.com/Ganesh-123-maker/RAG.git
cd RAG
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and provide your OpenAI key and secret:

```env
OPENAI_API_KEY=sk-proj-YOUR_REAL_KEY_HERE
JWT_SECRET_KEY=your-random-secret-32-chars-minimum
```

### 3. Launch with Docker Compose

```powershell
.\start.ps1
```

Or using Docker Compose directly:

```bash
docker compose up -d --build
```

---

## 💻 Local Development (Standalone Mode)

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Start FastAPI backend server
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

---

## 🌐 Service URLs

| Service | Local URL |
|---------|-----------|
| **Frontend App** | [http://localhost:3000](http://localhost:3000) |
| **API Docs (Swagger)** | [http://localhost:8000/docs](http://localhost:8000/docs) |
| **API Health Check** | [http://localhost:8000/health](http://localhost:8000/health) |
| **Qdrant Dashboard** | [http://localhost:6333/dashboard](http://localhost:6333/dashboard) |

---

## 🔧 Environment Variables

Variables configured in `.env`:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | **Yes** | — | OpenAI API key (`sk-proj-...`) |
| `JWT_SECRET_KEY` | **Yes** | — | Secret for signing JWT tokens (min 32 chars) |
| `DATABASE_URL` | No | `postgresql+asyncpg://...` | SQLAlchemy async DB URL |
| `QDRANT_HOST` | No | `localhost` | Qdrant host (`:memory:` for in-memory) |
| `QDRANT_PORT` | No | `6333` | Qdrant port |
| `QDRANT_COLLECTION` | No | `rag_chunks` | Qdrant collection name |
| `OPENAI_EMBEDDING_MODEL` | No | `text-embedding-3-large` | Embedding model |
| `OPENAI_EMBEDDING_DIMENSIONS` | No | `3072` | Embedding dimensions |
| `OPENAI_CHAT_MODEL` | No | `gpt-4o` | Chat completion model |
| `UPLOAD_DIR` | No | `./uploads` | Directory for uploaded files |
| `MAX_UPLOAD_SIZE_MB` | No | `50` | Max file size limit in MB |
| `CHUNK_SIZE_TOKENS` | No | `512` | Token size per text chunk |
| `CHUNK_OVERLAP_TOKENS` | No | `64` | Token overlap between chunks |
| `RETRIEVAL_TOP_K` | No | `5` | Top-K document chunks retrieved |

---

## 🧪 Running Tests

```bash
cd backend
python -m pytest tests/ -v
```

---

## ❓ Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| `Settings validation error` | Missing required env vars | Copy `.env.example` to `.env` and set `OPENAI_API_KEY` & `JWT_SECRET_KEY` |
| `JWT_SECRET_KEY` error | Secret string too short | Must be ≥ 32 characters long |
| Qdrant connection refused | Qdrant container not running | Start Qdrant in Docker or use `QDRANT_HOST=:memory:` |
| Module not found in tests | Python path not set | Run pytest inside `backend/` directory |

---

## 👨‍💻 Developer

**Barmavath Ganesh**

- **Education:** B.Tech Computer Science and Engineering, Indian Institute of Information Technology Guwahati (IIIT Guwahati)
- **Location:** Hyderabad, Telangana, India

### 📬 Connect with Me

- **GitHub:** [https://github.com/Ganesh-123-maker](https://github.com/Ganesh-123-maker)
- **LinkedIn:** [https://www.linkedin.com/in/barmavathganesh](https://www.linkedin.com/in/barmavathganesh)
- **Email:** [ganeshbarmavath14@gmail.com](mailto:ganeshbarmavath14@gmail.com)

---

## 📄 License

This project is licensed under the **MIT License**.

---

⭐ If you found this project useful, please consider giving it a **Star** on GitHub!
