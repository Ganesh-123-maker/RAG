"""Phase D evaluation runner.

Usage (from ``backend/``):

  Offline pipeline smoke test (no API key, no cost, NOT a quality
  measurement -- fake embeddings + fake LLM, see ``fake_backend.py``):

      python eval/run_eval.py --mode offline

  Live evaluation (real OpenAI embeddings + real graph + LLM judge):

      OPENAI_API_KEY=... QDRANT_HOST=:memory: \\
          python eval/run_eval.py --mode live --limit 20

  Variants actually run are recorded in the output; a variant that
  was not run is never reported with numbers. Examples:

      python eval/run_eval.py --mode offline --variant threshold-off --threshold 0.0
      python eval/run_eval.py --mode offline --variant no-mmr --no-mmr

Output: ``docs/eval/<run-id>/summary.json`` and
``docs/eval/<run-id>/results.jsonl`` (one record per question).
A run never overwrites an earlier run: if the run-id directory
exists, a numeric suffix is appended.

Modes are never mixed in one results file: every record and the
summary carry a ``mode`` field, ``offline-pipeline-smoke`` or
``live``.

Live token/cost figures are ESTIMATES, not metered API usage: the
agent service does not return token usage, so input tokens are
counted with tiktoken over the retrieved context + question and
output tokens over the answer, then priced with the constants in
``PRICING`` (labelled with their date in the output). Offline cost
is 0 because no external call is made.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import statistics
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

# Allow running as ``python eval/run_eval.py`` from backend/ (script dir
# is eval/) as well as ``python -m eval.run_eval`` (backend/ on path).
_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from eval import fake_backend as _fb  # type: ignore[attr-defined]
    from eval import metrics as _metrics
except Exception:  # noqa: BLE001 -- script-dir execution fallback
    import fake_backend as _fb  # type: ignore[no-redef]
    import metrics as _metrics  # type: ignore[no-redef]

# Pricing constants are estimates, not a bill. Update the date when
# the constants change; the date is recorded in every live summary.
PRICING_DATE = "2026-10-24"
PRICING = {
    # USD per 1M tokens, gpt-4o chat + text-embedding-3-large.
    "gpt-4o-input": 2.50,
    "gpt-4o-output": 10.00,
    "embedding": 0.13,
}

PLACEHOLDER_MARKERS = ("REPLACE", "YOUR_KEY", "DUMMY", "EXAMPLE", "xxx")


def _is_placeholder(key: str) -> bool:
    key = (key or "").strip()
    if not key:
        return True
    upper = key.upper()
    return any(marker in upper for marker in PLACEHOLDER_MARKERS)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(len(ordered) * pct)))
    return ordered[idx]


def _token_count(text: str) -> int:
    try:
        import tiktoken

        return len(tiktoken.get_encoding("cl100k_base").encode(text))
    except Exception:  # noqa: BLE001 -- estimate fallback
        return max(1, len(text.split()) * 4 // 3)


def _unique_run_dir(out_root: Path, run_id: str) -> Path:
    candidate = out_root / run_id
    suffix = 1
    while candidate.exists():
        candidate = out_root / f"{run_id}-{suffix}"
        suffix += 1
    candidate.mkdir(parents=True)
    return candidate


async def run_evaluation(cfg: dict) -> dict:
    """Run one evaluation. ``cfg`` keys: mode, corpus_dir, golden_dir,
    db_path, upload_dir, limit, variant, threshold, no_mmr,
    qdrant_client (optional, shared in-memory client for tests),
    judge_client (optional, live judge client override for tests)."""
    mode = cfg["mode"]
    if mode not in ("offline", "live"):
        raise ValueError("mode must be 'offline' or 'live'")
    mode_label = "offline-pipeline-smoke" if mode == "offline" else "live"

    # --- Environment: must be set BEFORE importing app modules, because
    # Settings is cached at first import. Tests that already imported
    # app modules must pass a qdrant_client override instead.
    if mode == "offline":
        os.environ.setdefault("OPENAI_API_KEY", "eval-offline-dummy-not-a-key")
    else:
        key = os.environ.get("OPENAI_API_KEY", "")
        if _is_placeholder(key):
            raise SystemExit(
                "BLOCKED: no valid OPENAI_API_KEY in the environment. "
                "Live evaluation needs a real key; refusing to fabricate "
                "a live run. Run the offline smoke test instead:\n"
                "  python eval/run_eval.py --mode offline"
            )
    os.environ.setdefault("QDRANT_HOST", ":memory:")
    os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{cfg['db_path']}")
    os.environ.setdefault("UPLOAD_DIR", str(cfg["upload_dir"]))
    os.environ.setdefault("ENVIRONMENT", "test")

    from fastapi import UploadFile
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    # Import every model module so relationships resolve and all
    # tables are created (importing only User fails on 'Conversation').
    import app.models.conversation
    import app.models.document  # noqa: F401
    from app.core.database import Base
    from app.models.user import User
    from app.services import agent_service, document_service, vector_store_service
    from app.services.agent_service import AgentService
    from app.services.document_service import DocumentService
    from app.services.embedding_service import EmbeddingService
    from app.services.vector_store_service import VectorStoreService

    if mode == "offline":
        document_service.EmbeddingService = _fb.FakeEmbeddingService  # type: ignore[assignment]
        agent_service.EmbeddingService = _fb.FakeEmbeddingService  # type: ignore[assignment]
        agent_service.get_openai_client = lambda: _fb.FakeLLMClient()  # type: ignore[assignment]
        # The runner's own search call uses the locally imported name,
        # so rebind it too; otherwise offline mode would construct the
        # real OpenAI client (and fail on proxy/key) just for retrieval.
        EmbeddingService = _fb.FakeEmbeddingService  # type: ignore[assignment]
    if cfg.get("qdrant_client") is not None:
        shared = cfg["qdrant_client"]
        vector_store_service.get_qdrant_client = lambda: shared  # type: ignore[assignment]
    # Variant overrides (recorded in output; only applied when requested).
    if cfg.get("threshold") is not None:
        vector_store_service.settings.RETRIEVAL_SIMILARITY_THRESHOLD = cfg["threshold"]
    if cfg.get("no_mmr"):
        vector_store_service.mmr_select = (  # type: ignore[assignment]
            lambda candidates, top_k, lambda_mult=0.7: list(candidates[:top_k])
        )

    corpus_dir = Path(cfg["corpus_dir"])
    golden_dir = Path(cfg["golden_dir"])
    manifest = load_json(corpus_dir / "corpus.json")["documents"]
    golden = load_json(golden_dir / "golden.json")
    unanswerable = load_json(golden_dir / "unanswerable.json")
    injection = load_json(golden_dir / "injection.json")
    if cfg.get("limit"):
        golden = golden[: cfg["limit"]]
        unanswerable = unanswerable[: cfg["limit"]]
        injection = injection[: cfg["limit"]]

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{cfg['db_path']}",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    owner_id = uuid.uuid4()
    doc_id_by_file: dict[str, str] = {}
    records: list[dict] = []
    # Checkpoint every record as it completes, so a mid-run crash
    # (e.g. a free-tier daily cap) does not lose completed questions.
    # The final results.jsonl is still written at the end on success.
    _checkpoint_dir = _unique_run_dir(Path(cfg["out_dir"]), cfg["run_id"])
    _checkpoint_path = _checkpoint_dir / "results-partial.jsonl"

    def _checkpoint(record: dict) -> None:
        with _checkpoint_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    async with factory() as session:
        session.add(
            User(
                id=owner_id,
                email="eval@example.com",
                hashed_password="$2b$12$fakehashfakehashfakehash",
                full_name="Eval User",
                is_active=True,
            )
        )
        await session.commit()
        # --- Ingest the corpus through the REAL DocumentService.
        for filename in manifest:
            data = (corpus_dir / filename).read_bytes()
            svc = DocumentService(session)
            doc_id = await svc.ingest(
                UploadFile(filename=filename, file=io.BytesIO(data)), owner_id
            )
            await session.commit()
            doc_id_by_file[filename] = str(doc_id)

        agent = AgentService()
        embed_svc = EmbeddingService()
        vector_svc = VectorStoreService()
        await vector_svc.ensure_collection()

        # Source texts for the judge (live only): extracted text per doc.
        source_text_by_file: dict[str, str] = {}
        if mode == "live":
            from app.services.chunking_service import extract_text

            ext_by_file = {
                "vector-databases.txt": "txt",
                "qdrant.md": "md",
                "langgraph.pdf": "pdf",
                "chunking.txt": "txt",
                "embeddings.md": "md",
                "jwt-auth.docx": "docx",
                "docker.txt": "txt",
                "postgres.md": "md",
                "sse.txt": "txt",
                "mmr.txt": "txt",
            }
            for filename in manifest:
                source_text_by_file[filename] = extract_text(
                    (corpus_dir / filename).read_bytes(), ext_by_file[filename]
                )

        async def ask(question: str) -> dict:
            t0 = time.perf_counter()
            query_vector = await embed_svc.embed_text(question)
            retrieved = await vector_svc.search(
                query_vector=query_vector, owner_id=owner_id
            )
            # Free-tier pacing: a transient 429 (per-minute quota) must not
            # kill the whole run. Retry the whole question with backoff,
            # then re-raise if it still fails so the failure is visible.
            last_exc: Exception | None = None
            for attempt, delay in enumerate((15.0, 30.0, 60.0)):
                try:
                    answer_obj = await agent.run(question, owner_id, history=[])
                    break
                except Exception as exc:  # noqa: BLE001 -- retry only 429s
                    last_exc = exc
                    text = str(exc)
                    if "429" not in text and "temporarily unavailable" not in text:
                        raise
                    if attempt == 2:
                        raise
                    await asyncio.sleep(delay)
            else:  # pragma: no cover -- loop always breaks or raises
                raise last_exc  # type: ignore[misc]
            latency = time.perf_counter() - t0
            pace = float(cfg.get("pace_seconds") or 0)
            if pace:
                await asyncio.sleep(pace)
            return {
                "retrieved": retrieved,
                "answer": answer_obj.answer,
                "citations": answer_obj.citations,
                "latency": latency,
            }

        # --- Golden questions.
        retrieved_doc_lists: list[list[str]] = []
        golden_doc_ids: list[str] = []
        for item in golden:
            result = await ask(item["question"])
            retrieved_ids = [c.document_id for c in result["retrieved"]]
            retrieved_doc_lists.append(retrieved_ids)
            golden_doc_ids.append(doc_id_by_file[item["source_document"]])
            retrieved_by_id = {c.chunk_id: c.text for c in result["retrieved"]}
            cited_ids = [c.get("chunk_id", "") for c in result["citations"]]
            cited_texts = [
                retrieved_by_id[cid] for cid in cited_ids if cid in retrieved_by_id
            ]
            record: dict = {
                "kind": "golden",
                "id": item["id"],
                "question": item["question"],
                "source_document": item["source_document"],
                "mode": mode_label,
                "answer": result["answer"],
                "citations": result["citations"],
                "retrieved_document_ids": retrieved_ids,
                "retrieved_scores": [c.score for c in result["retrieved"]],
                "hit": doc_id_by_file[item["source_document"]] in retrieved_ids,
                "rank": (
                    retrieved_ids.index(doc_id_by_file[item["source_document"]]) + 1
                    if doc_id_by_file[item["source_document"]] in retrieved_ids
                    else None
                ),
                "citation_precision": (
                    None
                    if _metrics.is_refusal(result["answer"])
                    else _metrics.citation_precision(
                        cited_ids, [c.chunk_id for c in result["retrieved"]]
                    )
                ),
                "faithfulness": _metrics.faithfulness(result["answer"], cited_texts),
                "latency_seconds": round(result["latency"], 4),
            }
            if mode == "live":
                from app.services.embedding_service import get_openai_client

                judge_client = cfg.get("judge_client") or get_openai_client()
                judge = await _judge(
                    judge_client,
                    item,
                    source_text_by_file.get(item["source_document"], ""),
                    result["answer"],
                )
                record["judge"] = judge
                record["keyword_score"] = None
                in_tokens = _token_count(
                    item["question"] + " ".join(c.text for c in result["retrieved"])
                )
                out_tokens = _token_count(result["answer"])
                record["estimated_tokens"] = {
                    "input": in_tokens,
                    "output": out_tokens,
                }
                # Free-tier providers via OpenAI-compatible endpoints cost
                # $0; the gpt-4o pricing constants do not apply to them.
                # Only a real OpenAI base URL (or no override) is priced.
                _base = os.environ.get("LLM_BASE_URL", "")
                if _base and "api.openai.com" not in _base:
                    record["estimated_cost_usd"] = 0.0
                else:
                    record["estimated_cost_usd"] = round(
                        in_tokens * PRICING["gpt-4o-input"] / 1_000_000
                        + out_tokens * PRICING["gpt-4o-output"] / 1_000_000,
                        6,
                    )
            else:
                record["judge"] = None
                record["keyword_score"] = _metrics.keyword_score(
                    result["answer"], item["expected_keywords"]
                )
                record["estimated_tokens"] = None
                record["estimated_cost_usd"] = 0.0
            records.append(record)
            _checkpoint(record)

        # --- Unanswerable probes.
        for item in unanswerable:
            result = await ask(item["question"])
            _rec = {
                "kind": "unanswerable",
                "id": item["id"],
                "question": item["question"],
                "mode": mode_label,
                "answer": result["answer"],
                "citations": result["citations"],
                "refused": _metrics.is_refusal(result["answer"]),
                "latency_seconds": round(result["latency"], 4),
            }
            records.append(_rec)
            _checkpoint(_rec)

        # --- Prompt-injection probes.
        for item in injection:
            result = await ask(item["question"])
            _rec = {
                "kind": "injection",
                "id": item["id"],
                "question": item["question"],
                "mode": mode_label,
                "answer": result["answer"],
                "citations": result["citations"],
                "passed": _metrics.injection_pass(
                    result["answer"], result["citations"], item["forbidden"]
                ),
                "forbidden": item["forbidden"],
                "latency_seconds": round(result["latency"], 4),
            }
            records.append(_rec)
            _checkpoint(_rec)

    await engine.dispose()

    golden_records = [r for r in records if r["kind"] == "golden"]
    latencies = [r["latency_seconds"] for r in golden_records]
    precisions = [
        r["citation_precision"]
        for r in golden_records
        if r["citation_precision"] is not None
    ]
    judged = [
        r["judge"]
        for r in golden_records
        if r.get("judge") and r["judge"].get("correct") is not None
    ]
    summary: dict = {
        "mode": mode_label,
        "provider": (
            "groq-chat+openrouter-embeddings"
            if "groq" in os.environ.get("LLM_BASE_URL", "")
            and "openrouter" in os.environ.get("EMBEDDING_BASE_URL", "")
            else "groq-chat+gemini-embeddings"
            if "groq" in os.environ.get("LLM_BASE_URL", "")
            and "generativelanguage" in os.environ.get("EMBEDDING_BASE_URL", "")
            else "gemini-openai-compat"
            if "generativelanguage" in os.environ.get("LLM_BASE_URL", "")
            else "openai"
            if not os.environ.get("LLM_BASE_URL")
            else "openai-compat"
        ),
        "variant": cfg.get("variant", "current-config"),
        "run_id": cfg["run_id"],
        "generated_at": datetime.now(UTC).isoformat(),
        "corpus_documents": len(manifest),
        "corpus_files": manifest,
        "golden_questions": len(golden_records),
        "unanswerable_probes": len([r for r in records if r["kind"] == "unanswerable"]),
        "injection_probes": len([r for r in records if r["kind"] == "injection"]),
        "retrieval": {
            "hit_rate_at_1": round(
                sum(
                    1
                    for docs, g in zip(retrieved_doc_lists, golden_doc_ids)
                    if g in docs[:1]
                )
                / len(retrieved_doc_lists)
                if retrieved_doc_lists
                else 0.0,
                4,
            ),
            "hit_rate_at_3": round(
                sum(
                    1
                    for docs, g in zip(retrieved_doc_lists, golden_doc_ids)
                    if g in docs[:3]
                )
                / len(retrieved_doc_lists)
                if retrieved_doc_lists
                else 0.0,
                4,
            ),
            "hit_rate_at_5": round(
                sum(
                    1
                    for docs, g in zip(retrieved_doc_lists, golden_doc_ids)
                    if g in docs[:5]
                )
                / len(retrieved_doc_lists)
                if retrieved_doc_lists
                else 0.0,
                4,
            ),
            "mrr": round(
                _metrics.mean_reciprocal_rank(retrieved_doc_lists, golden_doc_ids), 4
            ),
        },
        "citation_precision_mean": (
            round(statistics.mean(precisions), 4) if precisions else None
        ),
        "faithfulness_mean": (
            round(statistics.mean([r["faithfulness"] for r in golden_records]), 4)
            if golden_records
            else None
        ),
        "refusal_accuracy": (
            round(
                sum(1 for r in records if r["kind"] == "unanswerable" and r["refused"])
                / max(1, len([r for r in records if r["kind"] == "unanswerable"])),
                4,
            )
        ),
        "injection_pass_rate": (
            round(
                sum(1 for r in records if r["kind"] == "injection" and r["passed"])
                / max(1, len([r for r in records if r["kind"] == "injection"])),
                4,
            )
        ),
        "latency_seconds": {
            "p50": round(_percentile(latencies, 0.50), 4),
            "p95": round(_percentile(latencies, 0.95), 4),
            "mean": round(statistics.mean(latencies), 4) if latencies else 0.0,
        },
        "config": {
            "threshold": cfg.get("threshold"),
            "no_mmr": bool(cfg.get("no_mmr")),
            "chat_model": os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o"),
            "embedding_model": os.environ.get(
                "OPENAI_EMBEDDING_MODEL", "text-embedding-3-large"
            ),
        },
        "pricing_date": PRICING_DATE if mode == "live" else None,
        "estimated_cost_usd_total": (
            round(sum(r.get("estimated_cost_usd") or 0.0 for r in golden_records), 6)
            if mode == "live"
            else 0.0
        ),
        "notes": (
            "OFFLINE MODE: fake hashed bag-of-words embeddings and a fake "
            "LLM that copies the best-overlapping context chunk. These "
            "numbers prove the pipeline runs end to end; they are NOT a "
            "quality measurement of the real system."
            if mode == "offline"
            else (
                "LIVE MODE (Gemini free tier via its OpenAI-compatible "
                "endpoint): real Gemini embeddings, real graph LLM calls, "
                "and LLM-as-judge at temperature 0 with a fixed rubric. "
                "Cost is $0 on the free tier, subject to its rate limits. "
                "These numbers measure the Gemini configuration, NOT "
                "OpenAI/gpt-4o, and must never be presented as OpenAI results."
                if "generativelanguage" in os.environ.get("LLM_BASE_URL", "")
                else "LIVE MODE (Groq chat + OpenRouter free embeddings via "
                "OpenAI-compatible endpoints): real provider embeddings, "
                "real graph LLM calls, and LLM-as-judge at temperature 0 "
                "with a fixed rubric. Cost is $0 on the free tiers, "
                "subject to their rate limits. These numbers measure this "
                "provider configuration, NOT OpenAI/gpt-4o, and must never "
                "be presented as OpenAI results."
                if "groq" in os.environ.get("LLM_BASE_URL", "")
                and "openrouter" in os.environ.get("EMBEDDING_BASE_URL", "")
                else "LIVE MODE (Groq chat + Gemini free embeddings via "
                "OpenAI-compatible endpoints): real provider embeddings, "
                "real graph LLM calls, and LLM-as-judge at temperature 0 "
                "with a fixed rubric. Cost is $0 on the free tiers, "
                "subject to their rate limits. These numbers measure this "
                "provider configuration, NOT OpenAI/gpt-4o, and must never "
                "be presented as OpenAI results."
                if "groq" in os.environ.get("LLM_BASE_URL", "")
                else "LIVE MODE: real OpenAI embeddings, real graph LLM calls, "
                "and LLM-as-judge at temperature 0 with a fixed rubric. "
                "Token/cost figures are tiktoken-based estimates, not metered "
                "API usage (the agent service does not return usage)."
            )
        ),
    }
    if mode == "live":
        summary["judge_correct_rate"] = (
            round(sum(1 for j in judged if j["correct"]) / len(judged), 4)
            if judged
            else None
        )
        summary["judge_evaluated"] = len(judged)
    else:
        summary["keyword_score_mean"] = (
            round(
                statistics.mean(
                    [
                        r["keyword_score"]
                        for r in golden_records
                        if r["keyword_score"] is not None
                    ]
                ),
                4,
            )
            if golden_records
            else None
        )
        summary["judge_correct_rate"] = None

    out_dir = _checkpoint_dir
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    with (out_dir / "results.jsonl").open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")
    summary["output_dir"] = str(out_dir)
    return summary


async def _judge(client, item: dict, source_text: str, answer: str) -> dict:
    try:
        from eval import judge as _judge_mod  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        import judge as _judge_mod  # type: ignore[no-redef]
    return await _judge_mod.judge_answer(
        client, item["question"], item["expected_keywords"], source_text, answer
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase D RAG evaluation runner.")
    parser.add_argument(
        "--mode",
        choices=["offline", "live"],
        required=True,
        help="offline = pipeline smoke test only; live = real provider calls "
        "(OpenAI by default, or the LLM_BASE_URL provider, e.g. Gemini)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="cap golden/unanswerable/injection questions (cost control)",
    )
    parser.add_argument("--variant", default="current-config")
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="override RETRIEVAL_SIMILARITY_THRESHOLD for this run",
    )
    parser.add_argument(
        "--no-mmr", action="store_true", help="disable MMR selection for this run"
    )
    parser.add_argument(
        "--pace-seconds",
        type=float,
        default=0.0,
        help="sleep after each question (free-tier rate-limit pacing)",
    )
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--corpus-dir", default=None)
    parser.add_argument("--golden-dir", default=None)
    parser.add_argument("--out-dir", default=None)
    args = parser.parse_args(argv)

    eval_dir = Path(__file__).resolve().parent
    run_id = args.run_id or (
        f"{args.mode}-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    )
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="rag-eval-"))
    cfg = {
        "mode": args.mode,
        "corpus_dir": args.corpus_dir or str(eval_dir / "corpus"),
        "golden_dir": args.golden_dir or str(eval_dir / "golden"),
        "db_path": str(tmp / "eval.sqlite"),
        "upload_dir": str(tmp / "uploads"),
        "limit": args.limit,
        "pace_seconds": args.pace_seconds,
        "variant": args.variant,
        "threshold": args.threshold,
        "no_mmr": args.no_mmr,
        "run_id": run_id,
        "out_dir": args.out_dir or str(_BACKEND.parent / "docs" / "eval"),
    }
    summary = asyncio.run(run_evaluation(cfg))
    print(json.dumps(summary, indent=2))
    print(f"\nWrote {summary['output_dir']}/summary.json and results.jsonl")
    print("Reproduce with:")
    print(
        "  cd backend && python eval/run_eval.py --mode "
        f"{args.mode}"
        + (f" --limit {args.limit}" if args.limit else "")
        + (f" --variant {args.variant}" if args.variant != "current-config" else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
