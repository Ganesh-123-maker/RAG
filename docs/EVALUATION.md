# Evaluation

This document replaces any benchmark claim that is not backed by a run
output under `docs/eval/`. If a number is not in a committed run
output, it is not quoted.

## Corpus and golden set (Phase D)

- **Corpus:** 10 self-written documents in `backend/eval/corpus/`
  (listed in `corpus/corpus.json`; `langgraph_source.txt` and
  `jwt-auth_source.txt` are generator inputs, not corpus documents).
  Formats: `.txt`, `.md`, `.pdf` (dependency-free writer in
  `generate_corpus.py`, verified readable by pdfplumber), `.docx`
  (python-docx). All text is self-written; product names and public
  facts are ordinary factual references in the authors' own words.
  Topics are distinct enough for retrieval scoring, with deliberate
  near-collisions (e.g. HNSW appears in both the vector-database and
  Qdrant documents, with different numbers) so a wrong-document
  answer is detectable.
- **Golden set:** 55 answerable questions (`golden/golden.json`), each
  with a source document and expected keywords; 16 unanswerable
  probes (`golden/unanswerable.json`); 6 prompt-injection probes
  (`golden/injection.json`) scored by a fixed forbidden-string rule.
- **Runner:** `backend/eval/run_eval.py` (see `backend/eval/README.md`
  for the full metric definitions).

## Mode labels -- do not mix them

| Mode | What it runs | What it proves |
|---|---|---|
| `offline-pipeline-smoke` | Fake hashed bag-of-words embeddings + a fake LLM that copies the best-overlapping context chunk; real ingestion, real in-memory Qdrant search, real graded graph, real citation parsing, real metric code | The pipeline runs end to end. **NOT a quality measurement.** |
| `live` | Real embeddings, real graph, real GPT-4o, LLM-as-judge at temperature 0 with a fixed rubric | Answer quality, retrieval quality, latency, cost -- the only mode whose scores may be quoted as system quality. **Never run as of v1.0.0.** |

## Metrics (and their limits)

- Retrieval: hit-rate@1/@3/@5 and MRR against the golden source doc.
- Citation precision: cited chunk ids actually retrieved / all cited
  ids (refusals excluded -- they have no claims to cite).
- Faithfulness: hand-rolled sentence/token overlap against cited
  chunks. Coarse by design: it catches unsupported answers, not
  subtle hallucinations. RAGAS was not added (optional in the brief):
  a hand-rolled check with clear limits was preferred over a new
  dependency whose faithfulness score would itself need validation.
- Correctness, live: LLM-as-judge, fixed rubric, temperature 0;
  judge failures are recorded as `judge_error` and excluded, never
  counted as pass or fail. Correctness, offline: keyword overlap
  only, labelled as such.
- Refusal accuracy: fixed marker rule (see `metrics.py`).
- Injection pass rate: fixed forbidden-string rule per probe.
- Latency: p50/p95/mean over golden questions (search + graph).
- Cost: tiktoken-based estimates, not metered usage.

## Runs actually executed

### Offline smoke (only runs executed)

| Run | hit@1 | hit@3 | hit@5 | MRR | Citation precision | Faithfulness | Refusal acc. | Injection pass | Latency p50/p95 |
|---|---|---|---|---|---|---|---|---|---|
| `offline-smoke-1` (current config, threshold 0.30) | 0.3636 | 0.3636 | 0.3636 | 0.3636 | 1.0 | 1.0 | 1.0 (16/16) | 1.0 (6/6) | 0.031s / 0.047s |
| `offline-smoke-threshold-off` (threshold 0.0) | 0.9818 | 1.0 | 1.0 | 0.9909 | 1.0 | 1.0 | 0.5625 (9/16) | 1.0 (6/6) | 0.127s / 0.150s |

Raw outputs: `docs/eval/offline-smoke-1/` and
`docs/eval/offline-smoke-threshold-off/` (77 records each: 55 golden
+ 16 unanswerable + 6 injection).

What these runs teach, and what they do not:

- The pipeline works end to end, including refusals and injection
  scoring, and the metric code paths all execute.
- The current-config hit rate (0.36) is a **fake-embedding artifact**,
  not evidence about the real 0.30 threshold: hashed bag-of-words
  cosines between a short question and a long chunk are typically
  ~0.10-0.30, so most correct chunks fall below 0.30 and retrieval
  returns empty (35/55 questions retrieved zero chunks). Real text
  embeddings give much higher topical cosines. **Do NOT retune the
  threshold on this data.**
- The threshold-off run shows the threshold's real function in this
  pipeline: with no threshold, hit@5 is 1.0 but refusal accuracy
  collapses to 0.5625, because off-topic questions retrieve
  something and the (fake) LLM answers from it instead of refusing.
  The live run must measure whether that trade-off holds with real
  embeddings and a real LLM, which refuses differently.
- Citation precision and faithfulness are 1.0 in both runs because
  the fake LLM copies a retrieved chunk and cites it -- another
  reason these numbers say nothing about real answer quality. They
  validate the metric plumbing, not the model.

### Live run: BLOCKED (not run, not approximated)

No `OPENAI_API_KEY` was present in any phase sandbox (checked by
presence only; no key was printed, read from any `.env` file, or
requested during development). The runner refuses to fabricate a live
run: with a placeholder or absent key it exits with the blocked
message instead of writing live-labelled output.

To run it (maintainer, with a key that has quota for ~77 questions x
planner/reasoning/judge calls -- use `--limit` first):

```bash
cd backend
OPENAI_API_KEY=sk-... python eval/run_eval.py --mode live --limit 20
```

Full run without `--limit` once the capped run looks sane. Outputs go
to a new `docs/eval/<run-id>/` directory and must be committed with
their run id. Only then may README numbers be updated from them, with
the date, model names, corpus size, and the exact command recorded
alongside.

## Hybrid search / reranker experiment (not yet run)

No hybrid search and no reranker are implemented, because there is no
live (or even real-embedding) data to show a gain, and the offline
smoke data cannot rank retrieval methods. The extension point is
ready: Phase B's `Reranker` protocol in
`backend/app/services/vector_store_service.py` (`IdentityReranker` is
the current default; a real reranker is passed to
`VectorStoreService` without changing call sites).

Experiment, in order, once the live run is unblocked:

1. Live run with current config; record hit@5, MRR, judge
   correctness, refusal accuracy, latency, cost as the baseline.
2. Live run again with hybrid (Qdrant sparse/BM25 + RRF fusion) and
   again with a reranker, each as its own `--variant` run.
3. Keep a variant only if it improves hit@5/MRR or judge correctness
   without degrading refusal accuracy or latency beyond the recorded
   cost -- and report any metric that got worse, not just winners.

## How to reproduce

```bash
cd backend
python eval/run_eval.py --mode offline
python eval/run_eval.py --mode offline --variant threshold-off --threshold 0.0
python eval/run_eval.py --mode offline --variant no-mmr --no-mmr
# Live (needs a valid key; see above):
OPENAI_API_KEY=sk-... python eval/run_eval.py --mode live --limit 20
```

Runs never overwrite earlier runs. Every record carries a `mode`
field (`offline-pipeline-smoke` or `live`).
