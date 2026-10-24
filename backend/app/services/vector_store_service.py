import hashlib
import logging
import math
import uuid
from dataclasses import dataclass
from typing import Protocol

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.core.circuit_breaker import CircuitBreaker
from app.core.config import get_settings
from app.services.chunking_service import TextChunk

settings = get_settings()
logger = logging.getLogger(__name__)

_qdrant_client: AsyncQdrantClient | None = None


def get_qdrant_client() -> AsyncQdrantClient:
    global _qdrant_client
    if _qdrant_client is None:
        if settings.QDRANT_HOST in (
            ":memory:",
            "memory",
            ":memory",
        ) or settings.QDRANT_HOST.startswith("./"):
            _qdrant_client = AsyncQdrantClient(location=":memory:")
        elif settings.QDRANT_API_KEY:
            # Qdrant Cloud: use URL-based connection with API key
            url = f"https://{settings.QDRANT_HOST}:{settings.QDRANT_PORT}"
            _qdrant_client = AsyncQdrantClient(url=url, api_key=settings.QDRANT_API_KEY)
        else:
            # Local Qdrant without auth
            _qdrant_client = AsyncQdrantClient(
                host=settings.QDRANT_HOST,
                port=settings.QDRANT_PORT,
            )
    return _qdrant_client


def stable_chunk_id(owner_id: uuid.UUID, chunk: TextChunk) -> str:
    """Deterministic point id so identical chunks upsert, not duplicate.

    Derived from owner + document + chunk content hash. Re-uploading the
    same chunk therefore overwrites the same point instead of creating a
    second point with a random UUID.
    """
    content_hash = (
        chunk.content_hash or hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
    )
    return str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"{owner_id}:{chunk.document_id}:{content_hash}")
    )


@dataclass
class RetrievedChunk:
    text: str
    document_id: str
    document_name: str
    chunk_index: int
    score: float
    # Phase B fields; defaults keep older constructions working. When a
    # chunk_id is not supplied it falls back to document:chunk_index, a
    # stable identifier within one document version.
    chunk_id: str = ""
    page: int | None = None
    section: str | None = None
    # Candidate vector, present only when Qdrant returned it (needed for
    # MMR); None means MMR falls back to score order.
    vector: list[float] | None = None

    def __post_init__(self) -> None:
        if not self.chunk_id:
            self.chunk_id = f"{self.document_id}:{self.chunk_index}"


class Reranker(Protocol):
    """Reranker interface (Phase B: identity default, Phase D plugs in).

    A real reranker (e.g. cross-encoder) implements this protocol and is
    passed to :class:`VectorStoreService`; call sites do not change.
    """

    def rerank(
        self, query: str, candidates: list[RetrievedChunk]
    ) -> list[RetrievedChunk]: ...


class IdentityReranker:
    """No-op reranker: keeps the MMR/score order unchanged."""

    def rerank(
        self, query: str, candidates: list[RetrievedChunk]
    ) -> list[RetrievedChunk]:
        return candidates


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def mmr_select(
    candidates: list[RetrievedChunk],
    top_k: int,
    lambda_mult: float = 0.7,
) -> list[RetrievedChunk]:
    """Maximal Marginal Relevance selection.

    Iteratively picks the candidate maximising
    ``lambda * score - (1 - lambda) * max_similarity_to_selected``.
    If candidate vectors are missing, MMR cannot measure diversity and
    the function falls back to score order (documented, not silent: the
    caller logs this case in ``search``).
    """
    if not candidates or top_k <= 0:
        return []
    if len(candidates) <= top_k:
        return list(candidates)
    if any(c.vector is None for c in candidates):
        return list(candidates[:top_k])
    selected: list[RetrievedChunk] = []
    remaining = list(candidates)
    while remaining and len(selected) < top_k:
        best: RetrievedChunk | None = None
        best_value = -math.inf
        for cand in remaining:
            max_sim = 0.0
            for chosen in selected:
                assert cand.vector is not None and chosen.vector is not None
                max_sim = max(max_sim, _cosine(cand.vector, chosen.vector))
            value = lambda_mult * cand.score - (1 - lambda_mult) * max_sim
            if value > best_value:
                best_value = value
                best = cand
        assert best is not None
        selected.append(best)
        remaining.remove(best)
    return selected


def _collection_vector_size(info: object) -> int | None:
    """Best-effort extraction of a Qdrant collection's vector size."""
    try:
        config = getattr(info, "config", None)
        params = getattr(config, "params", None) if config is not None else None
        vectors = getattr(params, "vectors", None) if params is not None else None
        if vectors is None and isinstance(params, dict):
            vectors = params.get("vectors")
        if isinstance(vectors, dict):
            # Named vectors: take the first entry's size, if present.
            first = next(iter(vectors.values()), None)
            size = getattr(first, "size", None) if first is not None else None
            if isinstance(size, int):
                return size
            return None
        size = getattr(vectors, "size", None) if vectors is not None else None
        return size if isinstance(size, int) else None
    except Exception:  # noqa: BLE001 -- size extraction is best-effort
        return None


class CollectionDimensionMismatchError(ValueError):
    """Existing Qdrant collection dims differ from configured dims."""


class VectorStoreService:
    def __init__(
        self,
        reranker: Reranker | None = None,
        breaker: CircuitBreaker | None = None,
    ) -> None:
        self._client = get_qdrant_client()
        self._collection = settings.QDRANT_COLLECTION
        self._dim = settings.OPENAI_EMBEDDING_DIMENSIONS
        self._reranker = reranker or IdentityReranker()
        # Phase E circuit breaker around Qdrant search: after N
        # consecutive failures, search fails fast (CircuitOpenError)
        # instead of waiting on a dead dependency. Callers (the agent
        # retriever) map it to AgentError -> 502, as with any
        # retrieval failure; the breaker itself never leaks details.
        self._breaker = breaker or CircuitBreaker(
            failure_threshold=settings.CIRCUIT_BREAKER_FAILURE_THRESHOLD,
            cooldown_seconds=settings.CIRCUIT_BREAKER_COOLDOWN_SECONDS,
        )

    async def ensure_collection(self) -> None:
        try:
            existing = await self._client.get_collections()
            names = [c.name for c in existing.collections]
            if self._collection not in names:
                await self._client.create_collection(
                    collection_name=self._collection,
                    vectors_config=VectorParams(
                        size=self._dim,
                        distance=Distance.COSINE,
                    ),
                )
                return
            # Collection exists: refuse to silently use a mismatched one.
            # Recreating or deleting it would destroy indexed data, so a
            # mismatch is a loud error naming both dimensions instead.
            try:
                info = await self._client.get_collection(self._collection)
            except Exception as exc:  # noqa: BLE001 -- inspection failure defers, not fatal
                logger.warning(
                    "Could not inspect existing collection %s: %s",
                    self._collection,
                    exc,
                )
                return
            size = _collection_vector_size(info)
            if size is not None and size != self._dim:
                raise CollectionDimensionMismatchError(
                    f"Qdrant collection '{self._collection}' has vector "
                    f"dimension {size} but configured "
                    f"OPENAI_EMBEDDING_DIMENSIONS is {self._dim}. Refusing "
                    "to index or search against a mismatched collection; "
                    "either set the configured dimensions to match or "
                    "recreate the collection (which deletes its data)."
                )
        except CollectionDimensionMismatchError:
            raise
        except Exception as e:  # noqa: BLE001 -- transient Qdrant errors defer (Phase A behaviour)
            logger.warning("Vector DB collection check deferred: %s", e)

    async def upsert_chunks(
        self,
        chunks: list[TextChunk],
        embeddings: list[list[float]],
        owner_id: uuid.UUID,
    ) -> None:
        # Chunk-level dedupe: identical chunk ids (same owner/document/
        # content hash) collapse to one point instead of two upserts.
        seen: set[str] = set()
        points: list[PointStruct] = []
        for chunk, embedding in zip(chunks, embeddings):
            point_id = stable_chunk_id(owner_id, chunk)
            if point_id in seen:
                continue
            seen.add(point_id)
            content_hash = (
                chunk.content_hash
                or hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
            )
            points.append(
                PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload={
                        "text": chunk.text,
                        "document_id": str(chunk.document_id),
                        "document_name": chunk.document_name,
                        "chunk_index": chunk.chunk_index,
                        "chunk_id": point_id,
                        "page": chunk.page,
                        "section": chunk.section,
                        "char_start": chunk.char_start,
                        "char_end": chunk.char_end,
                        "content_hash": content_hash,
                        "owner_id": str(owner_id),
                    },
                )
            )
        if points:
            await self._client.upsert(collection_name=self._collection, points=points)

    async def search(
        self,
        query_vector: list[float],
        owner_id: uuid.UUID,
        top_k: int = settings.RETRIEVAL_TOP_K,
        document_id: uuid.UUID | None = None,
        threshold: float | None = None,
        fetch_k: int | None = None,
        query_text: str = "",
    ) -> list[RetrievedChunk]:
        """Fetch a candidate pool, filter by threshold, MMR to top_k.

        ``threshold`` defaults to the configured similarity threshold;
        pass ``threshold=None`` explicitly is not supported -- callers
        that need unfiltered results for tests pass ``threshold=0.0``
        (or a negative value) instead. ``fetch_k`` defaults to the
        configured pool size and is raised to at least ``top_k``.
        """
        if threshold is None:
            threshold = settings.RETRIEVAL_SIMILARITY_THRESHOLD
        pool = max(
            top_k, fetch_k if fetch_k is not None else settings.RETRIEVAL_FETCH_K
        )
        must_conditions = [
            FieldCondition(key="owner_id", match=MatchValue(value=str(owner_id)))
        ]
        if document_id is not None:
            must_conditions.append(
                FieldCondition(
                    key="document_id", match=MatchValue(value=str(document_id))
                )
            )

        self._breaker.before_call()
        try:
            results = await self._client.search(
                collection_name=self._collection,
                query_vector=query_vector,
                query_filter=Filter(must=must_conditions),
                limit=pool,
                with_payload=True,
                with_vectors=True,
                score_threshold=threshold if threshold > 0 else None,
            )
        except Exception:
            self._breaker.on_failure()
            raise
        self._breaker.on_success()

        retrieved: list[RetrievedChunk] = []
        for r in results:
            payload = r.payload or {}
            score = r.score
            if score < threshold:
                continue
            vector = getattr(r, "vector", None)
            retrieved.append(
                RetrievedChunk(
                    text=payload.get("text", ""),
                    document_id=payload.get("document_id", ""),
                    document_name=payload.get("document_name", "Unknown"),
                    chunk_index=payload.get("chunk_index", 0),
                    score=score,
                    chunk_id=payload.get("chunk_id") or "",
                    page=payload.get("page"),
                    section=payload.get("section"),
                    vector=vector if isinstance(vector, list) else None,
                )
            )
        # Qdrant returns score order; MMR reorders for diversity.
        if any(c.vector is None for c in retrieved):
            logger.debug(
                "MMR skipped (candidate vectors unavailable); using score order"
            )
            selected = retrieved[:top_k]
        else:
            selected = mmr_select(retrieved, top_k, lambda_mult=settings.MMR_LAMBDA)
        return self._reranker.rerank(query_text, selected)

    async def delete_by_document(
        self, document_id: uuid.UUID, owner_id: uuid.UUID
    ) -> None:
        await self._client.delete(
            collection_name=self._collection,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[
                        FieldCondition(
                            key="document_id", match=MatchValue(value=str(document_id))
                        ),
                        FieldCondition(
                            key="owner_id", match=MatchValue(value=str(owner_id))
                        ),
                    ]
                )
            ),
        )
