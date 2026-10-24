# Phase C — Agentic Architecture: Report

Branch: `phase-c-agentic` (from `phase-b-rag-quality`, stacks on PR #2).
No changes were made to `main`, `phase-a-correctness`, or
`phase-b-rag-quality`, no history was rewritten, no force-push was used,
and no secrets, `.env`, `uploads/`, `node_modules/`, or build output
were committed. Phase A/B behaviour is preserved: one unified
stream/non-stream LangGraph path, chunk-id citations, threshold + MMR
retrieval, and per-owner dedupe are all unchanged except where this
report says a behaviour intentionally changed.

## Graph design (new)

```
planner -> retriever -> grade_retrieval
  -> [rewrite_query -> retriever -> grade_retrieval]  (at most once)
  -> reasoning -> verify
  -> [reasoning again, stricter]                     (at most once)
  -> response
planner -> direct_answer -> response   (no-retrieval questions; verify skipped)
```

See `docs/graph.mmd` for the Mermaid diagram (nodes, conditional
edges, and retry caps). The graph always terminates: `should_retry`
routes to `rewrite` only when the grade is poor AND `retries < 1`, and
`should_regenerate` routes back to `reasoning` only on the first failed
verification (`verify_attempts <= 1`).

### C1 — Grade (score-based, deterministic, no LLM call)

`grade_retrieval_node` (`backend/app/services/agent_service.py`) grades
"good" only if at least one chunk was returned and its top score meets
`RETRIEVAL_GRADE_THRESHOLD` (new setting, default 0.50). Search already
drops chunks below `RETRIEVAL_SIMILARITY_THRESHOLD` (0.30), so the grade
bar is deliberately stricter: a 0.30–0.50 retrieval is weak-but-not-empty
and earns exactly one rewrite. Both thresholds are **unmeasured
starting points, not tuned optima** — Phase D must measure grade
thresholds (and the 0.30 search threshold) before anyone claims they are
tuned. No LLM relevance grading was added: it would add cost, latency,
and a non-deterministic grade that graph tests could not pin down. If
Phase D wants LLM grading, it should be an experiment measured against
this score-based baseline, not a silent replacement.

Grade + reason are stored in state (`retrieval_grade`,
`grade_reason`).

### C1 — Rewrite + retry once

`rewrite_query_node` reuses the planner system prompt and JSON
validation (`PlannerPlan`) with a rewrite prompt that asks for a
*different* self-contained query. On any rewrite failure it reuses the
previous query and records the failure in state `errors` — it never
silently invents a query, and it never aborts the run. It increments
`retries`, which is what enforces the one-retry cap. After a second
poor grade the graph proceeds to reasoning with whatever was retrieved;
empty retrieval still reaches the shared refusal in `reasoning_node`.

### C1 — Verify (keyword/token overlap — honest limits)

`verify_node` runs after reasoning (skipped for direct answers and for
the shared refusal, neither of which makes document claims) and checks,
in order:

1. Every cited chunk id was actually retrieved — this re-uses Phase B's
   `parse_citations`, so an unknown id, a positional `[1]`, or a
   missing `CITATIONS:` block fails verification.
2. The answer body (citations block stripped) shares at least one
   substantive token (lowercased alphanumeric tokens, stopwords
   removed) with the cited chunks' text.

On the first failure it sets `strict_reasoning` and the graph
regenerates once with a tightened system instruction (answer only from
context, cite only used chunks, refuse rather than guess). On a second
failure it replaces the answer with the shared refusal text and empty
citations. State fields: `verify_result` (`pass`/`fail`/`skipped`),
`verify_attempts`, `strict_reasoning`, plus `errors` (recoverable
problems only).

**Honest limits — read this before quoting verification in an
interview:** this is NOT LLM verification and NOT a faithfulness
guarantee. One shared token passes, so the check catches invented
citations, wholly unrelated answers, and missing-citation answers, but
it does NOT catch subtle hallucinations, misattributed-but-overlapping
claims, or answers that quote a chunk while drawing a wrong conclusion
from it. Claiming otherwise would repeat the Phase A/B evaluation
mistake in a new form. A real verifier (LLM-as-judge or RAGAS
faithfulness) belongs in Phase D, measured against this cheap gate.

### C1 — Errors and streaming

- Retriever failures (embedding or Qdrant) now raise typed `AgentError`
  instead of propagating raw exceptions; the router already maps
  `AgentError`/graph failures to a safe 502 / stream `error` event.
  No snippet fallback was reintroduced anywhere.
- Streaming still runs the same graph: `run_stream()` now drains one
  queue carrying both token and status events in emission order, so
  grade/retry/verify steps emit `status` SSE events (`grading`,
  `rewriting`, `verifying`) through the existing router forwarding.
  `frontend/components/ChatPanel.tsx` shows the latest status as a
  small progress line while streaming (and clears it on done/error);
  older clients safely ignore `status` events.
- Known streaming limitation (unchanged in kind from Phase A): if
  verification regenerates, the first reasoning attempt's tokens are
  streamed and then superseded by the `done` event's parsed final
  answer, which is what a reload shows.

### C2 — Document-scoped tool: SKIPPED, with reasons

Only `list_documents` was considered, and it was **not implemented**.
Reasons, stated so a reviewer can disagree on the merits rather than
guess at the omission:

1. The graph has no database session: `AgentService.run/run_stream`
   receive only `owner_id`/`history`/`document_id`. A list node would
   need a document-provider threaded through the router, the service,
   and graph state (a callable in state, as with the stream sink) —
   a new cross-layer plumbing change for one convenience query.
2. The dashboard already lists the user's documents, so the marginal
   user value of "what documents do I have?" inside chat is low.
3. A half-wired tool (e.g. listing from the vector store, or a node
   that cannot actually query the repository) would be exactly the
   kind of fake agentic feature this phase exists to remove.

This is preferable to a fake tool. If a future phase wants it, the
honest design is: router passes a repository-backed provider into
`AgentService`, planner gains an `intent` field, and the node is tested
against a real (SQLite) repository — not added as an untested stub.

### C3 — LangChain removed

Verified by grep over the whole backend: no file imported `langchain`
anything; only `langgraph` was used. `langchain-core==0.2.38` and
`langchain-openai==0.1.23` were therefore removed from
`backend/requirements.txt` (option (a) in the task: remove, since
nothing actually uses them). The README tech-stack row now reads
"LangGraph (direct OpenAI SDK; LangChain removed in Phase C)", and
the Key Features graph description now lists the new nodes
(`grade_retrieval_node`, `rewrite_query_node`, `verify_node`) instead
of the old 4-node description. No other README section was rewritten;
the full README rewrite is Phase G's work, and this report does not
endorse the README's remaining benchmark claims.

## What changed (files)

- `backend/app/services/agent_service.py`: new `grade_retrieval_node`,
  `rewrite_query_node`, `verify_node`, `_verify_support`,
  `_verify_tokens`, `_emit_status`; new state fields (`errors`,
  `retries`, `retrieval_grade`, `grade_reason`, `verify_result`,
  `verify_attempts`, `strict_reasoning`, `status_sink`); new
  conditionals `should_retry` / `should_regenerate`; graph rebuilt
  with grade/rewrite/verify nodes; retriever wrapped in `AgentError`;
  reasoning uses the shared `REFUSAL_TEXT` and a strict mode after a
  verify failure; direct answers record `verify_result="skipped"`;
  `run_stream()` drains a single token+status event queue.
- `backend/app/core/config.py`: new `RETRIEVAL_GRADE_THRESHOLD=0.50`,
  covered by the existing 0..1 validator.
- `backend/requirements.txt`: LangChain lines removed.
- `README.md`: tech-stack row + graph description only (see C3).
- `frontend/components/ChatPanel.tsx`: minimal status-line display
  for Phase C `status` SSE events.
- `backend/tests/test_phase_c.py`: new, 12 tests (below).
- `docs/graph.mmd`: new Mermaid diagram of the Phase C graph.
- `docs/phase-c-report.md`: this file.

## Tests

### New: `backend/tests/test_phase_c.py` (12 tests, compiled graph)

A deterministic fake LLM dispatches planner vs rewrite calls by
prompt shape (rewrite prompts carry a "Previous retrieval query"
marker) and scripts reasoning answers in order, so regeneration tests
can control attempt 1 vs attempt 2. All tests run the compiled graph
via `_agent_graph.ainvoke`, not only individual nodes, except the
grade-node unit test:

- Grade branches: empty → poor, top 0.35 → poor, top 0.95 → good.
- Planner skip → direct answer, no reasoning call, verify skipped.
- Good retrieval → verify pass → response, citations by chunk id.
- Poor retrieval → rewrite (exactly 1 call) → retry → good → answer.
- Poor after retry → proceeds with retrieved chunks (retries == 1,
  no second rewrite).
- Empty after retry → shared refusal, no citations, verify skipped.
- Verify fail → regenerate once → pass (2 reasoning calls, final
  answer is the second attempt).
- Verify fail twice → refusal, empty citations (2 reasoning calls,
  never a third).
- Unknown citation id → fails verification → refusal after
  regeneration.
- Rewrite LLM failure → previous query reused, error recorded in
  state, run still succeeds.
- Retriever (embedding) error → `AgentError` from the graph.
- Streaming → `status` events include `grading` and `verifying`,
  final event is `done` with the parsed answer.

### Results

- Before Phase C (Phase B head): **83 passed**.
- After Phase C: **95 passed** (83 + 12 new), 0 failed.
  Command (proxy variables cleared, as in Phase A/B — the sandbox's
  bracketed `NO_PROXY` entries break httpx URL parsing otherwise):
  `env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy -u
  ALL_PROXY -u all_proxy -u NO_PROXY -u no_proxy OPENAI_API_KEY=test-key
  JWT_SECRET_KEY=test-secret DATABASE_URL=sqlite+aiosqlite:///:memory:
  QDRANT_HOST=:memory: ENVIRONMENT=test /tmp/rag-venv/bin/python -m
  pytest tests/ -q --no-cov`
- Ruff: `ruff check` passes on the changed modules and
  `ruff format` was applied to them. Remaining ruff hits in
  `config.py` (unused `Path` import, `List` vs `list`, quoted
  annotation) are pre-existing and untouched, as in Phase B.
- No existing tests were weakened. No existing test file was edited;
  Phase A/B tests pass unchanged against the new graph, including
  the stream/non-stream equivalence test.

## How verified (and what was NOT verified)

- Full pytest suite: 95 passed (above). All external calls remain
  mocked; no live OpenAI/Qdrant/Postgres run was performed.
- Docker was not available in this environment (`docker` binary
  absent), so `docker compose build` and a containerised smoke test
  were NOT run — same caveat as Phase A/B, and the first thing to
  verify on a machine with Docker before merging.
- Frontend: the ChatPanel status line is a small additive render
  backed by existing SSE parsing; `tsc`/`next build` were NOT run
  here (no `node_modules` in this environment). CI's frontend job
  must confirm it, as in Phase B.
- No retrieval-quality measurement was made: the 0.50 grade
  threshold, like the 0.30 search threshold, is an unmeasured
  starting point. Phase D must measure hit-rate/recall and
  verification accuracy before any threshold is described as tuned.

## Known limitations

- The overlap verifier is coarse (see "Honest limits" above). It is a
  cheap gate, not a faithfulness proof.
- A verify-failed first attempt's tokens are streamed before being
  superseded by the final `done` answer (see "Errors and streaming").
- The grade uses only the top retrieved score; it does not consider
  score distribution, chunk count beyond non-empty, or query–chunk
  topical match. A top-heavy but otherwise weak retrieval grades
  "good".
- The rewrite is a single LLM call with no quality check on the
  rewritten query beyond JSON validity; a bad rewrite is bounded by
  the one-retry cap, not prevented.
- `list_documents` (C2) was deliberately skipped — see C2 above.
- The dev-only JWT secret fallback from Phase A is unchanged and
  must still not reach production.
