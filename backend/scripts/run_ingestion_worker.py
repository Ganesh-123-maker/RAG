"""DB-backed ingestion worker (Phase E).

Processes documents left in status 'queued' (e.g. after a crash
mid-upload). This is deliberately NOT FastAPI BackgroundTasks:
BackgroundTasks are lost on restart and have no durable status,
whereas a queued row survives a restart and is visible to clients
via GET /documents (queued -> processing -> ready/error).

Usage:
    python scripts/run_ingestion_worker.py --once
    python scripts/run_ingestion_worker.py --loop --interval 30
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import AsyncSessionLocal
from app.services.document_service import DocumentService

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)


async def run_once() -> dict[str, int]:
    async with AsyncSessionLocal() as session:
        svc = DocumentService(session)
        result = await svc.process_queued_documents()
        await session.commit()
        return result


async def main() -> int:
    parser = argparse.ArgumentParser(description="Ingestion queue worker")
    parser.add_argument(
        "--once", action="store_true", help="Process queued docs once and exit"
    )
    parser.add_argument("--loop", action="store_true", help="Poll forever")
    parser.add_argument(
        "--interval", type=int, default=30, help="Poll interval in seconds (loop mode)"
    )
    args = parser.parse_args()
    if args.loop:
        logger.info(
            "Ingestion worker polling every %ss (single-instance)", args.interval
        )
        while True:
            result = await run_once()
            if result["total"]:
                logger.info("Worker processed: %s", result)
            await asyncio.sleep(args.interval)
        return 0
    result = await run_once()
    logger.info("Worker result: %s", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
