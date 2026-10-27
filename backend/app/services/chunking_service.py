from __future__ import annotations

"""Text extraction and sentence/paragraph-aware chunking.

Extraction preserves the metadata retrieval needs later: PDF page numbers,
Markdown/DOCX headings as ``section``, and DOCX tables as text (they were
previously dropped silently). A PDF whose pages contain images but no
extractable text is reported as scanned, not as an empty document.

Chunking is sentence/paragraph aware: chunks are built by packing whole
sentences (never cutting a sentence in the middle for ordinary text) up to
``chunk_size`` tokens, with the previous chunk's trailing sentences carried
over as overlap. Only a single sentence longer than ``chunk_size`` -- or
text with no sentence boundaries at all -- falls back to a plain token
window. Every chunk carries ``char_start``/``char_end`` offsets into the
joined extracted text, its page/section (when known), and a SHA-256
``content_hash`` used for chunk-level dedupe downstream.
"""

import hashlib
import io
import re
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
        except Exception:  # noqa: BLE001 -- tokenizer fallback must catch any failure
            _TOKENIZER = tiktoken.encoding_for_model("gpt-4o")
    return _TOKENIZER


class ScannedDocumentError(ValueError):
    """A PDF that looks scanned: pages with images but no extractable text.

    A subclass of ``ValueError`` so existing unreadable-content handling
    still applies, but distinguishable so callers can give the user a
    specific, actionable message instead of a generic failure.
    """


@dataclass
class ExtractedSegment:
    """One block of extracted text with its source metadata."""

    text: str
    page: int | None = None
    section: str | None = None


@dataclass
class TextChunk:
    text: str
    chunk_index: int
    document_id: uuid.UUID
    document_name: str
    # Metadata added in Phase B; defaults keep older positional/kwarg
    # constructions working.
    page: int | None = None
    section: str | None = None
    char_start: int = 0
    char_end: int = 0
    content_hash: str = ""

    def __post_init__(self) -> None:
        if not self.content_hash:
            self.content_hash = hashlib.sha256(self.text.encode("utf-8")).hexdigest()
        if self.char_end == 0 and self.text:
            self.char_end = len(self.text)


def extract_segments(file_bytes: bytes, file_type: str) -> list[ExtractedSegment]:
    """Extract text as segments, preserving page/section metadata."""
    ft = file_type.lower()
    if ft == "pdf":
        return _extract_pdf_segments(file_bytes)
    if ft == "docx":
        return _extract_docx_segments(file_bytes)
    if ft in ("txt", "md"):
        return _extract_text_segments(file_bytes, parse_headings=(ft == "md"))
    raise ValueError(f"Unsupported file type: '{file_type}'")


def extract_text(file_bytes: bytes, file_type: str) -> str:
    """Backwards-compatible plain-text extraction (segments joined)."""
    return "\n\n".join(s.text for s in extract_segments(file_bytes, file_type))


def _extract_pdf_segments(data: bytes) -> list[ExtractedSegment]:
    try:
        segments: list[ExtractedSegment] = []
        scanned_pages = 0
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page_no, page in enumerate(pdf.pages, start=1):
                page_text = page.extract_text() or ""
                if not page_text.strip():
                    images = getattr(page, "images", None) or []
                    if images:
                        scanned_pages += 1
                    continue
                segments.append(ExtractedSegment(text=page_text.strip(), page=page_no))
        if not segments and scanned_pages:
            raise ScannedDocumentError(
                "This PDF appears to be a scanned document: its pages contain "
                "images but no extractable text. Please upload a text-based "
                "PDF or a document with selectable text."
            )
        return segments
    except ScannedDocumentError:
        raise
    except Exception as exc:
        raise ValueError(f"Failed to extract text from PDF: {exc}") from exc


def _extract_docx_segments(data: bytes) -> list[ExtractedSegment]:
    try:
        doc = DocxDocument(io.BytesIO(data))

        def _fallback_segments() -> list[ExtractedSegment]:
            # Unordered paragraph/table walk; headings still detected
            # from paragraph styles. Used when the ordered body walk
            # yields nothing (e.g. a mocked document in tests).
            out: list[ExtractedSegment] = []
            section: str | None = None
            for para in doc.paragraphs:
                text = para.text.strip()
                if not text:
                    continue
                style = (para.style.name or "") if para.style is not None else ""
                if isinstance(style, str) and style.startswith("Heading"):
                    section = text
                out.append(ExtractedSegment(text=text, section=section))
            for table in doc.tables:
                rows = [
                    " | ".join(cell.text.strip() for cell in row.cells)
                    for row in table.rows
                ]
                rows = [r for r in rows if r.strip(" |").strip()]
                if rows:
                    out.append(ExtractedSegment(text="\n".join(rows), section=section))
            return out

        segments: list[ExtractedSegment] = []
        section: str | None = None
        try:
            from docx.oxml.ns import qn
            from docx.table import Table
            from docx.text.paragraph import Paragraph

            body = doc.element.body
            for child in body:
                if child.tag == qn("w:p"):
                    para = Paragraph(child, doc)
                    text = para.text.strip()
                    if not text:
                        continue
                    style = (para.style.name or "") if para.style is not None else ""
                    if isinstance(style, str) and style.startswith("Heading"):
                        section = text
                    segments.append(ExtractedSegment(text=text, section=section))
                elif child.tag == qn("w:tbl"):
                    table = Table(child, doc)
                    rows = [
                        " | ".join(cell.text.strip() for cell in row.cells)
                        for row in table.rows
                    ]
                    rows = [r for r in rows if r.strip(" |").strip()]
                    if rows:
                        segments.append(
                            ExtractedSegment(text="\n".join(rows), section=section)
                        )
        except Exception:  # noqa: BLE001 -- body walk failure falls back to paragraphs/tables
            return _fallback_segments()
        if not segments:
            return _fallback_segments()
        return segments
    except Exception as exc:
        raise ValueError(f"Failed to extract text from DOCX: {exc}") from exc


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


def _extract_text_segments(data: bytes, parse_headings: bool) -> list[ExtractedSegment]:
    text = data.decode("utf-8", errors="replace")
    segments: list[ExtractedSegment] = []
    section: str | None = None
    block_lines: list[str] = []

    def flush() -> None:
        nonlocal block_lines
        block = "\n".join(block_lines).strip()
        if block:
            segments.append(ExtractedSegment(text=block, section=section))
        block_lines = []

    for line in text.splitlines():
        heading = _HEADING_RE.match(line) if parse_headings else None
        if heading:
            flush()
            section = heading.group(2).strip()
            segments.append(ExtractedSegment(text=line.strip(), section=section))
        elif not line.strip():
            flush()
        else:
            block_lines.append(line)
    flush()
    return segments


# A sentence is a run of characters ending in terminal punctuation (or a
# line break / end of text). Newlines break units so paragraph structure
# is respected even when punctuation is missing.
_SENTENCE_RE = re.compile(r"[^.!?\n]+(?:[.!?]+[\"'\)\]]*)?(?:\s+|$)")


@dataclass
class _Unit:
    start: int
    end: int
    tokens: int
    page: int | None
    section: str | None


def _segment_for_offset(
    spans: list[tuple[int, int, ExtractedSegment]], pos: int
) -> ExtractedSegment | None:
    for start, end, seg in spans:
        if start <= pos < end:
            return seg
    return spans[-1][2] if spans else None


def chunk_text(
    text: str,
    document_id: uuid.UUID,
    document_name: str,
    chunk_size: int = settings.CHUNK_SIZE_TOKENS,
    overlap: int = settings.CHUNK_OVERLAP_TOKENS,
    segments: list[ExtractedSegment] | None = None,
) -> list[TextChunk]:
    if not text or not text.strip():
        return []

    tokenizer = get_tokenizer()
    if segments is None:
        segments = [ExtractedSegment(text=text)]
    spans: list[tuple[int, int, ExtractedSegment]] = []
    offset = 0
    for i, seg in enumerate(segments):
        spans.append((offset, offset + len(seg.text), seg))
        offset += len(seg.text) + (2 if i < len(segments) - 1 else 0)

    units: list[_Unit] = []
    for match in _SENTENCE_RE.finditer(text):
        raw = match.group(0)
        stripped = raw.rstrip()
        if not stripped:
            continue
        start = match.start()
        end = start + len(stripped)
        # Renamed: the span loop above already binds `seg` as
        # ExtractedSegment, so reusing it for a possibly-None lookup
        # result is a type error.
        seg_for_unit = _segment_for_offset(spans, start)
        units.append(
            _Unit(
                start=start,
                end=end,
                tokens=len(tokenizer.encode(stripped)),
                page=seg_for_unit.page if seg_for_unit else None,
                section=seg_for_unit.section if seg_for_unit else None,
            )
        )
    if not units:
        return []

    chunks: list[TextChunk] = []

    def emit(cur: list[_Unit]) -> None:
        if not cur:
            return
        chunk_text_str = text[cur[0].start : cur[-1].end]
        if not chunk_text_str.strip():
            return
        chunks.append(
            TextChunk(
                text=chunk_text_str,
                chunk_index=len(chunks),
                document_id=document_id,
                document_name=document_name,
                page=cur[0].page,
                section=cur[0].section,
                char_start=cur[0].start,
                char_end=cur[-1].end,
            )
        )

    def emit_token_windows(unit: _Unit) -> None:
        """Fallback for one oversized unit: plain token windows."""
        unit_text = text[unit.start : unit.end]
        tokens = tokenizer.encode(unit_text)
        if not tokens:
            return
        # Token strings concatenate back to the unit text for cl100k, so
        # per-token decoded lengths give exact char offsets.
        lengths = [len(tokenizer.decode([t])) for t in tokens]
        cum = [0]
        for length in lengths:
            cum.append(cum[-1] + length)
        step = max(1, chunk_size - overlap)
        start_tok = 0
        while start_tok < len(tokens):
            end_tok = min(start_tok + chunk_size, len(tokens))
            window_text = tokenizer.decode(tokens[start_tok:end_tok])
            if window_text.strip():
                chunks.append(
                    TextChunk(
                        text=window_text,
                        chunk_index=len(chunks),
                        document_id=document_id,
                        document_name=document_name,
                        page=unit.page,
                        section=unit.section,
                        char_start=unit.start + cum[start_tok],
                        char_end=unit.start + cum[end_tok],
                    )
                )
            if end_tok >= len(tokens):
                break
            start_tok += step

    i = 0
    overlap_units: list[_Unit] = []
    while i < len(units):
        unit = units[i]
        if unit.tokens > chunk_size:
            # Overlap units were already emitted as part of the previous
            # chunk; they are a prefix for the next chunk, not a chunk of
            # their own, so they are simply dropped here.
            overlap_units = []
            emit_token_windows(unit)
            i += 1
            continue
        cur: list[_Unit] = list(overlap_units)
        cur_tokens = sum(u.tokens for u in cur)
        j = i
        while j < len(units):
            candidate = units[j]
            if candidate.tokens > chunk_size:
                break
            if cur and cur_tokens + candidate.tokens > chunk_size:
                break
            cur.append(candidate)
            cur_tokens += candidate.tokens
            j += 1
        if j == i:
            if overlap_units:
                # Carried overlap alone leaves no room for the next unit:
                # drop the overlap and retry with a fresh chunk instead of
                # re-emitting the overlap as a duplicate chunk (and looping).
                overlap_units = []
                continue
            # Defensive: should be unreachable (oversized handled above).
            emit_token_windows(unit)
            i += 1
            continue
        emit(cur)
        # Next chunk's overlap: trailing units of this chunk totalling
        # at most ``overlap`` tokens (at least the last unit, if any).
        new_overlap: list[_Unit] = []
        total = 0
        for u in reversed(cur):
            if new_overlap and total + u.tokens > overlap:
                break
            new_overlap.append(u)
            total += u.tokens
            if total >= overlap:
                break
        overlap_units = list(reversed(new_overlap)) if overlap > 0 else []
        # Only overlap units that were already consumed may be carried;
        # they are all < j by construction.
        i = j
        if i >= len(units):
            break
    return chunks
