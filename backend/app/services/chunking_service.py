from __future__ import annotations

import io
import uuid
from dataclasses import dataclass

import pdfplumber
import tiktoken
from docx import Document as DocxDocument

from app.core.config import get_settings

settings = get_settings()

_TOKENIZER = None


def get_tokenizer():
    global _TOKENIZER
    if _TOKENIZER is None:
        try:
            _TOKENIZER = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _TOKENIZER = tiktoken.encoding_for_model("gpt-4o")
    return _TOKENIZER


@dataclass
class TextChunk:
    text: str
    chunk_index: int
    document_id: uuid.UUID
    document_name: str


def extract_text(file_bytes: bytes, file_type: str) -> str:
    ft = file_type.lower()
    if ft == "pdf":
        return _extract_pdf(file_bytes)
    elif ft == "docx":
        return _extract_docx(file_bytes)
    elif ft in ("txt", "md"):
        return file_bytes.decode("utf-8", errors="replace")
    else:
        raise ValueError(f"Unsupported file type: '{file_type}'")


def _extract_pdf(data: bytes) -> str:
    try:
        text_parts: list[str] = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
        return "\n\n".join(text_parts)
    except Exception as exc:
        raise ValueError(f"Failed to extract text from PDF: {exc}") from exc


def _extract_docx(data: bytes) -> str:
    try:
        doc = DocxDocument(io.BytesIO(data))
        return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as exc:
        raise ValueError(f"Failed to extract text from DOCX: {exc}") from exc


def chunk_text(
    text: str,
    document_id: uuid.UUID,
    document_name: str,
    chunk_size: int = settings.CHUNK_SIZE_TOKENS,
    overlap: int = settings.CHUNK_OVERLAP_TOKENS,
) -> list[TextChunk]:
    if not text or not text.strip():
        return []

    tokenizer = get_tokenizer()
    tokens = tokenizer.encode(text)
    if not tokens:
        return []

    chunks: list[TextChunk] = []
    start = 0
    step = max(1, chunk_size - overlap)

    while start < len(tokens):
        end = min(start + chunk_size, len(tokens))
        chunk_tokens = tokens[start:end]
        chunk_str = tokenizer.decode(chunk_tokens)

        if chunk_str.strip():
            chunks.append(
                TextChunk(
                    text=chunk_str,
                    chunk_index=len(chunks),
                    document_id=document_id,
                    document_name=document_name,
                )
            )

        if end >= len(tokens):
            break
        start += step

    return chunks
