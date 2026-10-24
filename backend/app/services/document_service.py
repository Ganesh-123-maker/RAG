from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.repositories.document_repository import DocumentRepository
from app.services.chunking_service import TextChunk, chunk_text, extract_text
from app.services.embedding_service import EmbeddingError, EmbeddingService
from app.services.vector_store_service import VectorStoreService

settings = get_settings()
logger = logging.getLogger(__name__)

ALLOWED_TYPES = {"pdf", "docx", "txt", "md"}


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
    if isinstance(exc, ValueError):
        return (
            "Document could not be processed (unsupported or unreadable content).",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    return (
        "Document ingestion failed. Please try again.",
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


class DocumentService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._doc_repo = DocumentRepository(db)
        self._embed_svc = EmbeddingService()
        self._vector_svc = VectorStoreService()

    async def ingest(self, file: UploadFile, owner_id: uuid.UUID) -> uuid.UUID:
        file_ext = self._get_extension(file.filename or "")
        if file_ext not in ALLOWED_TYPES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unsupported file type '{file_ext}'. Allowed: {sorted(ALLOWED_TYPES)}",
            )

        file_bytes = await file.read()

        max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        if len(file_bytes) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File exceeds {settings.MAX_UPLOAD_SIZE_MB} MB limit",
            )

        safe_filename = f"{uuid.uuid4()}.{file_ext}"
        doc = await self._doc_repo.create(
            owner_id=owner_id,
            filename=safe_filename,
            original_name=file.filename or safe_filename,
            file_type=file_ext,
            file_size_bytes=len(file_bytes),
        )
        doc_id = doc.id
        file_path: Path | None = None
        vectors_upserted = False

        try:
            upload_path = Path(settings.UPLOAD_DIR).resolve() / str(owner_id)
            upload_path.mkdir(parents=True, exist_ok=True)
            file_path = upload_path / safe_filename
            file_path.write_bytes(file_bytes)
            logger.info("File saved: %s", file_path)

            raw_text = extract_text(file_bytes, file_ext)
            if not raw_text.strip():
                raise ValueError("Document appears to be empty or unreadable")

            chunks: list[TextChunk] = chunk_text(
                text=raw_text,
                document_id=doc_id,
                document_name=file.filename or safe_filename,
            )
            if not chunks:
                raise ValueError("Document produced no chunks")
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
            if file_path is not None:
                try:
                    file_path.unlink(missing_ok=True)
                    # Remove the per-owner directory if it is now empty, so
                    # a failed upload leaves no trace on disk.
                    file_path.parent.rmdir()
                except OSError:
                    pass
                except Exception as cleanup_exc:  # noqa: BLE001 -- best-effort cleanup must not raise
                    logger.warning(
                        "File cleanup failed for document %s: %s", doc_id, cleanup_exc
                    )
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
