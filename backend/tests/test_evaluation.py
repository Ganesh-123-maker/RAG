from __future__ import annotations

import pytest
from scripts.evaluate_rag import run_evaluation


@pytest.mark.asyncio
async def test_full_corpus_evaluation_benchmark() -> None:
    eval_result = await run_evaluation()
    assert eval_result.total_documents >= 50
    assert eval_result.source_grounded_pct >= 97.0
    assert eval_result.citation_coverage_pct == 100.0
    assert eval_result.hallucination_rate_pct <= 1.0
    assert eval_result.avg_latency_seconds <= 10.0
    assert eval_result.auth_success_rate_pct >= 99.0
    assert eval_result.passed_all_targets is True
