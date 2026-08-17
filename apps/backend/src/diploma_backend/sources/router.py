"""HTTP endpoints for must-cite required sources (TASK-E14-2).

Scoped by `project_id` and the authenticated caller (TASK-E11-1), matching `projects.router`'s
ownership pattern; duplicated here as a small standalone helper rather than importing
`projects.router`'s private `_get_owned_project` across the module boundary (same reasoning
`locks.router` used for its own `_get_owned_chapter`).
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from diploma_backend.auth.dependencies import get_current_user_id
from diploma_backend.db import get_database
from diploma_backend.llm_routing.client import LLMRequestError
from diploma_backend.llm_routing.required_sources_parse import (
    PARSE_MAX_TOKENS,
    RequiredSourcesParseError,
    build_parse_messages,
    parse_response,
)
from diploma_backend.llm_routing.tasks import generate_with_retry_task
from diploma_backend.projects.service import get_project
from diploma_backend.sources.required import (
    RequiredSource,
    create_required_source,
    list_required_sources_for_project,
)

router = APIRouter(prefix="/projects", tags=["sources"])

_PARSE_TASK_TIMEOUT_SECONDS = 30.0


async def _check_owned_project(db: AsyncIOMotorDatabase, project_id: str, owner_id: str) -> None:
    """Raises `HTTPException(404)` if `project_id` doesn't exist or belongs to a different
    owner — deliberately the same status/detail either way, matching
    `projects.router._get_owned_project`'s identical rationale.
    """
    project = await get_project(db, project_id)
    if project is None or project.owner_id != owner_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Project '{project_id}' not found"
        )


class CreateRequiredSourceRequest(BaseModel):
    """Body for `POST /projects/{project_id}/required-sources`."""

    author: str
    title: str | None = None
    year: int | None = None


@router.post(
    "/{project_id}/required-sources",
    response_model=RequiredSource,
    status_code=status.HTTP_201_CREATED,
)
async def create_required_source_endpoint(
    project_id: str,
    body: CreateRequiredSourceRequest,
    db: AsyncIOMotorDatabase = Depends(get_database),
    owner_id: str = Depends(get_current_user_id),
) -> RequiredSource:
    """Declare a must-cite author/work for `project_id` (TASK-E14-2), scoped to the authenticated
    caller. Raises `HTTPException(404)` if `project_id` doesn't exist or isn't owned by the
    caller. Boosting these into generation is `projects.router`'s job (TASK-E14-3), not this
    endpoint's — this only records the requirement.
    """
    await _check_owned_project(db, project_id, owner_id)
    return await create_required_source(db, project_id, body.author, body.title, body.year)


@router.get("/{project_id}/required-sources", response_model=list[RequiredSource])
async def list_required_sources_endpoint(
    project_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
    owner_id: str = Depends(get_current_user_id),
) -> list[RequiredSource]:
    """List `project_id`'s declared must-cite sources, scoped to the authenticated caller.
    Raises `HTTPException(404)` if `project_id` doesn't exist or isn't owned by the caller.
    """
    await _check_owned_project(db, project_id, owner_id)
    return await list_required_sources_for_project(db, project_id)


class ParseRequiredSourcesBulkRequest(BaseModel):
    """Body for `POST /projects/required-sources/parse-bulk`."""

    text: str


class ParsedRequiredSource(BaseModel):
    """One auto-detected candidate from `parse_required_sources_bulk_endpoint` — not yet
    persisted as a `RequiredSource` (that needs a `project_id`, which doesn't exist yet during
    new-project setup)."""

    author: str
    title: str | None = None


@router.post("/required-sources/parse-bulk", response_model=list[ParsedRequiredSource])
async def parse_required_sources_bulk_endpoint(
    body: ParseRequiredSourcesBulkRequest,
    _owner_id: str = Depends(get_current_user_id),
) -> list[ParsedRequiredSource]:
    """Auto-detect individual author/work entries out of a block of pasted bibliography text
    (user request), so a user with many must-cite sources doesn't have to add each one through
    `create_required_source_endpoint`'s one-at-a-time form.

    Project-independent by design (fixed path, no `{project_id}`): runs during new-project setup,
    before a project exists to scope a `RequiredSource` to. Requires auth like every other
    endpoint in this router, but doesn't otherwise touch project ownership. Returns an empty list
    for blank input. Raises `HTTPException(502)` if the DeepSeek call itself fails, or if its
    response couldn't be parsed as the expected JSON shape (both genuine infra/model failures,
    not user error).
    """
    text = body.text.strip()
    if not text:
        return []

    messages = build_parse_messages(text)

    def _run_parse() -> str:
        return generate_with_retry_task.delay("fast", messages, max_tokens=PARSE_MAX_TOKENS).get(
            timeout=_PARSE_TASK_TIMEOUT_SECONDS
        )

    try:
        content = await asyncio.to_thread(_run_parse)
    except LLMRequestError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    try:
        entries = parse_response(content)
    except RequiredSourcesParseError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return [ParsedRequiredSource(**entry) for entry in entries]
