.PHONY: setup dev backend frontend test eval lint

setup:
	cd backend && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
	cd backend && .venv/bin/python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"
	cd frontend && npm install

backend:
	cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

dev:
	$(MAKE) -j2 backend frontend

test:
	cd backend && .venv/bin/pytest -q
	cd frontend && npm test -- --run

eval:
	cd backend && .venv/bin/python ../eval/run_eval.py

lint:
	cd backend && .venv/bin/ruff check app tests
