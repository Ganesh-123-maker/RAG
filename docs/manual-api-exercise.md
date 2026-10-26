# Manual API exercise (run 2026-10-26, local stack, no Docker)

This is the Step-2 exercise from the 2026-10-24 plan, executed against
a real local backend instead of Docker (this sandbox has no Docker
binary). It proves the deployed-shaped flow end to end: register,
upload, ready, streamed answer with a page-number citation, and an
out-of-corpus refusal. It is not a substitute for the deployment
smoke test in `docs/DEPLOYMENT.md`, which must still be run against
the real Render/Vercel/Qdrant Cloud stack.

## Stack used

- Backend: `uvicorn app.main:app` on `127.0.0.1:8000`, from the repo
  at main `2cd5d37` (PR #25 merged), with `DATABASE_URL` pointed at
  a scratch SQLite file and `QDRANT_HOST=":memory:"` (the server's
  own in-memory Qdrant path, not a test double). Migrations applied
  with `alembic upgrade head` (001 -> 002 -> 003).
- Provider: Gemini free tier via its OpenAI-compatible endpoint
  (chat `gemini-3.5-flash-lite`, embeddings `gemini-embedding-001`),
  because the OpenAI account is credit-exhausted. Same provider as
  the committed live eval runs.
- Ingestion worker: `scripts/run_ingestion_worker.py --loop
  --interval 10` alongside the server.
- `/health` returned `{"status":"ok","version":"1.0.0"}` and `/ready`
  returned `{"status":"ready","version":"1.0.0"}` before any other
  step.

## Steps and observed results (all real responses, not fixtures)

1. **Register** `POST /api/v1/auth/register` with
   `exercise@example.com` -> HTTP 201, user id
   `002e03c4-91e7-435b-bedf-fa9ed3729256`. Note: register alone did
   not leave a usable cookie for the next call, so the exercise
   logged in explicitly next.
2. **Login** `POST /api/v1/auth/login` -> HTTP 200, httpOnly
   `access_token` cookie set (verified in the cookie jar).
3. **Upload** `POST /api/v1/documents/upload` with
   `backend/eval/corpus/langgraph.pdf` (3095 bytes) -> HTTP 201,
   document id `d832c776-0473-46f1-8873-a195a2631413`,
   `status: ready`, `chunk_count: 1`, `ingestion_progress: 100`
   (worker picked it up within seconds). `GET /api/v1/documents`
   later listed the same document as `ready`.
4. **Streamed in-corpus answer** `POST /api/v1/chat/stream` with
   `{"question": "What is LangGraph and how does its graph
   execution work?"}` -> real SSE `token` events, then a
   `citations` event and `done`. The answer describes state,
   nodes, edges, conditional routing, cycles, checkpointers, and
   streaming, every claim cited to chunk
   `34a5a739-c9a3-5858-8815-9c98a3a84980`, `langgraph.pdf`,
   **page 1**, score 0.804, `document_id` matching the uploaded
   document. Conversation id
   `6e8377ab-63b5-40c0-83a4-bb043f785bed`.
5. **Out-of-corpus question** `POST /api/v1/chat/stream` with
   `{"question": "What is the recipe for sourdough bread starter
   and how long does it ferment?"}` -> answer: "The provided
   context does not contain information about the recipe for
   sourdough bread starter or how long it ferments." No recipe
   was invented. Honest detail: a LangGraph chunk (score 0.4216)
   was retrieved and cited, so this refusal came from the
   reasoning step judging the context insufficient, not from the
   empty-retrieval refusal path. The user-visible behaviour --
   no hallucinated recipe -- is what was checked.

## What this does not prove

- It does not prove the Docker images, the Render/Vercel wiring, or
  Qdrant Cloud behaviour; CI's Docker builds and compose smoke
  cover boot/readiness only. The deployment smoke test in
  `docs/DEPLOYMENT.md` is still required on the real stack.
- It uses one small PDF and one user; it is a smoke exercise, not
  a load or multi-user test.
