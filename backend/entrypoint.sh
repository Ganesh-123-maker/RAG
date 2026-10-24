#!/bin/sh
# Backend container entrypoint (Phase A, extended Phase G): apply Alembic
# migrations, wait for Qdrant, then start the API. Schema is owned by
# migrations, not by create_all().
set -e
echo "Running database migrations..."
alembic upgrade head

# Phase G: wait for Qdrant readiness here, with the backend image's own
# Python stdlib, instead of a Qdrant-container healthcheck. The
# qdrant/qdrant image ships no wget/curl, so the old compose
# healthcheck (`wget .../healthz`) failed forever and `docker compose
# up` reported Qdrant unhealthy even though Qdrant itself was fine
# (proven by CI compose-smoke on PR #7). Readiness is also re-checked
# by the app's /ready endpoint (Postgres + Qdrant) after boot.
# In-memory / path-based Qdrant modes need no wait.
QDRANT_HOST_VALUE="${QDRANT_HOST:-localhost}"
case "$QDRANT_HOST_VALUE" in
  ":memory:"|./*|/*)
    echo "Skipping Qdrant wait (in-memory/path mode: $QDRANT_HOST_VALUE)"
    ;;
  *)
    if [ -n "${QDRANT_API_KEY:-}" ]; then
      QDRANT_SCHEME="https"
    else
      QDRANT_SCHEME="http"
    fi
    echo "Waiting for Qdrant at ${QDRANT_SCHEME}://${QDRANT_HOST_VALUE}:${QDRANT_PORT:-6333}/healthz ..."
    QDRANT_HOST="$QDRANT_HOST_VALUE" QDRANT_PORT="${QDRANT_PORT:-6333}" QDRANT_SCHEME="$QDRANT_SCHEME" python3 - <<'PYEOF'
import os
import sys
import time
import urllib.request

host = os.environ["QDRANT_HOST"]
port = os.environ["QDRANT_PORT"]
scheme = os.environ["QDRANT_SCHEME"]
url = f"{scheme}://{host}:{port}/healthz"
deadline = time.time() + 120
while True:
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            if resp.status == 200:
                print("Qdrant is ready.")
                break
    except Exception:
        pass
    if time.time() >= deadline:
        print(f"Timed out waiting for Qdrant at {url}", file=sys.stderr)
        sys.exit(1)
    time.sleep(2)
PYEOF
    ;;
esac

echo "Starting API..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level info
