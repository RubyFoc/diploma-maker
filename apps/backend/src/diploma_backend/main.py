"""FastAPI application entrypoint for the diploma-maker backend.

Pipeline modules (llm_routing, sources, humanizer, formatting, feedback, billing) are added
incrementally per docs/architecture/overview.md; this module only wires up the app and the
health check used by scripts/smoke-compose.sh and docker-compose's healthcheck.
"""

from fastapi import FastAPI

app = FastAPI(title="diploma-maker backend")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check consumed by scripts/smoke-compose.sh and container orchestration."""
    return {"status": "ok"}
