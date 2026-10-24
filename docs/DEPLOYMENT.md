# Deployment

## Chosen stack (Phase G)

| Piece | Platform | Why this one |
|---|---|---|
| Frontend | Vercel | Native Next.js hosting; no config file needed for Next.js (there is deliberately no `vercel.json` in this repo -- inventing one would add nothing). |
| Backend | Render, Docker web service (`render.yaml`) | Single declarative file, Docker entrypoint already runs `alembic upgrade head` then uvicorn, health check path `/health` exists. |
| Postgres | Render Postgres (free tier, `render.yaml`) | Managed, and the app already speaks asyncpg. |
| Qdrant | Qdrant Cloud free tier | The app already supports Qdrant Cloud (API key + HTTPS on port 443); Render does not host Qdrant in this config. |

Alternatives considered and not chosen: Fly.io (also viable, but
adds a second CLI/config surface for no benefit here) and Railway
(similar; Render's `render.yaml` + dashboard-secret model is the
simplest to audit). If the maintainer prefers Fly.io/Railway, only
this document and `render.yaml` change -- the app itself is
platform-agnostic (Docker image + env vars).

## Status: NOT DEPLOYED (credentials missing)

**No live URL exists as of v1.0.0.** No Vercel, Render, Fly.io, or
Railway token was present in the Phase G sandbox (checked by
presence only; no token was printed or read). The live-deploy
sub-task was therefore stopped deliberately, and everything else in
Phase G continued. Do not claim the old Vercel URL: it was never
verified from this repository and is removed from the README.

## Exactly what the maintainer must provide

1. **Render account + dashboard access.** Apply `render.yaml`
   (Render Dashboard -> New -> Blueprint, or `render blueprint`
   via the Render CLI). Then set these secrets in the Render
   dashboard for the `rag-backend` service (all marked `sync: false`
   in `render.yaml`, so they are never in the repo):
   - `OPENAI_API_KEY` -- valid key with quota.
   - `JWT_SECRET_KEY` -- random, at least 32 characters.
   - `QDRANT_HOST` -- Qdrant Cloud cluster host, e.g.
     `<cluster-id>.qdrant.io` (host only, no scheme, no port).
   - `QDRANT_API_KEY` -- Qdrant Cloud API key.
2. **DATABASE_URL scheme fix (required, easy to miss).** Render's
   `fromDatabase` connection string uses the `postgres://` scheme,
   but this app (SQLAlchemy async + Alembic) requires
   `postgresql+asyncpg://`. After applying the blueprint, edit the
   web service's `DATABASE_URL` in the Render dashboard to the
   Postgres internal URL with that scheme substituted. Until that
   edit, the service will fail to start. This is a Render
   configuration step, not a code bug, and it is called out here
   and in `render.yaml` so it is not discovered by trial and error.
3. **Qdrant Cloud free-tier cluster** (create it first, then fill in
   `QDRANT_HOST`/`QDRANT_API_KEY` above). `QDRANT_PORT` is `443`
   in `render.yaml`; the old README's `6333` was wrong for cloud.
4. **Vercel project:** import the repo, set **Root Directory** to
   `frontend`, Framework Preset Next.js, and set the environment
   variable **`BACKEND_URL`** to the Render backend URL
   (e.g. `https://rag-backend.onrender.com`). Note: the old guide's
   `NEXT_PUBLIC_API_URL` was dead config -- the frontend proxy reads
   `BACKEND_URL` in `next.config.js` rewrites, and `NEXT_PUBLIC_API_URL`
   is read nowhere. Also set the Vercel domain as a CORS origin:
   update the Render service's `BACKEND_CORS_ORIGINS` to
   `["https://<your-vercel-domain>"]` (production startup rejects
   `*`).
5. **GitHub secrets (only if CI-driven deploy is wanted later).**
   No deploy workflow is wired to secrets in v1.0.0, so nothing is
   blocked on them today. If a deploy workflow is added later, it
   will need `RENDER_API_KEY` + `RENDER_SERVICE_ID` (Render) and/or
   `VERCEL_TOKEN` + `VERCEL_PROJECT_ID` (Vercel) as GitHub secrets,
   and this document must be updated to name the workflow.

## Deploy steps (once credentials exist)

```bash
# 1. Backend (Render): apply render.yaml, set the secrets above,
#    fix the DATABASE_URL scheme, deploy. The Dockerfile CMD runs
#    `alembic upgrade head` then uvicorn, so no separate migration
#    step is needed.
# 2. Frontend (Vercel): import repo, Root Directory = frontend,
#    BACKEND_URL = <Render backend URL>, deploy.
# 3. Smoke test (see below) against the live URLs.
```

## Smoke test (live, after deploying)

```bash
curl -fsS https://<render-backend>/health        # {"status":"ok"}
curl -fsS https://<render-backend>/ready        # {"status":"ready"} (Postgres + Qdrant)
curl -fsS https://<vercel-frontend>/login | head -c 200   # login page HTML, HTTP 200
```

Then, in the browser: register, upload a small TXT document, wait
for `ready`, ask a question about it, and confirm a cited answer
streams. Record the real URLs and the smoke results in this document
and in the release notes -- do not backfill a URL that was not
smoke-tested. A chat smoke needs a valid `OPENAI_API_KEY`; a
placeholder key proves boot/readiness only, exactly as in the CI
`compose-smoke` job.

## Local / compose smoke (what CI does instead)

CI's `compose-smoke` job runs `docker compose up -d --build` with a
test key and checks `/health` + `/ready` + the frontend login page.
That proves boot, migration, and readiness -- not chat. Docker was
not available in the Phase G sandbox, so the compose smoke was not
run there either; it is a CI verification, not a claimed local pass.

## Rollback

- Render: redeploy the previous commit from the Render dashboard
  (or `git revert` + push, since deploys track the branch).
- Vercel: redeploy a previous deployment from the Vercel dashboard.
- Database: migrations are forward-only in this repo (no down
  migrations are relied upon); a rollback that needs a schema revert
  must be planned as its own migration, not assumed.
