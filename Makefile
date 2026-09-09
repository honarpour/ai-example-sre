.PHONY: dev dev-backend dev-frontend install test test-live eval types lint tools-demo

install:
	cd backend && python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
	cd frontend && pnpm install

dev-backend:
	cd backend && . .venv/bin/activate && uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd frontend && pnpm dev

dev:
	@echo "Starting backend (:8000) and frontend (:5173). Ctrl+C stops both."
	@trap 'kill 0' EXIT; \
	(cd backend && . .venv/bin/activate && uvicorn app.main:app --reload --port 8000) & \
	(cd frontend && pnpm dev) & \
	wait

types:
	cd backend && . .venv/bin/activate && python scripts/export_openapi.py
	cd frontend && pnpm types

tools-demo:
	cd backend && . .venv/bin/activate && python scripts/tools_demo.py

test:
	cd backend && . .venv/bin/activate && pytest

test-live:
	cd backend && . .venv/bin/activate && RUN_LIVE_LLM_TESTS=1 pytest -v tests/test_runner_live.py

eval:
	cd backend && . .venv/bin/activate && python -m evals.run

lint:
	cd backend && . .venv/bin/activate && ruff check . && mypy app
	cd frontend && pnpm lint
