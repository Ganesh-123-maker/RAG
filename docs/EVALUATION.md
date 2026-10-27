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
| `live` | Real provider embeddings, real graph, real provider LLM, LLM-as-judge at temperature 0 with a fixed rubric | Answer quality, retrieval quality, latency, cost -- the only mode whose scores may be quoted as system quality. The provider is recorded per run in `summary.json` (`provider`, `config.chat_model`, `config.embedding_model`); numbers from one provider must never be quoted as another provider's. First live runs (2026-10-24/26) used Gemini free tier, **not** OpenAI/GPT-4o, because the connected OpenAI account returned `credit_balance_exhausted`. |

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

### Live runs: Gemini free tier (OpenAI-compatible endpoint)

The OpenAI path stayed blocked (`credit_balance_exhausted` on the
connected account), so the first live runs used Gemini free tier via
its OpenAI-compatible endpoint: chat `gemini-3.5-flash-lite`,
embeddings `gemini-embedding-001` (3072 dims), cost $0. These numbers
measure the **Gemini configuration**, not OpenAI/GPT-4o, and must
never be quoted as OpenAI results. Free-tier interruptions are part
of the record, not smoothed away: the runs below survived an
OpenRouter daily cap, a Groq daily token cap, two runtime restarts,
and a Gemini daily quota exhaustion, via per-question checkpointing
(`results-partial.jsonl`) and `--resume`.

| Run | hit@1 | hit@3 | hit@5 | MRR | Citation precision | Faithfulness | Refusal acc. | Injection pass | Judge correct | Latency p50/p95 |
|---|---|---|---|---|---|---|---|---|---|---|
| `gemini-live-limit20` (20 golden, threshold 0.30) | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 0.9833 | 0.5625 (9/16) | 0.8333 (5/6) | 20/20 | 8.41s / 14.33s |
| `gemini-live-full` (55 golden, threshold 0.30) | 1.0 | 1.0 | 1.0 | 1.0 | 0.9623 | 0.9636 | 0.6875 (11/16) | 0.8333 (5/6) | 52/54 (mmr-02 judge 503'd; wrong: vec-05, sse-02) | 9.98s / 78.46s |
| `gemini-live-limit20-threshold050` (20 golden, threshold 0.50) | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 0.50 (8/16) | 1.0 (6/6) | 16/16 evaluated (4 judge calls 503'd: qdr-01/02/05/06) | 13.08s / 181.86s |

Raw outputs: `docs/eval/gemini-live-limit20/`,
`docs/eval/gemini-live-full/`,
`docs/eval/gemini-live-limit20-threshold050/` (42, 77, and 42
records respectively). The threshold-0.50 variant's records span two
days (Oct 24 + Oct 26) because the Gemini daily quota (500
generate-content requests/day for this model) exhausted mid-run; the
remaining 8 questions were resumed after the reset with `--resume`.

What these runs teach, and what they do not:

- Retrieval is perfect on this corpus at either threshold, but the
  corpus is only 10 documents and the golden questions were written
  against them, so 1.0 hit rates prove the pipeline end to end, not
  general retrieval quality on a large corpus.
- Refusal is the weak metric (0.50-0.6875 across runs), and it
  wobbles run to run on identical probes (the same probes fail in
  different combinations), which is itself a finding: refusal is not
  deterministic at the current settings.
- **Tuning decision (evidence, not a guess): raising the similarity
  threshold 0.30 -> 0.50 did NOT improve refusal** (8/16 vs 9/16 on
  the same 20-golden subset; the one-question difference is within
  run-to-run LLM variation), while golden retrieval was unchanged
  (20/20 hit@1 both ways, as predicted: golden top-scores in the
  full run ranged from 0.64 upward, median 0.735, none below 0.50). The
  production default therefore **stays at 0.30**; the variant is
  recorded, not shipped. A jump to 0.70 was not run: it would have
  cost 8/55 golden top-1 hits in the full run's score distribution.
- Why threshold tuning cannot fix refusal here: the graph refuses
  on empty chunks (see `agent_service.py`, reasoning node), and
  out-of-corpus probes still retrieve topically related chunks above
  0.50, so the LLM answers from them instead of refusing.
- **Grade-based refusal, implemented 2026-10-26** (no longer future
  work): the grade now requires score AND lexical coverage -- the
  fraction of the original question's content tokens appearing in
  the retrieved chunk texts (union; deterministic tokenizer with
  stopwords removed and plural/gerund folding, both sides). After
  the single rewrite, a still-poor grade routes to a refuse node
  that answers the shared refusal with no LLM call at all, instead
  of reasoning. Coverage is measured against the original question,
  never the rewritten query. Measured basis, real Gemini retrieval
  at chunk level over all 55 golden + 16 probes: golden coverage
  min 0.75 / median 1.00; the 5 probes the live full run answered
  all 0.00; threshold `RETRIEVAL_COVERAGE_THRESHOLD = 0.50` sits in
  that gap. Two probes with in-corpus vocabulary (0.80, 1.00) still
  pass coverage and are refused downstream by reasoning/verify, as
  before -- coverage is a floor, not a proof of answerability.
  Pinned by `tests/test_grade_refusal.py` (helper, grade branches,
  graph-level refuse-without-reasoning and good-grade-still-reasons)
  and a rewritten `test_phase_c` still-poor case.
- **Live re-run with the new graph, 2026-10-27**
  (`docs/eval/gemini-live-full-post-refusal/`, Gemini free tier,
  same 55+16+6 set, ~44 min): **refusal 10/16 (0.625), NOT 16/16**.
  Hit@1/3/5 still 1.0, citation 0.9423 (was 0.9623), faithfulness
  0.9348 (was 0.9636), judge 53/55 (was 52/54 evaluated),
  injection 5/6 (unchanged). The prediction failed for a specific,
  diagnosed reason, not a grade malfunction:
  - The 5 still-answered probes never reach the grade at all: the
    planner routes them to the **direct branch**
    (`needs_retrieval=False`), so they are answered from
    pretraining with zero citations. The coverage measurement
    assumed the retrieval path; the live leak is upstream, in the
    planner. Verified by replaying planner -> retriever -> grade
    for all 5 with real Gemini: all 5 direct, grade never runs.
  - The one flip, un-15 (refused in baseline, answered now),
    passes the grade by design (coverage 0.80, top 0.696) and was
    answered by reasoning with 1 citation -- LLM variation in
    reasoning/verify, not a grade regression (the old score-only
    grade would also have passed it).
  - The 2 golden refusals (vec-06, doc-05) are likewise NOT grade
    refusals: replayed grade is good for both (coverage 1.00 /
    0.86, tops 0.723 / 0.691, matching the run's retrieved scores),
    so they were refused downstream by reasoning/verify -- LLM
    variation, same class as the baseline's own run-to-run wobble
    (9/16 -> 11/16 across runs). 10/16 sits inside that noise band;
    the honest conclusion is **no measured refusal improvement
    from the grade change on this corpus**, because the remaining
    failures bypass it.
  - Consequence: the next refusal fix must narrow the planner's
    direct branch (direct only for greetings/small talk, never for
    factual questions, even general-knowledge ones), so factual
    probes flow through retrieval -> grade -> refusal. That change
    is NOT in this run; it needs its own implementation, tests,
    and another live re-run before any new refusal figure is
    claimed. Until then the shipped refusal figure is 10/16 from
    this run, with the mechanism above explaining it.
- Injection: inj-04 failed in both 0.30 runs and passed in the 0.50
  variant; with n=6 that single flip is not evidence the threshold
  caused it.
- Latency p95s in the full and variant runs (78s, 182s) are inflated
  by free-tier 503/timeout retries (the runner retries transient
  429/503s with 60/90/120s backoff, and that wait is inside the
  recorded question latency), not by normal answering speed (p50
  10-13s).
- The `--no-mmr` and grade-threshold variants were **not run**: on a
  10-document corpus MMR has little room to matter, and free-tier
  quota is better spent on the refusal question above than on
  variants with no predicted signal. They are not claimed as tested.

To run a live evaluation (maintainer, with a provider key that has
quota for ~77 questions x planner/reasoning/judge calls -- use
`--limit` first):

```bash
cd backend
OPENAI_API_KEY=sk-... python eval/run_eval.py --mode live --limit 20
```

Outputs go to a new `docs/eval/<run-id>/` directory and must be
committed with their run id. Only then may README numbers be updated
from them, with the date, model names, corpus size, and the exact
command recorded alongside.

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
