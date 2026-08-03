# Backend Stack Conventions

- Package/dependency management: `uv` (`apps/backend/pyproject.toml`).
- Web framework: FastAPI, ASGI via `uvicorn`.
- Primary DB: MongoDB via `motor` (async driver) — document configs, users, wallet/transactions.
- Vector DB: Qdrant client — draft/literature embeddings for RAG citation verification.
- Document export: `python-docx` for the Markdown -> `.docx` assembly engine.
- LLM access: DeepSeek API — route to a fast/cheap model for structure/parsing/formatting tasks
  and a heavy/reasoning model for synthesis/complex reasoning, per PRD §3.1.
- Typing: Python 3.12+, type hints on public functions; builtin generics (`dict`, `list`) and
  PEP604 unions (`X | None`) — no `typing.Dict`/`Optional`/`Union`.
- Lint/format: `ruff`.
- Tests: `pytest`, mock LLM/DB calls in unit tests; integration tests behind a `mongomock`/local
  Qdrant fixture.
