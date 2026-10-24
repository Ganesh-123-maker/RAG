from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.repositories.document_repository import DocumentRepository
from app.services.chunking_service import (
    ScannedDocumentError,
    TextChunk,
    chunk_text,
    extract_segments,
)
from app.services.embedding_service import EmbeddingError, EmbeddingService
from app.services.vector_store_service import VectorStoreService

settings = get_settings()
logger = logging.getLogger(__name__)

ALLOWED_TYPES = {"pdf", "docx", "txt", "md"}

# Bounded read size for streaming uploads: the service never calls
# ``file.read()`` without a size, so an oversize upload is rejected after
# at most one extra bounded chunk past the limit, not after loading the
# whole file into memory.
_STREAM_CHUNK_BYTES = 1024 * 1024
_SNIFF_BYTES = 8192


def _safe_ingestion_message(exc: Exception) -> tuple[str, int]:
    """Map an ingestion failure to a client-safe message and status.

    Raw exception text (library internals, paths, provider errors) is
    never returned to the client; the full error is logged server-side.
    """
    if isinstance(exc, EmbeddingError):
        return (
            "Embedding service is temporarily unavailable. The document was not indexed; please try again.",
            status.HTTP_502_BAD_GATEWAY,
        )
    if isinstance(exc, ScannedDocumentError):
        # Our own message: safe to surface verbatim, and it tells the
        # user what to do instead of a generic failure.
        return (str(exc), status.HTTP_422_UNPROCESSABLE_ENTITY)
    if isinstance(exc, ValueError):
        return (
            "Document could not be processed (unsupported or unreadable content).",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    return (
        "Document ingestion failed. Please try again.",
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def sniff_mismatch(first_bytes: bytes, file_ext: str) -> bool:
    """Stdlib magic-byte check (no new dependency for four types).

    PDF files start with ``%PDF-``; DOCX files are ZIP archives
    (``PK\\x03\\x04``). Plain text / Markdown must not carry either
    magic, and must not contain NUL bytes. This catches renamed files
    that extension-only validation would accept; deeper format errors
    are still caught by the parsers themselves.
    """
    if file_ext == "pdf":
        return not first_bytes.startswith(b"%PDF-")
    if file_ext == "docx":
        return not first_bytes.startswith(b"PK\x03\x04")
    if file_ext in ("txt", "md"):
        return (
            first_bytes.startswith((b"%PDF-", b"PK\x03\x04")) or b"\x00" in first_bytes
        )
    return True


def _cleanup_file(file_path: Path | None) -> None:
    """Delete a file and its owner directory if now empty (best-effort)."""
    if file_path is None:
        return
    try:
        file_path.unlink(missing_ok=True)
        file_path.parent.rmdir()
    except OSError:
        pass
    except Exception as cleanup_exc:  # noqa: BLE001 -- best-effort cleanup must not raise
        logger.warning("File cleanup failed for %s: %s", file_path, cleanup_exc)


class DocumentService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._doc_repo = DocumentRepository(db)
        self._embed_svc = EmbeddingService()
        self._vector_svc = VectorStoreService()

    async def _stream_to_disk(
        self, file: UploadFile, file_path: Path
    ) -> tuple[int, str, bytes]:
        """Stream an upload to disk, hashing as we go.

        Returns ``(size_bytes, content_hash, first_bytes)``. Raises 413
        as soon as the size limit is exceeded, without ever holding the
        whole file in memory: reads are bounded to
        ``_STREAM_CHUNK_BYTES`` and each chunk is written and discarded.
        """
        max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        hasher = hashlib.sha256()
        total = 0
        first_bytes = b""
        try:
            with file_path.open("wb") as out:
                while True:
                    chunk = await file.read(_STREAM_CHUNK_BYTES)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise HTTPException(
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail=f"File exceeds {settings.MAX_UPLOAD_SIZE_MB} MB limit",
                        )
                    hasher.update(chunk)
                    if len(first_bytes) < _SNIFF_BYTES:
                        first_bytes += chunk[: _SNIFF_BYTES - len(first_bytes)]
                    out.write(chunk)
        except HTTPException:
            _cleanup_file(file_path)
            raise
        except Exception:
            _cleanup_file(file_path)
            raise
        return total, hasher.hexdigest(), first_bytes

    async def ingest(self, file: UploadFile, owner_id: uuid.UUID) -> uuid.UUID:
        file_ext = self._get_extension(file.filename or "")
        if file_ext not in ALLOWED_TYPES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unsupported file type '{file_ext}'. Allowed: {sorted(ALLOWED_TYPES)}",
            )

        # Stream to disk first (bounded reads, content hash, size limit).
        safe_filename = f"{uuid.uuid4()}.{file_ext}"
        upload_path = Path(settings.UPLOAD_DIR).resolve() / str(owner_id)
        upload_path.mkdir(parents=True, exist_ok=True)
        file_path = upload_path / safe_filename
        file_size, content_hash, first_bytes = await self._stream_to_disk(
            file, file_path
        )

        # Real content validation, not just the extension.
        if sniff_mismatch(first_bytes, file_ext):
            _cleanup_file(file_path)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="File content does not match its declared type.",
            )

        # Per-owner dedupe (Phase B): a ready document with the same
        # bytes for the same owner is returned, not re-indexed. A
        # different owner may upload the same bytes (their vectors are
        # isolated by owner_id). A non-ready (processing/error) row does
        # not block a retry -- it is not a usable document yet.
        existing = await self._doc_repo.get_by_content_hash_for_owner(
            owner_id, content_hash
        )
        if existing is not None and existing.status == "ready":
            logger.info(
                "Dedupe hit for owner=%s: returning existing document %s",
                owner_id,
                existing.id,
            )
            _cleanup_file(file_path)
            return existing.id

        doc = await self._doc_repo.create(
            owner_id=owner_id,
            filename=safe_filename,
            original_name=file.filename or safe_filename,
            file_type=file_ext,
            file_size_bytes=file_size,
            content_hash=content_hash,
        )
        doc_id = doc.id
        vectors_upserted = False

        try:
            # CPU-bound parsing/tokenizing runs off the event loop.
            file_bytes = await asyncio.to_thread(file_path.read_bytes)
            segments = await asyncio.to_thread(extract_segments, file_bytes, file_ext)
            raw_text = "\n\n".join(s.text for s in segments)
            if not raw_text.strip():
                raise ValueError("Document appears to be empty or unreadable")

            chunks: list[TextChunk] = await asyncio.to_thread(
                chunk_text,
                raw_text,
                doc_id,
                file.filename or safe_filename,
                settings.CHUNK_SIZE_TOKENS,
                settings.CHUNK_OVERLAP_TOKENS,
                segments,
            )
            if not chunks:
                raise ValueError("Document produced no chunks")
            # Chunk-level dedupe: identical chunk hashes within one
            # document collapse to the first occurrence, renumbered.
            seen_hashes: set[str] = set()
            deduped: list[TextChunk] = []
            for chunk in chunks:
                if chunk.content_hash in seen_hashes:
                    continue
                seen_hashes.add(chunk.content_hash)
                chunk.chunk_index = len(deduped)
                deduped.append(chunk)
            chunks = deduped
            logger.info("Document %s chunked into %d chunks", doc_id, len(chunks))

            texts = [c.text for c in chunks]
            embeddings = await self._embed_svc.embed_batch(texts)

            await self._vector_svc.ensure_collection()
            await self._vector_svc.upsert_chunks(chunks, embeddings, owner_id)
            vectors_upserted = True
            logger.info("Upserted %d vectors for document %s", len(chunks), doc_id)

            await self._doc_repo.mark_ready(
                doc_id, chunk_count=len(chunks), owner_id=owner_id
            )

        except Exception as exc:
            # Full error goes to the server log only; the client gets a
            # safe message, and partial side effects are compensated.
            logger.error("Ingestion failed for document %s", doc_id, exc_info=exc)
            if vectors_upserted:
                try:
                    await self._vector_svc.delete_by_document(doc_id, owner_id)
                except Exception as cleanup_exc:  # noqa: BLE001 -- best-effort cleanup must not raise
                    logger.warning(
                        "Vector cleanup failed for document %s: %s", doc_id, cleanup_exc
                    )
            _cleanup_file(file_path)
            safe_message, status_code = _safe_ingestion_message(exc)
            await self._doc_repo.mark_error(doc_id, safe_message, owner_id=owner_id)
            await self._db.commit()
            raise HTTPException(status_code=status_code, detail=safe_message) from exc

        return doc_id

    async def delete(self, doc_id: uuid.UUID, owner_id: uuid.UUID) -> None:
        doc = await self._doc_repo.get_by_id_for_owner(doc_id, owner_id)
        if doc is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
            )

        await self._vector_svc.delete_by_document(doc_id, owner_id)

        file_path = Path(settings.UPLOAD_DIR) / str(owner_id) / doc.filename
        if file_path.exists():
            file_path.unlink()

        await self._doc_repo.delete_for_owner(doc_id, owner_id)

    @staticmethod
    def _get_extension(filename: str) -> str:
        return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
