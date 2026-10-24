# Resume bullets and interview talking points

Every number below is verified: backend/frontend test counts and
coverage are from Phase G runs on the phase-g branch (see
`docs/phase-g-report.md`); corpus/golden counts are from
`backend/eval/`; offline smoke numbers are labelled as pipeline
smoke only. **Live evaluation has not been run** (blocked on a valid
`OPENAI_API_KEY`), so no live accuracy, latency, or cost number
appears here. If an interviewer asks for one, say it is pending --
that is the honest answer, and the eval harness to run it is already
built.

## Resume bullets (pick 5-6)

1. Built an Agentic RAG Knowledge Assistant (Next.js 14, FastAPI,
   LangGraph, Qdrant, PostgreSQL, OpenAI) with one LangGraph
   pipeline serving both chat and SSE streaming: planner ->
   retriever -> grade -> bounded rewrite/retry -> reasoning ->
   verify -> response, plus a direct-answer branch.
2. Implemented grounded, chunk-id citations validated against
   retrieved chunks (only cited, retrieved chunks are shown, with
   page/section and snippet), a similarity threshold with MMR
   selection, and a shared empty/low-confidence refusal path.
3. Hardened ingestion: content-validated, size-streamed uploads;
   sentence-aware 512/64-token chunking with page/section/hash
   metadata; per-owner content-hash dedupe; background queue with
   progress and retry -- and removed a silent fallback-embedding
   bug that had corrupted the vector index.
4. Built a real evaluation harness from scratch (10 self-written
   documents, 55 golden questions, 16 unanswerable probes, 6
   prompt-injection probes) after deleting a simulated benchmark
   that fabricated its scores; ran offline pipeline smoke runs
   and documented, honestly, that live quality measurement is
   pending a valid API key.
5. Shipped production hardening: httpOnly auth cookies with logout
   revocation, owner-scoped repositories and vector filters, rate
   limits and login lockout, circuit breaker, structured logging
   with request IDs, Prometheus-text metrics, and Alembic-owned
   schema migrations in the container entrypoint.
6. Set up CI with a measured coverage gate (backend 122 tests,
   91% coverage, gate 80%), Ruff, frontend lint/typecheck/Vitest/
   `next build`/Playwright E2E, Docker image builds, and a compose
   smoke test; rewrote all docs to remove unverifiable claims.

## Interview talking points

- **Why RAG, and why Qdrant?** Answers must come from the user's
  own documents, not model memory, and must be citable. Qdrant
  gives filtered dense search (cosine) with payload metadata
  (owner, document, page, section) in one store; Postgres owns
  relational data (users, documents, conversations) because it
  is the right tool for transactions and ownership, not vectors.
- **Why `text-embedding-3-large` at 3072 dims?** It is the
  configured default, validated (1..3072) with a startup
  collection-dimension check. Reducing dimensions is supported
  by the model and the config, but was not done: no live data
  justified the trade-off, and changing dims against an existing
  collection silently breaks search -- which is why the mismatch
  check exists.
- **Why 512/64 chunks?** A starting default from the original
  design, kept through Phases A-G because no live eval data
  justified retuning it. Say that plainly; do not claim it is
  tuned. The chunker is sentence/paragraph-aware with overlap,
  and stores offsets/page/section/hash so chunks are traceable.
- **Why LangGraph, and what does each node do?** One pipeline
  for both endpoints, so behaviour cannot drift (it did, before
  Phase A -- the stream path was a separate inline RAG path).
  Planner (LLM JSON plan, fail-open to retrieval, direct-answer
  branch); retriever (embed + owner-filtered, thresholded, MMR
  search); grade (score-based, no LLM); rewrite (one retry);
  reasoning (GPT-4o, delimited context marked as data); verify
  (cited ids were retrieved + token overlap, one regenerate,
  then refuse); response (parse + validate citations).
- **How is hallucination controlled?** Three layers, none of
  which is a guarantee: strict grounded prompt + delimited
  context, threshold + refusal on empty/low-confidence retrieval,
  and verify-node citation validation with regenerate-or-refuse.
  Verify is overlap-based, not LLM faithfulness -- say so.
- **How is multi-user isolation achieved?** Owner-scoped
  repositories, an `owner_id` Qdrant filter on every search and
  delete, and a chat `document_id` ownership/status check.
  Safety does not rest on any single layer.
- **What happens when retrieval fails?** Empty retrieval refuses
  with a fixed message; poor retrieval rewrites once; embedding
  failure marks the document `error` and cleans up (never a
  fallback vector); Qdrant failure trips a circuit breaker
  (3 failures, 60s cooldown); agent failures surface as a safe
  502, never raw exception text.
- **What are the limitations?** Live quality unmeasured; thresholds
  untuned; verify is overlap, not faithfulness; rate limits and
  quotas are single-instance/in-memory; refresh tokens deferred;
  daily token budget is an estimate; mypy has 14 pre-existing
  errors; pip-audit has 71 records (documented accepted risk,
  must be upgraded before any public deploy); live deployment
  pending credentials; Docker smoke not run in the sandbox
  (CI covers it). Naming these unprompted is the strongest
  interview signal in this project: it proves the numbers that
  *are* claimed were actually measured.

## What NOT to claim

- Any live accuracy, groundedness, hallucination, latency, or
  cost number (never measured).
- Offline smoke scores (e.g. hit@5 0.3636 / 0.9818) as system
  quality -- they are fake-embedding artifacts.
- 97% coverage, 100% grounded, 0% hallucination, <1.5s latency,
  "52 documents indexed" -- all from the deleted simulated
  benchmark; the measured coverage is 91% (122 backend tests).
- Hybrid search, reranking, semantic long-term memory, or a
  verified production deployment -- none exists in v1.0.0.
- "Production-grade" without the qualifiers in
  `docs/phase-g-report.md` (scans not clean, mypy not clean,
  single-instance limits, deploy pending).
