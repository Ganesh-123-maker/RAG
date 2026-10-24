"""Export the FastAPI OpenAPI schema to docs/openapi.json.

This is the API reference generator for Phase G: the schema is produced
from the live FastAPI application object, never hand-written, so it
cannot drift from the routes that actually exist.

Usage (from the repo root, backend dependencies installed):

    ENVIRONMENT=test OPENAI_API_KEY=test-placeholder-key \\
        python backend/scripts/export_openapi.py

The script does not start the server and does not call OpenAI, Qdrant,
or PostgreSQL: ``app.openapi()`` only inspects the route table. It
writes ``docs/openapi.json`` relative to the repo root and prints the
route count so a stale export is easy to spot.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.main import app  # noqa: E402


def main() -> None:
    schema = app.openapi()
    out = REPO_ROOT / "docs" / "openapi.json"
    out.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    routes = [p for p in schema.get("paths", {})]
    print(f"Wrote {out} ({len(routes)} paths, title={schema['info']['title']})")


if __name__ == "__main__":
    main()
