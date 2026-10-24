# Cross-platform Makefile (Phase G). The .ps1 scripts remain as an
# optional Windows path; nothing here deletes or replaces them.
# Every target is safe to re-run. Docker targets need Docker;
# eval-live needs a valid OPENAI_API_KEY (see docs/EVALUATION.md).

.PHONY: help test lint build up down eval-offline eval-live openapi seed clean

help: ## Show targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/ -- /'

test: ## Backend pytest + frontend Vitest (proxy vars cleared for backend)
	cd backend && env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy -u ALL_PROXY -u all_proxy -u NO_PROXY -u no_proxy OPENAI_API_KEY=test-placeholder-key DATABASE_URL='sqlite+aiosqlite:///:memory:' QDRANT_HOST=':memory:' JWT_SECRET_KEY='ci-test-secret-key-minimum-32-chars-long' ENVIRONMENT=test python -m pytest tests/ -q --cov=app --cov-fail-under=80
	cd frontend && npm test

lint: ## Ruff + frontend lint/typecheck
	cd backend && ruff check app tests eval && ruff format --check app tests eval
	cd frontend && npm run lint && npx tsc --noEmit

build: ## Next.js build + both Docker images (needs Docker for images)
	cd frontend && npm run build
	docker build ./backend -t rag-backend:local
	docker build ./frontend -t rag-frontend:local

up: ## Start the compose stack (needs .env with OPENAI_API_KEY; see README)
	docker compose up -d --build

down: ## Stop the compose stack and remove volumes
	docker compose down -v

eval-offline: ## Offline pipeline smoke ONLY (not a quality measurement)
	cd backend && python eval/run_eval.py --mode offline

eval-live: ## Real evaluation (needs OPENAI_API_KEY; see docs/EVALUATION.md)
	cd backend && python eval/run_eval.py --mode live --limit 20

openapi: ## Regenerate docs/openapi.json from the FastAPI app
	ENVIRONMENT=test OPENAI_API_KEY=test-placeholder-key python backend/scripts/export_openapi.py

seed: ## Seed a RUNNING stack with demo user + corpus docs (see script help)
	python backend/scripts/seed_demo.py --api-url http://localhost:8000

clean: ## Remove local build/test artefacts (never committed anyway)
	rm -rf backend/htmlcov backend/coverage.xml backend/.coverage frontend/.next
