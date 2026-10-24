# Phase B — RAG Quality: Report

Branch: `phase-b-rag-quality` (from `phase-a-correctness`, stacks on PR #1).
No changes were made to `main` or `phase-a-correctness`, no history was
rewritten, no force-push was used, and no secrets, `.env`, `uploads/`,
`node_modules/`, or build output were committed.

## Decisions (documented choices)

- **Dedupe return value:** re-uploading the same bytes for the same owner
  returns the existing document id (idempotent return), not a 409. A
  different owner uploading the same bytes gets a new document (vectors
  are isolated by `owner_id`). A previous `processing`/`error` row does
  not block a retry -- only a `ready` row is treated as a dedupe hit.
- **Similarity threshold default 0.30:** a sensible starting default for
  cosine similarity on `text-embedding-3-large`, explicitly NOT a
  measured optimum. Phase D must measure hit-rate/recall at several
  thresholds before anyone claims it is tuned.
- **Dimensions NOT reduced:** `text-embedding-3-large` stays at 3072 by
  default. Reducing dimensions without an eval baseline would trade
  quality for cost on faith; Phase D measures the tradeoff first.
- **Magic-byte sniffing is stdlib, not python-magic:** the four supported
  types (PDF `%PDF-`, DOCX ZIP `PK\x03\x04`, text/Markdown non-magic)
  are fully covered by a small sniffing function, so no new heavy
  dependency was justified.
- **Citation ids:** a chunk's stable id is the Qdrant point id
  (`uuid5(owner, document, content_hash)`); chunks retrieved from older
  payloads without a stored id fall back to `document_id:chunk_index`.
  The model cites the id shown in its `<context>` block.

## What changed

### B1 — Ingestion
- `backend/app/services/chunking_service.py`: new `extract_segments()`
  (PDF pages, DOCX headings/tables in document order, Markdown headings)
  alongside the backwards-compatible `extract_text()`; new
  `ScannedDocumentError` for image-only PDFs (pages with images but no
  extractable text) with a user-facing message. DOCX tables are now
  extracted as `col | col` text instead of being dropped.
- `backend/app/services/document_service.py`: streaming upload in 1 MiB
  bounded reads (never `read()` without a size) with SHA-256 hashing
  during the stream; oversize uploads are rejected at 413 after at most
  one extra bounded chunk, with the partial file deleted. Magic-byte
  validation (`sniff_mismatch()`) runs after streaming, before any DB
  row is created; mismatches are 422. Extraction and chunking run via
  `asyncio.to_thread`, off the event loop.

### B2 — Chunking
- `chunking_service.py`: sentence/paragraph-aware packing (whole
  sentences up to 512 tokens, trailing sentences carried as the 64-token
  overlap; token-window fallback only for a single oversized sentence
  or boundary-less text). Every `TextChunk` now carries `page`,
  `section`, `char_start`/`char_end` offsets into the joined text, and a
  SHA-256 `content_hash`. Defaults remain 512/64 from config.
- `vector_store_service.py`: the Qdrant payload for each point now
  stores `chunk_id`, `page`, `section`, `char_start`, `char_end`,
  `content_hash` in addition to the previous fields.

### B3 — Dedupe
- `backend/app/models/document.py` + `backend/alembic/versions/002_content_hash.py`
  (new migration, no `create_all`): `documents.content_hash` (SHA-256 of
  the raw bytes) with an `(owner_id, content_hash)` index.
- `backend/app/repositories/document_repository.py`:
  `create(..., content_hash)` and `get_by_content_hash_for_owner()`.
- `document_service.py`: per-owner ready-document dedupe (above) and
  chunk-level dedupe (identical chunk hashes within one document kept
  once, renumbered). `vector_store_service.py` additionally dedupes by
  stable point id on upsert, so the same chunk can never create two
  points.

### B4 — Retrieval
- `backend/app/core/config.py`: `RETRIEVAL_SIMILARITY_THRESHOLD=0.30`,
  `RETRIEVAL_FETCH_K=20`, `MMR_LAMBDA=0.7`, `MAX_CONTEXT_TOKENS=6000`,
  `HISTORY_MAX_TOKENS=2000`, `CHAT_MAX_TOKENS=1000`, with validators
  (embedding dims 1..3072, threshold/lambda in 0..1).
- `vector_store_service.py`: `search()` fetches a pool (`fetch_k`, at
  least `top_k`), filters scores below the threshold (also passed to
  Qdrant as `score_threshold`), then MMR-selects the final top-k
  (`mmr_select()`, cosine-based; falls back to score order with a log
  line when candidate vectors are unavailable, as with mocked clients).
  New `Reranker` protocol + `IdentityReranker` default: Phase D can plug
  a real reranker into `VectorStoreService(reranker=...)` without
  changing call sites.
- Collection-dimension mismatch: `ensure_collection()` now raises
  `CollectionDimensionMismatchError` naming both dimensions when an
  existing collection's vector size differs from the configured one. It
  never silently recreates or deletes the collection. (Transient
  inspection failures still defer with a warning, as in Phase A.)

### B5 — Prompting
- `backend/app/services/agent_service.py`: reasoning prompt now uses
  delimited context blocks (`<context id=... document=... chunk=...
  page=... section=...>`) and explicitly instructs that document text
  is DATA, not instructions (imperative language inside a block is to
  be summarised, never obeyed). Context is truncated lowest-score first
  and history most-recent first to their token budgets (with a log line
  when context is truncated); reasoning and direct-answer calls pass
  `max_tokens=CHAT_MAX_TOKENS`. The empty/low-confidence refusal path
  is unchanged and shared: threshold-filtered retrieval returning
  nothing reaches `reasoning_node` with no chunks, which refuses, and
  both chat endpoints run this same graph (Phase A unification kept).
- `rag_service.py`: `parse_citations()` now validates by chunk id
  (see B6). The old positional format is dropped, not substituted.

### B6 — Citations
- Only chunks actually cited by the model (by id) are returned, with
  `chunk_id`, `page`, `section`, `score`, and snippet.
  `backend/app/schemas/chat.py`: `CitationSchema` gains optional
  `chunk_id`/`page`/`section` (defaults keep pre-Phase-B stored
  citations valid).
- `frontend/lib/api.ts`: `Citation` type gains the same optional
  fields. `frontend/components/ChatPanel.tsx`: citation rows render
  `p. N` and the section when present, omitted otherwise. No other
  frontend change (full redesign is Phase F).

## Tests

### New: `backend/tests/test_phase_b.py` (23 tests)
- PDF page numbers; DOCX tables + headings; Markdown headings;
  scanned-PDF error at extraction and at service level (422, "scanned"
  in detail, no file left).
- Magic-byte mismatch -> 422 (PDF/DOCX/text cases).
- Oversize rejection with a tracking file object: every read is bounded
  to <= 1 MiB, never unbounded; 413; no file left.
- Threadpool: `extract_segments` and `chunk_text` are invoked via
  `asyncio.to_thread` during ingestion.
- Sentence-aware chunking: chunk text equals the original substring at
  its offsets, chunks end on sentence boundaries, hashes are correct,
  offsets are monotonic; chunk page/section metadata.
- Document dedupe: same bytes + same owner -> same id, one upsert;
  same bytes + different owner -> new id. Chunk dedupe within a
  document (identical sentence kept once, renumbered, chunk_count 2).
- MMR diversity (near-duplicate high scorers do not fill top-k when a
  diverse chunk exists); identity reranker keeps order; threshold
  filtering (0.9 kept, 0.2/0.05 dropped at 0.30); collection-dimension
  mismatch raises naming both dims; upsert payload carries page,
  section, chunk id, content hash, and collapses duplicate points.
- Empty retrieval -> shared refusal ("couldn't find", no citations).
- Citation-id validation (valid kept with page/section, unknown and
  duplicate ids dropped, positional `[1]` not substituted); context
  budget drops lowest-score first; history budget keeps most recent.

### Updated existing tests (behaviour intentionally changed, not weakened)
- `tests/test_phase_a.py`: stream/non-stream equivalence fixture now
  cites by chunk id (`_CHUNK.chunk_id`).
- `tests/test_services.py`: citation-parser test now uses chunk ids and
  asserts positional citations are dropped; agent-nodes reasoning
  fixture now cites by chunk id. A DOCX body-walk fallback was added
  to the code (not the test) so the old mocked-DOCX test still passes:
  when the ordered body walk yields nothing, extraction falls back to
  the paragraph/table walk.

### Results
- Before Phase B (Phase A head): **60 passed**.
- After Phase B: **83 passed** (60 + 23 new), 0 failed.
  Command (all proxy variables cleared -- the sandbox's bracketed
  `NO_PROXY` entries break httpx URL parsing otherwise, as in Phase A):
  `env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy -u
  ALL_PROXY -u all_proxy -u NO_PROXY -u no_proxy OPENAI_API_KEY=test-key
  JWT_SECRET_KEY=test-secret DATABASE_URL=sqlite+aiosqlite:///:memory:
  QDRANT_HOST=:memory: ENVIRONMENT=test /tmp/rag-venv/bin/python -m
  pytest tests/ -q --no-cov`
- Ruff: `ruff check` passes on all Phase B modules; `ruff format`
  applied to the changed modules. Two pre-existing ruff hits elsewhere
  (quoted `"User"` annotation, `Sequence` import) were left untouched.
- Alembic: `alembic upgrade head` against a fresh SQLite database
  applies `001_initial -> 002_content_hash` and the
  `ix_documents_owner_content_hash` index exists afterwards.

## How verified (and what was NOT verified)
- Full pytest suite: 83 passed (above). All external calls (OpenAI,
  Qdrant) remain mocked in tests; no live OpenAI/Qdrant/Postgres run
  was performed.
- Docker was not available in this environment (`docker` binary
  absent), so `docker compose build` and a containerised smoke test
  were NOT run -- same caveat as Phase A, and the first thing to verify
  on a machine with Docker before merging.
- Frontend: the ChatPanel change is two optional render fields backed
  by the updated `Citation` type; `tsc`/`next build` were NOT run here
  (no `node_modules` in this environment). The change is minimal and
  backwards-compatible, but CI's frontend job must confirm it.
- No live retrieval-quality measurement was made in this phase; the
  threshold/MMR defaults are unmeasured starting points (see below).

## Metrics baseline note for Phase D (no invented numbers)
Phase B adds no benchmark numbers, deliberately. What Phase D must
measure, in order, before changing any default:
1. Retrieval hit-rate@k and MRR on a real golden set, at thresholds
   0.0 / 0.2 / 0.30 / 0.4 / 0.5, to decide whether 0.30 survives.
2. The same, with MMR on vs off and at lambda 0.5 / 0.7 / 0.9, to decide
   whether MMR helps or only reorders.
3. Embedding-dimension tradeoff: 3072 (current) vs 1536 vs 512 on the
   same corpus, including re-index cost -- only then consider reducing
   dimensions.
4. Citation precision (cited ids actually supporting the answer) and
   refusal accuracy on out-of-corpus probes, now that citations are
   id-validated.
5. Ingestion cost/latency of the new pipeline (threadpool extraction,
   streaming upload) vs the Phase A baseline, on the same documents.
Until those numbers exist, README/docs must not claim any retrieval
improvement from Phase B -- only that the mechanisms are in place and
tested.

## Known limitations
- Sentence segmentation is regex-based (terminal punctuation / line
  breaks); it does not handle abbreviations, decimals, or languages
  without sentence punctuation specially. Oversized sentences still
  fall back to token windows, where offsets are token-derived.
- MMR needs candidate vectors from Qdrant (`with_vectors=True`); if a
  future Qdrant client configuration drops them, selection silently
  falls back to score order (logged at debug level).
- Threshold filtering happens both in Qdrant (`score_threshold`) and
  in code, so a mocked client that ignores `score_threshold` still
  gets filtered -- but a real client returning scores on a different
  scale (e.g. dot product) would make 0.30 meaningless. The configured
  distance is cosine, and that assumption should be re-checked if the
  collection configuration ever changes.
- Scanned-PDF detection relies on `page.images`; a scanned page whose
  images are not exposed by pdfplumber would still surface as an empty
  document error rather than a scanned error.
- DOCX heading detection uses paragraph style names starting with
  "Heading"; documents with custom heading styles will have
  `section=None` for those blocks.
- The `search()` `threshold=None` argument means "use the configured
  default"; callers needing unfiltered results pass `threshold=0.0`.
  This is documented in the docstring but is slightly surprising.
