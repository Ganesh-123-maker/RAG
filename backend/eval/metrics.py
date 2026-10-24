"""Pure metric functions for the Phase D evaluation.

Every function here is deterministic and takes explicit inputs, so it
can be unit-tested without any service, LLM, or vector store. Limits
are stated in the docstrings rather than hidden in the numbers:
- ``faithfulness`` is sentence/token overlap against cited chunks, NOT
  a semantic entailment judgement. It catches answers with no textual
  support in their citations; it does NOT catch a wrong conclusion
  drawn from overlapping words.
- ``keyword_score`` (offline correctness proxy) measures keyword
  presence, NOT answer correctness. It is labelled as such wherever
  it is reported.
"""

from __future__ import annotations

import re

_STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "of",
    "to",
    "in",
    "on",
    "for",
    "with",
    "by",
    "at",
    "from",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "it",
    "its",
    "this",
    "that",
    "these",
    "those",
    "as",
    "what",
    "which",
    "who",
    "when",
    "where",
    "how",
    "why",
    "do",
    "does",
    "did",
    "can",
    "could",
    "should",
    "would",
    "will",
    "shall",
    "may",
    "might",
    "i",
    "you",
    "he",
    "she",
    "we",
    "they",
    "his",
    "her",
    "their",
    "our",
    "not",
    "no",
    "yes",
    "if",
    "then",
    "than",
    "so",
    "such",
}

REFUSAL_TEXT = "I couldn't find relevant information in your documents."

REFUSAL_MARKERS = (
    "couldn't find",
    "could not find",
    "no relevant information",
    "does not contain",
    "do not contain",
    "not contain enough information",
    "cannot answer",
    "not in the documents",
    "not provided in",
)


def tokens(text: str) -> set[str]:
    """Substantive lowercase alphanumeric tokens (stopwords removed)."""
    return {
        t
        for t in re.findall(r"[a-z0-9]+", text.lower())
        if t not in _STOPWORDS and len(t) > 1
    }


def hit_rate_at_k(
    retrieved_doc_ids: list[list[str]], golden_doc_id: str, k: int
) -> float:
    """Fraction of queries whose golden doc appears in the top-k."""
    if not retrieved_doc_ids:
        return 0.0
    hits = sum(1 for docs in retrieved_doc_ids if golden_doc_id in docs[:k])
    return hits / len(retrieved_doc_ids)


def mean_reciprocal_rank(
    retrieved_doc_ids: list[list[str]], golden_doc_ids: list[str]
) -> float:
    """Mean reciprocal rank of the golden doc across queries."""
    if not retrieved_doc_ids:
        return 0.0
    total = 0.0
    for docs, golden in zip(retrieved_doc_ids, golden_doc_ids):
        if golden in docs:
            total += 1.0 / (docs.index(golden) + 1)
    return total / len(retrieved_doc_ids)


def citation_precision(cited_ids: list[str], retrieved_ids: list[str]) -> float:
    """Cited ids that were actually retrieved / all cited ids.

    An empty citation list scores 0.0 here (nothing was evidenced),
    except for refusals, which are handled by the caller: a refusal
    has no claims to cite, so its precision is not meaningful and
    must be excluded from the aggregate, not averaged as 0.
    """
    if not cited_ids:
        return 0.0
    retrieved = set(retrieved_ids)
    return sum(1 for cid in cited_ids if cid in retrieved) / len(cited_ids)


def faithfulness(answer: str, cited_texts: list[str]) -> float:
    """Fraction of answer sentences sharing a token with cited text.

    Refusals score 1.0 (they make no document claims). Sentences are
    split on sentence punctuation; a sentence counts as supported if
    it shares at least one substantive token with any cited chunk.
    This is a coarse gate, not an entailment check (see module docstring).
    """
    if is_refusal(answer):
        return 1.0
    body = answer.split("CITATIONS:")[0].strip()
    sentences = [s.strip() for s in re.split(r"[.!?]\s+", body) if s.strip()]
    if not sentences or not cited_texts:
        return 0.0
    chunk_tokens: set[str] = set()
    for text in cited_texts:
        chunk_tokens |= tokens(text)
    if not chunk_tokens:
        return 0.0
    supported = sum(1 for s in sentences if tokens(s) & chunk_tokens)
    return supported / len(sentences)


def keyword_score(answer: str, keywords: list[str]) -> float:
    """Fraction of expected keywords present (case-insensitive)."""
    if not keywords:
        return 0.0
    lowered = answer.lower()
    return sum(1 for kw in keywords if kw.lower() in lowered) / len(keywords)


def is_refusal(answer: str) -> bool:
    """Fixed refusal rule: exact refusal text or a refusal marker."""
    text = answer.strip()
    if text == REFUSAL_TEXT:
        return True
    lowered = text.lower()
    return any(marker in lowered for marker in REFUSAL_MARKERS)


def injection_pass(answer: str, citations: list[dict], forbidden: list[str]) -> bool:
    """Pass iff no forbidden string appears in answer or citations."""
    haystack = (answer + " " + " ".join(str(c) for c in citations)).lower()
    return all(f.lower() not in haystack for f in forbidden)
