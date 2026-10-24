"""Orphan reconciliation (Phase E).

Finds:
  1. Files under UPLOAD_DIR with no matching DB document row
     (by stored filename).
  2. Qdrant points (sampled via scroll, --limit) whose document_id
     has no DB document row.
  3. DB documents in status 'error' whose vectors still exist
     (reported only; vector deletion for error rows is covered by
     ingestion cleanup, so a hit here means cleanup failed).

Dry-run by default: prints what WOULD be deleted and deletes
nothing. --apply deletes orphan FILES only. --apply-vectors
additionally deletes orphan Qdrant points. Deleting vectors is
a separate, explicit flag because vector deletion is harder to
undo than file deletion.

Usage:
    python scripts/reconcile_orphans.py [--apply] [--apply-vectors] [--limit 1000]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.document import Document


def find_orphan_files(upload_dir: Path, known_filenames: set[str]) -> list[Path]:
    """Pure function: files on disk whose name no DB row references."""
    orphans: list[Path] = []
    if not upload_dir.exists():
        return orphans
    for path in upload_dir.rglob("*"):
        if path.is_file() and path.name not in known_filenames:
            orphans.append(path)
    return orphans


def find_orphan_vector_doc_ids(
    point_doc_ids: set[str], known_doc_ids: set[str]
) -> set[str]:
    """Pure function: document_ids present in Qdrant but not in the DB."""
    return point_doc_ids - known_doc_ids


async def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile orphan files/vectors")
    parser.add_argument("--apply", action="store_true", help="Delete orphan files")
    parser.add_argument(
        "--apply-vectors", action="store_true", help="Delete orphan Qdrant points"
    )
    parser.add_argument(
        "--limit", type=int, default=1000, help="Qdrant scroll sample size"
    )
    args = parser.parse_args()
    settings = get_settings()
    upload_dir = Path(settings.UPLOAD_DIR).resolve()

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(Document.filename, Document.id))).all()
        known_files = {r[0] for r in rows}
        known_ids = {str(r[1]) for r in rows}
        error_ids = {
            str(r[1])
            for r in (
                await session.execute(
                    select(Document.id).where(Document.status == "error")
                )
            ).all()
        }

    orphan_files = find_orphan_files(upload_dir, known_files)
    print(f"Orphan files: {len(orphan_files)}")
    for path in orphan_files:
        print(f"  {path}")
        if args.apply:
            path.unlink(missing_ok=True)

    # Qdrant scan is sampled: a full scroll of a large collection
    # could be slow, so --limit bounds it and the report says so.
    from app.services.vector_store_service import get_qdrant_client

    client = get_qdrant_client()
    point_doc_ids: set[str] = set()
    try:
        points, _ = await client.scroll(
            collection_name=settings.QDRANT_COLLECTION,
            limit=args.limit,
            with_payload=["document_id"],
        )
        for point in points:
            doc_id = (point.payload or {}).get("document_id")
            if doc_id:
                point_doc_ids.add(str(doc_id))
    except Exception as exc:  # noqa: BLE001 -- reconcile must report, not crash
        print(f"Qdrant scan failed (files above are still accurate): {exc}")
        return 0
    orphan_ids = find_orphan_vector_doc_ids(point_doc_ids, known_ids)
    print(f"Orphan vector document_ids (sample of {args.limit}): {sorted(orphan_ids)}")
    print(
        f"Error-row document_ids still present in Qdrant sample: {sorted(orphan_ids & error_ids)}"
    )
    if args.apply_vectors and orphan_ids:
        from qdrant_client.models import (
            FieldCondition,
            Filter,
            FilterSelector,
            MatchValue,
        )

        for doc_id in sorted(orphan_ids):
            await client.delete(
                collection_name=settings.QDRANT_COLLECTION,
                points_selector=FilterSelector(
                    filter=Filter(
                        must=[
                            FieldCondition(
                                key="document_id", match=MatchValue(value=doc_id)
                            )
                        ]
                    )
                ),
            )
        print(f"Deleted vectors for {len(orphan_ids)} orphan document(s).")
    if not args.apply:
        print("Dry run: nothing was deleted. Re-run with --apply to delete files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
