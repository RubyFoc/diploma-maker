"""FastAPI application entrypoint for the diploma-maker backend.

Pipeline modules (llm_routing, sources, humanizer, formatting, feedback, billing) are added
incrementally per docs/architecture/overview.md; this module only wires up the app and the
health check used by scripts/smoke-compose.sh and docker-compose's healthcheck.
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from diploma_backend.auth.router import router as auth_router
from diploma_backend.formatting.router import router as formatting_router
from diploma_backend.plagiarism.router import router as plagiarism_router
from diploma_backend.projects.router import router as projects_router
from diploma_backend.projects.router import versions_router

app = FastAPI(title="diploma-maker backend")

# The frontend (Vite dev server) runs on a different origin (e.g. http://localhost:5173) than
# this API (e.g. http://localhost:8010), so the browser enforces CORS on every fetch call unless
# this origin is explicitly allowlisted here — without it, every request from the browser fails
# silently at the network layer (the backend never even sees it) despite working fine via curl.
# `CORS_ALLOWED_ORIGINS` is comma-separated to support multiple deployed frontend origins later.
_cors_allowed_origins = [
    origin.strip()
    for origin in os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(formatting_router)
app.include_router(plagiarism_router)
app.include_router(projects_router)
app.include_router(versions_router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check consumed by scripts/smoke-compose.sh and container orchestration."""
    return {"status": "ok"}
