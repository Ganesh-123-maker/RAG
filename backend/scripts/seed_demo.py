"""Seed a running stack with a demo user and sample documents.

This is a convenience script for demos, not a fixture and not a test:
it talks to a *running* backend over HTTP, so it needs the stack up
(``docker compose up`` or ``start-local.ps1``) and a working OpenAI key
for ingestion to reach ``ready`` -- uploads are queued (Phase E) and
a failed embedding lands the document in ``error`` status, which the
script reports honestly instead of hiding. Re-run the list step later
(or poll in the dashboard) to see final statuses.

Sample documents are the self-written Phase D evaluation corpus
(``backend/eval/corpus/``); no copyrighted text and no secrets are
involved. Credentials are never hardcoded: pass ``--password`` or set
``DEMO_PASSWORD`` (or answer the prompt); the demo user is created
with ``POST /api/v1/auth/register`` and, if it already exists, the
script logs in instead.

Usage:

    python backend/scripts/seed_demo.py --api-url http://localhost:8000
    python backend/scripts/seed_demo.py --api-url http://localhost:8000 \\
        --email demo@example.com --password '...' --limit 3

Exit code is 0 only if the user exists and every upload was accepted
(HTTP 2xx); ingestion status is printed per document afterwards.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIR = REPO_ROOT / "backend" / "eval" / "corpus"

# Demo corpus files (self-written, Phase D). Binary formats are included
# deliberately so the demo exercises PDF/DOCX extraction, not just TXT.
DEMO_FILES = [
    "vector-databases.txt",
    "qdrant.md",
    "chunking.txt",
    "embeddings.md",
    "sse.txt",
]


def _auth_token(client: httpx.Client, email: str, password: str) -> str:
    # Register returns a UserResponse (no token), so login is always
    # the second step; a 409 means the user already exists, which is
    # also fine -- login below then succeeds.
    payload = {"email": email, "password": password, "full_name": "Demo User"}
    resp = client.post("/api/v1/auth/register", json=payload)
    if resp.status_code not in (200, 201, 409):
        resp.raise_for_status()
    resp = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    resp.raise_for_status()
    return str(resp.json()["access_token"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--email", default="demo@example.com")
    parser.add_argument("--password", default=os.environ.get("DEMO_PASSWORD"))
    parser.add_argument("--limit", type=int, default=len(DEMO_FILES))
    args = parser.parse_args()
    password = args.password or getpass.getpass("Demo user password: ")
    if not password:
        print("Refusing to create a demo user with an empty password.", file=sys.stderr)
        return 2

    ok = True
    with httpx.Client(base_url=args.api_url, timeout=120.0) as client:
        token = _auth_token(client, args.email, password)
        print(f"Demo user ready: {args.email}")
        headers = {"Authorization": f"Bearer {token}"}
        for name in DEMO_FILES[: args.limit]:
            path = CORPUS_DIR / name
            if not path.exists():
                print(f"SKIP (missing corpus file): {name}")
                ok = False
                continue
            with path.open("rb") as fh:
                resp = client.post(
                    "/api/v1/documents/upload",
                    files={"file": (name, fh)},
                    headers=headers,
                )
            if resp.status_code in (200, 201):
                doc = resp.json()
                print(
                    f"Uploaded {name}: id={doc.get('id')} "
                    f"status={doc.get('status')} chunks={doc.get('chunk_count')}"
                )
            else:
                print(f"FAILED {name}: HTTP {resp.status_code} {resp.text[:200]}")
                ok = False
        resp = client.get("/api/v1/documents", headers=headers)
        if resp.status_code == 200:
            for doc in resp.json().get("documents", []):
                print(
                    f"  {doc.get('original_name')}: {doc.get('status')} "
                    f"({doc.get('chunk_count')} chunks)"
                )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
