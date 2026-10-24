"""Regenerate the binary corpus files from committed text sources.

Outputs (committed, so the runner works without regenerating):
  corpus/langgraph.pdf  -- from corpus/langgraph_source.txt
  corpus/jwt-auth.docx  -- from corpus/jwt-auth_source.txt

The PDF writer is intentionally dependency-free: it writes a minimal,
valid PDF (Helvetica, one text stream per page) that pdfplumber can
read. It exists so corpus regeneration does not require reportlab or
fpdf, which are not production dependencies. The DOCX writer uses
python-docx, already a production dependency. Re-running this script
must produce byte-stable output for the same sources (no timestamps
in the PDF objects), so regenerated files diff cleanly.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "corpus"


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def write_pdf(source: Path, dest: Path) -> None:
    """Write a minimal multi-page PDF from plain text."""
    lines: list[str] = []
    for paragraph in source.read_text(encoding="utf-8").split("\n\n"):
        paragraph = " ".join(paragraph.split())
        if not paragraph:
            continue
        lines.extend(textwrap.wrap(paragraph, width=88) or [""])
        lines.append("")
    pages: list[list[str]] = []
    per_page = 42
    for i in range(0, len(lines), per_page):
        pages.append(lines[i : i + per_page])

    objects: list[bytes] = []
    # Object numbering: 1 = catalog, 2 = pages, then per page: page + content.
    page_obj_ids = [3 + 2 * i for i in range(len(pages))]
    content_obj_ids = [4 + 2 * i for i in range(len(pages))]
    kids = " ".join(f"{pid} 0 R" for pid in page_obj_ids)
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    for pid, cid, page_lines in zip(page_obj_ids, content_obj_ids, pages):
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 5 0 R >> >> /Contents {cid} 0 R >>".encode()
        )
        stream_lines = ["BT /F1 11 Tf 48 744 Td 14 TL"]
        for line in page_lines:
            stream_lines.append(f"({_pdf_escape(line)}) Tj T*")
        stream_lines.append("ET")
        stream = "\n".join(stream_lines).encode("latin-1", errors="replace")
        objects.append(
            b"<< /Length "
            + str(len(stream)).encode()
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )
    # Font object: id = 5 + 2*len(pages)... actually appended after pages;
    # fix: font must be object 5 only if one page. Compute font id properly:
    # Rebuild with font as the last object; page resources reference it
    # by its final id. To keep numbering simple, font id = 3 + 2*n_pages.
    font_id = 3 + 2 * len(pages)
    # Rewrite page objects to point at the real font id.
    fixed: list[bytes] = []
    for obj in objects:
        fixed.append(obj.replace(b"/F1 5 0 R", f"/F1 {font_id} 0 R".encode()))
    objects = fixed
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for idx, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{idx} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode()
    dest.write_bytes(bytes(out))


def write_docx(source: Path, dest: Path) -> None:
    from docx import Document

    doc = Document()
    for paragraph in source.read_text(encoding="utf-8").split("\n\n"):
        paragraph = " ".join(paragraph.split())
        if not paragraph:
            continue
        doc.add_paragraph(paragraph)
    doc.save(str(dest))


def main() -> int:
    write_pdf(CORPUS / "langgraph_source.txt", CORPUS / "langgraph.pdf")
    write_docx(CORPUS / "jwt-auth_source.txt", CORPUS / "jwt-auth.docx")
    print("Wrote langgraph.pdf and jwt-auth.docx")
    return 0


if __name__ == "__main__":
    sys.exit(main())
