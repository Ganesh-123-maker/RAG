# Contributing

## Ground rules

- **Honesty first.** Never invent a metric, a test result, or a
  deployment. Every number in the README or docs must come from a
  run you actually performed, with the output committed (eval runs
  under `docs/eval/`, test/coverage numbers from a real run).
  If you cannot verify something, say so in the report and docs.
- **One RAG path.** Both chat endpoints run the same LangGraph.
  Do not reintroduce a second retrieval/prompt/citation path for
  streaming or any other surface; extend the graph instead.
- **No fallback vectors, ever.** Embedding failure is a visible
  error with cleanup, not a substitute vector. This rule exists
  because a silent substitute corrupts the index.
- **No secrets in the repo.** No `.env`, no API keys, no tokens in
  code, docs, or commit messages. Check staged files before
  committing (`git diff --cached` and a grep for `sk-` / key
  material). Never force-push, never rewrite history.
- **Tests for behaviour changes.** Prefer real components
  (SQLite, in-memory Qdrant) over mocks; keep mocks only for paid
  external calls (OpenAI). A live integration test, if added,
  must be marked `@pytest.mark.live` and opt-in.

## Workflow

1. Branch from `main` (or from the current phase branch if work is
   stacked): `git checkout -b <type>/<short-name>`.
2. Run the relevant checks before pushing:
   ```bash
   cd backend
   ruff check app tests eval && ruff format --check app tests eval
   python -m pytest tests/ -q --cov=app --cov-fail-under=80
   cd ../frontend
   npm run lint && npx tsc --noEmit && npm test && npm run build
   ```
   Backend tests need proxy variables cleared in some sandboxes
   (including `NO_PROXY` -- see `docs/phase-g-report.md`); CI sets
   a clean environment, so a sandbox-only proxy failure is an
   environment artifact, not a code failure, but verify that claim
   before dismissing a failure.
3. Commit with Conventional Commits (`feat:`, `fix:`, `docs:`,
   `test:`, `chore:`). Push the branch and open a PR; do not push
   directly to `main` unless the maintainer explicitly says so for
   that change.
4. CI must be green on the blocking jobs. Non-blocking jobs (mypy,
   security scans) are documented in `docs/phase-g-report.md` and
   `docs/SECURITY.md`; a failure there is still reported in the PR,
   never hidden.

## Code conventions

- Layering: routers -> services -> repositories. No retrieval or
  embedding logic in routers; no HTTP logic in services.
- Typed, small, documented code. New backend modules pass
  `ruff check` + `ruff format`; mypy is currently non-blocking
  (14 pre-existing errors -- see the phase-g report) and new code
  should not add to that count.
- Frontend: typed API client in `lib/api.ts` (do not reintroduce
  per-component fetch calls or JS token handling), sanitised
  Markdown rendering, no raw HTML execution.
- Pre-commit (optional, configured in `.pre-commit-config.yaml`):
  `pip install pre-commit && pre-commit install`. It was configured
  in Phase G, not run over the whole history.

## Adding an evaluation run

See `docs/EVALUATION.md`. Live runs go to a new `docs/eval/<run-id>/`
directory, are never overwritten, and every record carries a `mode`
field. Offline smoke numbers must never be quoted as quality.
