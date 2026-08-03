# diploma-maker backend

FastAPI service. See `../../docs/architecture/overview.md` for the pipeline-stage module shape.

## Run locally
```
uv sync
uv run uvicorn diploma_backend.main:app --reload
```

## Test
```
uv run pytest -q
```

## Lint
```
uv run ruff check .
```
