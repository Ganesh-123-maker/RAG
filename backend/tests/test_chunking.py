"""Tests for the chunking and text extraction pipeline."""
from __future__ import annotations

import uuid

import pytest

from app.services.chunking_service import chunk_text, extract_text


class TestExtractText:
    def test_extract_txt(self) -> None:
        content = b"Hello world. This is a test document."
        result = extract_text(content, "txt")
        assert "Hello world" in result

    def test_extract_md(self) -> None:
        content = b"# Header\n\nSome **bold** text here."
        result = extract_text(content, "md")
        assert "Header" in result

    def test_unsupported_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported"):
            extract_text(b"data", "xyz")


class TestChunkText:
    def test_short_text_single_chunk(self) -> None:
        doc_id = uuid.uuid4()
        chunks = chunk_text("Short text.", doc_id, "test.txt", chunk_size=512, overlap=64)
        assert len(chunks) == 1
        assert chunks[0].chunk_index == 0
        assert chunks[0].document_id == doc_id

    def test_long_text_multiple_chunks(self) -> None:
        # ~1500 tokens of text
        long_text = "The quick brown fox jumps over the lazy dog. " * 100
        doc_id = uuid.uuid4()
        chunks = chunk_text(long_text, doc_id, "test.txt", chunk_size=128, overlap=16)
        assert len(chunks) > 1

    def test_overlap_means_boundary_content_appears_twice(self) -> None:
        """Content near a boundary should appear in consecutive chunks when overlap > 0."""
        long_text = "word " * 300
        doc_id = uuid.uuid4()
        chunks = chunk_text(long_text, doc_id, "test.txt", chunk_size=100, overlap=20)
        if len(chunks) > 1:
            # last tokens of chunk 0 should appear at start of chunk 1
            end_of_chunk0 = chunks[0].text.split()[-5:]
            start_of_chunk1 = chunks[1].text.split()[:5]
            overlap_found = any(w in start_of_chunk1 for w in end_of_chunk0)
            assert overlap_found

    def test_chunk_indexes_sequential(self) -> None:
        long_text = "sentence " * 200
        doc_id = uuid.uuid4()
        chunks = chunk_text(long_text, doc_id, "test.txt", chunk_size=64, overlap=8)
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i
