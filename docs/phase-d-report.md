# Phase D — Real Evaluation: Report

Branch: `phase-d-evaluation` (from `phase-c-agentic`, stacks on PR #3).
No changes were made to `main`, `phase-a-correctness`,
`phase-b-rag-quality`, or `phase-c-agentic`, no history was rewritten,
no force-push was used, and no secrets, `.env`, `uploads/`,
`node_modules/`, or build output were committed. No production code
under `backend/app/` was changed in this phase: Phase A–C behaviour
(one LangGraph path, threshold + MMR, id citations, dedupe) is
preserved exactly. The only README change is a pointer update for
the deleted script (full README rewrite is Phase G).

## D1 — Deleted: the simulated evaluation

- Deleted `backend/scripts/evaluate_rag.py` (fabricated scores from
  hardcoded strings, fake corpus, literal `97.0` coverage).
- Deleted `backend/eval_metrics_report.json` and
  `backend/eval_metrics_report.md` (outputs of that script).
- Deleted `backend/tests/test_evaluation.py`: it asserted the
  simulated script's outputs (groundedness ≥ 97%, hallucination ≤
  1%, coverage claims). It tested nothing else, so deleting it
  removes no legitimate coverage of other behaviour; its replacement
  is `backend/tests/test_eval.py` (see Tests). No other test or
  import referenced the deleted script; a repo-wide search confirms
  the only remaining mention is this report's predecessor note in
  the README pointer (updated to point at the new runner).

## D2 — Built: `backend/eval/` (not in the production import path)

- Corpus: 10 self-written documents, all prose written for this
  evaluation (no copied copyrighted text), listed in
  `backend/eval/corpus/corpus.json`: `vector-databases.txt`,
  `qdrant.md`, `langgraph.pdf`, `chunking.txt`, `embeddings.md`,
  `jwt-auth.docx`, `docker.txt`, `postgres.md`, `sse.txt`, `mmr.txt`.
  Formats: txt, md, pdf, docx. The PDF is produced by the
  dependency-free writer in `backend/eval/generate_corpus.py` and
  was verified readable by pdfplumber (1 page, full text); the DOCX
  is produced with python-docx (already a production dependency).
  `langgraph_source.txt` / `jwt-auth_source.txt` are generator
  inputs, not ingested documents. Topics share terms with different
  numbers (HNSW in two docs, different values) so wrong-document
  answers are detectable.
- Golden set: 55 answerable questions (`golden/golden.json`), each
  with a source document and expected keywords.
- Unanswerable probes: 16 (`golden/unanswerable.json`).
- Prompt-injection probes: 6 (`golden/injection.json`), scored by a
  fixed forbidden-string rule (no vibe judgements).
- `backend/eval/README.md` documents provenance and extension.

## D3 — Runner: `backend/eval/run_eval.py`

- Ingests the corpus through the real `DocumentService`
  (chunking, embedding, Qdrant) and runs the real `AgentService`
  graph for every question. Retrieval metrics are measured with a
  second call to the same `VectorStoreService.search`.
- Two modes, never mixed in one file (every record carries `mode`):
  - `--mode offline`: deterministic fake embedding (feature-hashed
    bag of words, 3072-d) + fake LLM (copies the best-overlapping
    context chunk). Pipeline smoke test ONLY.
  - `--mode live`: real OpenAI embeddings, real graph LLM calls,
    LLM-as-judge at temperature 0 with the fixed rubric committed
    in `backend/eval/judge.py`. Judge failures are recorded as
    `judge_error` and excluded, never counted as pass/fail.
- Metrics (`backend/eval/metrics.py`, pure functions): hit-rate@1/3/5,
  MRR, citation precision (refusals excluded), hand-rolled
  faithfulness (sentence/token overlap vs cited chunks — coarse by
  design, documented limits; RAGAS was NOT added, deliberately: a
  new dependency's faithfulness score would itself need validation),
  refusal accuracy (fixed marker rule), injection pass rate (fixed
  forbidden-string rule), p50/p95 latency, and token/cost
  ESTIMATES (tiktoken counts priced with constants dated
  2026-10-24 in code — the agent service does not return usage, so
  these are never presented as metered usage).
- Output: `docs/eval/<run-id>/summary.json` + `results.jsonl`
  (one record per question). Runs never overwrite earlier runs.
- Variant flags actually implemented: `--threshold`,
  `--no-mmr`, `--limit` (cost control), `--variant`.

Reproduce the offline smoke run:

```bash
cd backend
python eval/run_eval.py --mode offline
```

## D4 — Results actually run (offline smoke ONLY)

Both runs below are `mode: offline-pipeline-smoke`. They prove the
pipeline runs end to end (ingest → retrieve → graph → metrics →
output). They are NOT quality measurements of the real system, and
must not be quoted as such.

| Run | hit@1 | hit@3 | hit@5 | MRR | Citation precision | Faithfulness | Refusal acc. | Injection pass | Keyword score | Latency p50/p95 |
|---|---|---|---|---|---|---|---|---|---|---|
| `offline-smoke-1` (current config, threshold 0.30) | 0.3636 | 0.3636 | 0.3636 | 0.3636 | 1.0 | 1.0 | 1.0 (16/16) | 1.0 (6/6) | 0.3636 | 0.031s / 0.047s |
| `offline-smoke-threshold-off` (threshold 0.0) | 0.9818 | 1.0 | 1.0 | 0.9909 | 1.0 | 1.0 | 0.5625 (9/16) | 1.0 (6/6) | 1.0 | 0.127s / 0.150s |

Raw outputs: `docs/eval/offline-smoke-1/` and
`docs/eval/offline-smoke-threshold-off/` (77 records each:
55 golden + 16 unanswerable + 6 injection).

What these two runs actually teach (and do not teach):

- The pipeline works: real ingestion of all four formats,
  real Qdrant (in-memory) search, real graded graph with
  rewrite/verify, real citation parsing, and all metric code
  paths executed, including refusals and injection scoring.
- The current-config hit rate (0.36) is a FAKE-EMBEDDING
  ARTIFACT, not evidence about the real 0.30 threshold: hashed
  bag-of-words cosines between a short question and a long chunk
  are typically ~0.10–0.30, so most correct chunks fall below
  0.30 and retrieval returns empty (35/55 questions retrieved
  zero chunks). Real text embeddings give much higher topical
  cosines. Do NOT retune the threshold on this data.
- The threshold-off run shows the threshold's real function in
  this pipeline: with no threshold, hit@5 is 1.0 but refusal
  accuracy collapses to 0.5625, because off-topic questions
  retrieve something and the (fake) LLM answers from it instead
  of refusing. The threshold is what makes refusals work here;
  the live run must measure whether that trade-off holds with
  real embeddings and a real LLM, which refuses differently.
- Citation precision and faithfulness are 1.0 in both runs
  because the fake LLM copies a retrieved chunk and cites it —
  another reason these numbers say nothing about real answer
  quality. They validate the metric plumbing, not the model.

## D5 — Hybrid search / reranker: NOT implemented, with evidence

No hybrid search and no reranker were implemented in this phase.
Reason: the brief requires a measured gain, and no live (or even
real-embedding) data exists yet — the only data is offline smoke
data from a fake embedding, which cannot rank retrieval methods.
Implementing hybrid/RRF or a cross-encoder now would be exactly
the unmeasured "improvement" this phase was created to stop.

The extension point is ready and documented: Phase B's
`Reranker` protocol in `backend/app/services/vector_store_service.py`
(`IdentityReranker` is the current default; a real reranker is
passed to `VectorStoreService` without changing call sites).

The exact experiment to run once the live run is unblocked:

1. Run live with current config; record hit@5, MRR, judge
   correctness, refusal accuracy, latency, cost as the baseline.
2. Run live again with hybrid (Qdrant sparse/BM25 + RRF fusion)
   and again with a reranker, each as its own `--variant` run.
3. Keep a variant only if it improves hit@5/MRR or judge
   correctness without degrading refusal accuracy or latency
   beyond the recorded cost — and report any metric that got
   worse, not just the winners.

## BLOCKED (the only open item in Phase D)

**Live evaluation has NOT been run.** No `OPENAI_API_KEY` is
present in this sandbox's environment (checked by presence only;
no key was printed, read from any `.env` file, or requested from
the user during this phase). The runner refuses to fabricate a
live run: with a placeholder or absent key it exits with the
blocked message instead of writing live-labelled output.

What is needed: a valid `OPENAI_API_KEY` (with enough quota for
~77 questions × planner/reasoning/judge calls — use `--limit`
to cap cost on a first run). Then:

```bash
cd backend
OPENAI_API_KEY=<your key> QDRANT_HOST=:memory: \
  python eval/run_eval.py --mode live --limit 20
```

Full live run (no `--limit`) once the capped run looks sane.
Live outputs go to a new `docs/eval/<run-id>/` directory and must
be committed with their run id; the README benchmark table is
Phase G's job to replace from those outputs, not from offline
smoke numbers.

## Tests

- New `backend/tests/test_eval.py` (8 tests): golden schema +
  source-doc existence, corpus files + format variety,
  unanswerable/injection counts, hit-rate/MRR on a handmade
  example, citation precision, refusal/injection rules,
  faithfulness gate, and a runner offline end-to-end test on a
  tiny 2-doc fixture (tests the runner, not quality).
- `tests/test_eval.py`: **8 passed**. Ruff check + format clean
  on `backend/eval/` and `tests/test_eval.py`.
- Full suite: **74 passed, 28 failed** — and the 28 failures are
  IDENTICAL (same test names, verified by diff) on a pristine
  `phase-c-agentic` worktree (67 passed, 28 failed there; the
  +7 passed on this branch is exactly the 8 new tests minus the
  1 deleted simulated test). Phase D introduces no regressions;
  the 28 pre-existing failures (mostly `httpx.InvalidURL` when
  tests construct real OpenAI clients in this sandbox) are a
  Phase A–C / environment issue for a later phase, not something
  this phase introduced or silently fixed.

## Known limitations

- Live quality (judge correctness, real hit-rate/MRR, real
  latency/cost, threshold tuning) is entirely unmeasured until
  the blocked item above is resolved.
- Faithfulness is a token-overlap gate, not entailment; the
  judge is a single LLM call, not a panel; latency in offline
  runs (~0.03–0.15s) is fake-backend time, not production latency.
- The injection rule for one probe (inj-04) is strict: any
  occurrence of the forbidden word, even inside a refusal
  sentence, fails it. That strictness is documented in the probe
  file and is preferable to a judgement call, but a live LLM
  that refuses while naming the answer would fail that probe.
- Docker compose build + smoke test were NOT re-run in this
  phase: no production code changed, and the phase's own
  verification is the test suite + offline eval runs above.
  Phase G's compose smoke test remains the deployment check.
