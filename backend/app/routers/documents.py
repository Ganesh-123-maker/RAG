from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import CurrentUser
from app.repositories.document_repository import DocumentRepository
from app.schemas.document import DocumentListResponse, DocumentResponse
from app.services.document_service import DocumentService

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=DocumentResponse, status_code=201)
async def upload_document(
    file: UploadFile,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    svc = DocumentService(db)
    doc_id = await svc.ingest(file=file, owner_id=current_user.id)

    repo = DocumentRepository(db)
    doc = await repo.get_by_id_for_owner(doc_id, current_user.id)
    return DocumentResponse.model_validate(doc)


@router.get("", response_model=DocumentListResponse)
@router.get("/", response_model=DocumentListResponse, include_in_schema=False)
async def list_documents(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> DocumentListResponse:
    repo = DocumentRepository(db)
    docs = await repo.get_by_owner(current_user.id)
    return DocumentListResponse(
        documents=[DocumentResponse.model_validate(d) for d in docs],
        total=len(docs),
    )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    repo = DocumentRepository(db)
    doc = await repo.get_by_id_for_owner(document_id, current_user.id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return DocumentResponse.model_validate(doc)


@router.delete("/{document_id}", status_code=204, response_class=Response)
async def delete_document(
    document_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    svc = DocumentService(db)
    await svc.delete(doc_id=document_id, owner_id=current_user.id)
    return Response(status_code=204)
