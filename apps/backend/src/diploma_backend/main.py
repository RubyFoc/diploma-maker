"""FastAPI application entrypoint for the diploma-maker backend.

Pipeline modules (llm_routing, sources, humanizer, formatting, feedback, billing) are added
incrementally per docs/architecture/overview.md; this module only wires up the app and the
health check used by scripts/smoke-compose.sh and docker-compose's healthcheck.
"""

from fastapi import FastAPI

from diploma_backend.auth.router import router as auth_router
from diploma_backend.formatting.router import router as formatting_router

app = FastAPI(title="diploma-maker backend")
app.include_router(auth_router)
app.include_router(formatting_router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check consumed by scripts/smoke-compose.sh and container orchestration."""
    return {"status": "ok"}
