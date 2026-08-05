"""Formatting-sample upload and institution-selection endpoints (TASK-E05-2, TASK-E05-3).

`POST /formatting/institution-configs/upload` turns a `.docx` formatting sample into a stored
`InstitutionConfig` (ADR-0005). `GET /formatting/institution-configs` and
`GET /formatting/institution-configs/{institution_id}` expose the storage-layer listing/lookup
from `formatting.service` (TASK-E05-1) so the onboarding flow (TASK-E10-1) can populate a
university dropdown and fetch the selected institution's full config.

`POST /formatting/institution-configs/auto-detect` is ADR-0005's 2026-08-05 addendum
(`source="auto"`): tries to find and extract a named university's formatting requirements from
the web (`formatting.discovery`) instead of requiring a manual upload.
"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from diploma_backend.db import get_database
from diploma_backend.formatting.discovery import (
    FormattingDiscoveryError,
    discover_institution_config,
)
from diploma_backend.formatting.models import Headings, InstitutionConfig
from diploma_backend.formatting.service import (
    create_institution_config,
    get_institution_config,
    list_institution_configs,
)
from diploma_backend.formatting.upload import (
    FormattingSampleParseError,
    parse_formatting_sample,
    save_uploaded_sample,
)

router = APIRouter(prefix="/formatting", tags=["formatting"])


class AutoDetectRequest(BaseModel):
    """Request body for `POST /formatting/institution-configs/auto-detect`."""

    institution_name: str = Field(min_length=1)


@router.post(
    "/institution-configs/upload",
    response_model=InstitutionConfig,
    status_code=status.HTTP_201_CREATED,
)
async def upload_institution_config(
    institution_name: str = Form(min_length=1),
    file: UploadFile = File(...),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> InstitutionConfig:
    """Save `file` as a raw formatting sample and create an `InstitutionConfig` from it.

    Parses page/font/citation-style fields via `formatting.upload.parse_formatting_sample`.
    `headings`, `citation_rules`, and `toc_rules` are left at ADR-0005's empty-dict defaults and
    `accuracy_weight` at `0.0` — extracting those is out of scope for this task. Raises
    `HTTPException(422)` if `file` isn't a parseable `.docx` sample (fail-closed: this endpoint
    never guesses page/font values it couldn't read).
    """
    content = await file.read()

    try:
        parsed = parse_formatting_sample(content)
    except FormattingSampleParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    file_id = save_uploaded_sample(content)

    config = InstitutionConfig(
        institution_id=file_id,
        institution_name=institution_name,
        source="upload",
        page=parsed.page,
        font=parsed.font,
        headings=Headings(),
        citation_style=parsed.citation_style,
        citation_rules={},
        toc_rules={},
        accuracy_weight=0.0,
        raw_sample_reference=file_id,
    )
    return await create_institution_config(db, config)


@router.post(
    "/institution-configs/auto-detect",
    response_model=InstitutionConfig,
    status_code=status.HTTP_201_CREATED,
)
async def auto_detect_institution_config(
    request: AutoDetectRequest,
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> InstitutionConfig:
    """Try to auto-discover `request.institution_name`'s formatting requirements from the web.

    Delegates to `formatting.discovery.discover_institution_config`. On a `"found"` result,
    persists the built `source="auto"` config and returns it with `201`. Raises
    `HTTPException(404)` if nothing could be determined (a real, expected outcome — like a
    citation-verification rejection elsewhere in this codebase — not a server error) so the
    frontend can fall back to prompting for a manual upload or the default GOST template.
    Raises `HTTPException(502)` if the search step itself failed (genuine infra failure).
    """
    try:
        result = await discover_institution_config(request.institution_name)
    except FormattingDiscoveryError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    if result.status == "not_found" or result.config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Could not automatically determine formatting requirements for "
                f"'{request.institution_name}'. Please upload a sample document or use the "
                f"default GOST template instead."
            ),
        )

    return await create_institution_config(db, result.config)


@router.get("/institution-configs", response_model=list[InstitutionConfig])
async def list_institution_configs_endpoint(
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> list[InstitutionConfig]:
    """List all stored institution configs, for populating a university dropdown.

    Returns full `InstitutionConfig` objects rather than a slimmer `{institution_id,
    institution_name}` summary: the dropdown only needs those two fields, but a separate summary
    model would duplicate ADR-0005's schema and need to stay in sync with it for no real benefit
    (the config list is small and this isn't a hot path), so the frontend just picks the fields
    it needs from the full object.
    """
    return await list_institution_configs(db)


@router.get("/institution-configs/{institution_id}", response_model=InstitutionConfig)
async def get_institution_config_endpoint(
    institution_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> InstitutionConfig:
    """Fetch a single institution config by `institution_id`.

    Used after the user selects a university from the dropdown (TASK-E10-1) to load its full
    formatting config. Raises `HTTPException(404)` if `institution_id` doesn't exist.
    """
    config = await get_institution_config(db, institution_id)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Institution config '{institution_id}' not found",
        )
    return config
