# Demo seed run (2026-11-10, local stack, no Docker)

First ever run of `backend/scripts/seed_demo.py`. It works: demo user
`demo@example.com` created, 3 documents uploaded (`--limit 3`:
`vector-databases.txt`, `qdrant.md`, `chunking.txt`), all reached
`ready` with 1 chunk each, script exit 0. A streamed in-corpus
question afterwards ("How does HNSW search work in a vector
database?") returned a real answer cited to the `vector-databases.txt`
chunk (score 0.8229).

## Stack used

- Backend: `uvicorn app.main:app` on `127.0.0.1:8000`, branch
  `remaining-completion`, scratch SQLite file
  (`workspace/.rag-exercise/seed-stack/seed.db`, not committed),
  `QDRANT_HOST=":memory:"`, migrations 001 -> 004 applied.
- Provider: Gemini free tier via its OpenAI-compatible endpoint
  (chat `gemini-3.5-flash-lite`, embeddings `gemini-embedding-001`),
  same as the committed live eval runs.
- Ingestion worker: `scripts/run_ingestion_worker.py --loop
  --interval 10` alongside the server. `/health` and `/ready` both
  returned `ok`/`ready` before seeding.

## Two defects found and fixed while running it

1. **Ingestion worker crashed on startup** (SQLAlchemy
   `InvalidRequestError`: `Document.owner` expression `'User'`
   failed to locate a name). Same class of bug as the eval runner's
   refresh_token import (fixed 2026-10-27): the worker imported
   only `DocumentService`, never the `User` model. Fixed by
   importing every model module in `scripts/run_ingestion_worker.py`;
   the same latent fix was applied to `scripts/reconcile_orphans.py`,
   which imported only `Document`. The worker is therefore broken
   as shipped on main -- it could never have processed a queued
   document -- and this run is the first proof it works.
2. **Seed script vs sandbox proxy**: `seed_demo.py` crashed with
   `httpx.InvalidURL` until run with
   `NO_PROXY=localhost,127.0.0.1`, which bypasses the sandbox proxy
   for localhost (same bypass the Gemini wrapper sets). Not a code
   bug; a sandbox quirk worth knowing when running scripts locally.

## What this does not prove

- It does not prove the Docker images, the Render/Vercel wiring, or
  Qdrant Cloud behaviour; the deployment smoke test in
  `docs/DEPLOYMENT.md` is still required on the real stack.
- Demo credentials are throwaway (`demo@example.com` /
  `demo-password-123`, local scratch DB only). Never reuse them
  anywhere real.
