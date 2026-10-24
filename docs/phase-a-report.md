# Phase A — Correctness: Report

Branch: `phase-a-correctness` (from `main` @ `d5322f4`).
No changes were made to `main`, no history was rewritten, no force-push was
used, and no secrets, `.env`, `uploads/`, `node_modules/`, or build output
were committed.

## Audit findings verified (and one correction)

All audit findings for Phase A were confirmed against the code before
changing anything:

- A1: the SHA-256 fallback in `embedding_service.py` was real, and
  ingestion marked documents `ready` on top of it.
- A2: `/chat` used LangGraph while `/chat/stream` ran an inline RAG path
  with a different prompt, history window, no query rewrite, and
  all-retrieved-chunks citations.
- A3: `needs_retrieval=False` routed to `reasoning_node` with empty chunks,
  which returned a document-refusal.
- A4: `frontend/Dockerfile` copied `/app/public` which did not exist;
  `docker-compose.yml` required a `.env` file; the backend image had no
  `CMD`; there were no `.dockerignore` files; `/health` checked nothing.
- A5/A7: repositories had unscoped lookups/deletes; a non-UUID JWT `sub`
  raised an uncaught `ValueError` (500); `is_active` was never checked.
- Correction to the audit's framing: `RagService.answer()` was described as
  "dead code" — that was accurate for production (no router called it), but
  its citation parser was live code used by the agent. Phase A therefore
  deleted `answer()` but kept the parser (see A2 below) instead of deleting
  the whole file.

## What changed

### A1 — Embeddings fail loudly (no fallback vectors)
- `backend/app/services/embedding_service.py`: deleted
  `_generate_fallback_embedding` entirely. Added typed `EmbeddingError`,
  tenacity exponential-backoff retry (3 attempts), a 30 s OpenAI timeout
  (SDK `max_retries=0` so retries are not double-counted), and batching of
  at most 100 inputs per embeddings call.
- `backend/app/services/document_service.py`: on any ingestion failure the
  document is marked `error` with a **safe** message (never raw exception
  text — verified by a sentinel-string test), the stored file is deleted
  (including the now-empty owner directory), and already-upserted vectors
  are deleted (best-effort, logged). Embedding failures return 502,
  unreadable-content failures 422, other failures 500. The full error is
  logged server-side with `exc_info`.
- `backend/requirements.txt`: added `tenacity==8.5.0`.

### A2 — One RAG path for both chat endpoints
- `backend/app/services/agent_service.py`: both `AgentService.run()` and
  the new `AgentService.run_stream()` execute the same compiled LangGraph
  with the same planner, retrieval, prompts, history windows (planner: last
  4 messages; reasoning/direct: last 10), and citation parsing. Streaming
  passes a token sink through graph state so the reasoning node's tokens
  are yielded while the graph runs; `run_stream()` yields structured
  events: `status`, `token`, `citations`, `done`, `error`.
- `backend/app/routers/chat.py`: `/chat/stream` was rewritten on top of
  `run_stream()`; the old inline embedding/search/LLM code and the
  snippet-fallback-on-LLM-error are gone. The assistant message is
  persisted in the generator's `finally` block, so it is saved even when
  the client disconnects mid-stream (partial content, parsed citations).
  Non-stream `/chat` maps agent failures to a safe 502 instead of leaking
  internals. Both endpoints now pass the full history to the agent (the
  windows are applied inside the agent), so they can no longer drift apart.
- `backend/app/services/rag_service.py`: `RagService.answer()` (the dead
  duplicate retrieval path) was deleted. The module now only provides
  `RagAnswer` and `parse_citations` (plus a thin `RagService` namespace
  so existing `RagService._parse_citations` imports keep working).
  The file was **not** deleted outright because the parser is live code
  used by `response_node`.
- `frontend/components/ChatPanel.tsx`: handles the new SSE shapes — the
  `done` event's parsed answer replaces the streamed text (so the streamed
  message matches a reload), and `error` events surface a toast instead of
  silently dropping the answer.

### A3 — Planner fix
- Planner now has a real system prompt (`PLANNER_SYSTEM_PROMPT`), and its
  JSON output is validated with a pydantic `PlannerPlan` schema. Any
  planner failure (LLM error, bad JSON, schema mismatch) fails **open**
  to retrieval with the raw question.
- New `direct` node: when `needs_retrieval=False`, the graph routes
  planner → direct → response. Direct answers are answered by the LLM
  without document claims or citations, and never return the old
  document-refusal. LLM failure in the direct node returns an honest
  apology, not fabricated content.
- Reasoning-node LLM failure now raises `AgentError` (mapped to 502 /
  stream `error` event) instead of presenting retrieved snippets as an
  answer.

### A4 — Docker boot
- `frontend/public/.gitkeep` created so the frontend Dockerfile's
  `COPY --from=builder /app/public ./public` succeeds on a fresh clone.
- `backend/.dockerignore` and `frontend/.dockerignore` added (no
  `.env*`, `node_modules`, `.next`, `__pycache__`, `uploads`, or VCS
  metadata in build contexts).
- `backend/Dockerfile`: added `CMD ["sh", "entrypoint.sh"]` and a
  non-root `appuser` (uid 10001); `frontend/Dockerfile` runner now runs
  as the `node` user. Multi-stage frontend build preserved.
- `backend/entrypoint.sh` (new, executable): runs
  `alembic upgrade head`, then `uvicorn`. `docker-compose.yml` no longer
  overrides the backend command, so `docker run` of the backend image
  works standalone too.
- `docker-compose.yml`: `env_file` is now optional
  (`required: false`), so a missing `.env` no longer breaks compose
  itself; `OPENAI_API_KEY` / `JWT_SECRET_KEY` can also be passed through
  the shell environment. Frontend gained a healthcheck.
- Fresh-clone flow (documented here; README quickstart rewrite is Phase G):
  `cp .env.example .env`, set `OPENAI_API_KEY` to a real key, then
  `docker compose up --build`. `JWT_SECRET_KEY` may be left unset for
  local development only — see the config note below.
- `backend/app/main.py`: `/health` is liveness-only (process up); new
  `/ready` checks Postgres (`SELECT 1`) and Qdrant (`get_collections`)
  with 5 s timeouts and returns 503 with the failing dependency named
  when either is down.

### A5 — Security / ownership
- Owner-scoped repository methods added and used by all production
  callers: `DocumentRepository.get_by_id_for_owner` /
  `delete_for_owner`, `mark_ready`/`mark_error` with optional `owner_id`
  (used by ingestion), `ConversationRepository.get_messages_for_owner` /
  `delete_conversation_for_owner`. The old unscoped methods are kept,
  marked deprecated in their docstrings, and used only by existing tests.
- Chat `document_id` is now checked: 404 for another user's (or missing)
  document, 409 for a document that is not `ready` yet (documented
  choice: 409 = exists but not usable yet).
- `backend/app/core/dependencies.py`: non-UUID JWT `sub` now returns 401
  (UUID parsing moved inside the auth try-block); `is_active=False`
  users now return 401 as well.
- Typed/safe error responses: ingestion and chat never return raw
  exception text; full errors are logged server-side.

### A6 — Migrations, not create_all
- `backend/app/main.py` lifespan no longer calls
  `Base.metadata.create_all()`; schema is owned by Alembic, applied by
  `backend/entrypoint.sh` (`alembic upgrade head`) before uvicorn starts.
- No new migration was added: Phase A changes no model, so the existing
  `alembic/versions/001_initial.py` already covers the schema. (A
  `content_hash` column belongs to Phase B and was deliberately not added
  here.)

### Config note (deliberate, local-dev-only)
- `backend/app/core/config.py`: `JWT_SECRET_KEY` may be unset outside
  production, in which case a well-known dev-only secret is used with a
  startup warning; in production (`ENVIRONMENT=production`) a missing
  secret fails startup. This is what makes
  `docker compose up` work with only `OPENAI_API_KEY` set for local
  development. It must be replaced by proper secret management before
  any real deployment (Phase E).

## Tests

### New: `backend/tests/test_phase_a.py` (11 tests)
- Embedding failure marks the document `error`, returns a safe message
  (sentinel secret absent from detail and stored message), and leaves no
  files behind.
- Failure after upsert deletes vectors and the file.
- Stream vs non-stream equivalence on the same mocked fixture (same
  parsed answer and citations, token + citations events present).
- Planner-skip direct answer (no document-refusal, no citations).
- Planner invalid JSON fails open to retrieval.
- Malformed JWT `sub` → 401; inactive user → 401.
- Owner-scoped repository methods refuse cross-owner access.
- Chat `document_id`: other/missing doc → 404, non-ready doc → 409.
- `/ready` 200 when deps are up, 503 naming the failing dep when down;
  `/health` remains liveness-only.
- Stream error after partial tokens still persists the partial answer.

### Updated existing tests (behaviour intentionally changed, not weakened)
- `tests/test_services.py`: embedding fallback assertions replaced with
  `EmbeddingError` assertions; `RagService.answer()` tests replaced with
  citation-parser tests; reasoning-node snippet fallback replaced with
  `AgentError`; routing assertion updated (`False` → `direct`); direct
  node test added.
- `tests/test_routers_extended.py`: stream tests now patch
  `AgentService.run_stream` (the graph boundary) instead of the deleted
  inline LLM path; stream failure now expects an `error` event, not a
  snippet fallback; `test_chat_errors_and_document_id` now uses a real
  ready document and asserts 404 for a random document id.

### Results
- Baseline before Phase A (same environment): **49 passed**.
- After Phase A: **60 passed** (49 baseline + 11 new), 0 failed.
  Command (proxy variables cleared — see "Environment note" below):
  `OPENAI_API_KEY=test-key JWT_SECRET_KEY=test-secret-key-for-tests-123456 DATABASE_URL="sqlite+aiosqlite:///:memory:" QDRANT_HOST=":memory:" python -m pytest tests/ -q --no-cov`
  (run in a venv under `/tmp`, not committed).
- Ruff: new/changed backend modules pass `ruff check` (remaining hits in
  the wider repo are pre-existing FastAPI/typing patterns, e.g. `Depends`
  in defaults, and will be addressed by a ruff config in Phase G) and
  `ruff format --check` on the rewritten modules.

## How verified (and what was NOT verified)
- Full pytest suite: 60 passed (above).
- Real boot smoke test (uvicorn, SQLite file DB, in-memory Qdrant, no
  mocks): `/health` → 200 `{"status":"ok"}`, `/ready` → 200
  `{"status":"ready"}`, `/docs` → 200.
- `docker-compose.yml` parses as valid YAML. **Docker was not available
  in this environment (`docker` binary absent), so `docker compose build`
  and a containerised smoke test were NOT run** — that is the first
  thing to verify on a machine with Docker before merging, and the PR
  description says so explicitly.
- No live OpenAI/Qdrant/Postgres run was performed; all external calls
  in tests are mocked, as before. No new metrics are claimed anywhere.

## What remains / known limitations
- Streamed text transiently includes the raw `CITATIONS:` block until
  the `done` event replaces it with the parsed answer (frontend handles
  this; a reload always shows the parsed answer).
- Direct-answer (no-retrieval) streaming yields no per-token events —
  the answer arrives in the `done` event — because the direct node uses
  a non-streaming call. Acceptable for short chit-chat answers; streaming
  the direct node is a Phase F polish item.
- The dev-only JWT secret fallback (above) must not reach production.
- Frontend auth drift (cookie vs JWT lifetime), register FormData
  content-type, rate limiting, observability, hybrid search, reranking,
  and real evaluation are all out of scope for Phase A and belong to
  later phases. README benchmark claims were deliberately NOT rewritten
  here; that is Phase G's documentation work, and this report does not
  endorse those numbers.
- Environment note: this sandbox sets proxy variables whose `NO_PROXY`
  list breaks `httpx` 0.27 URL parsing (`InvalidURL: ':1]'`) when an
  OpenAI client is constructed. Tests were run with all proxy variables
  cleared; this is a sandbox artifact, not a repo defect, and does not
  affect CI or Docker runs.
